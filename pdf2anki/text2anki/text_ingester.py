#!/usr/bin/env python3
"""
text_ingester.py — IngestorBase + TextFileIngestor: Text → new_cards_output.json

Liest eine oder mehrere .txt-Dateien (vorkonvertierte PDFs, Vorlesungsnotizen, etc.),
ruft ein LLM auf und erzeugt new_cards_output.json im Schema des Integration-Workflows.

Option-3-ready: IngestorBase definiert das Plugin-Interface für Milestone 3.
"""

import json
import os
import re
from typing import List

from .console_utils import safe_print
from .llm_helper import get_llm_decision
from .project_config import ProjectConfig


# ─────────────────────────────────────────────────────────────────────────────
# new_cards_output.json Schema (Referenz)
# ─────────────────────────────────────────────────────────────────────────────

NEW_CARDS_SCHEMA_EXAMPLE = {
    "new_cards": [
        {
            "front": "Was ist X?",
            "back": "X ist ...",
            "collection": "collection_0_Kapitel1",
            "category": "a_grundlagen"
        }
    ]
}

# ─────────────────────────────────────────────────────────────────────────────
# Abstract Base (Option 3 Plugin-Interface)
# ─────────────────────────────────────────────────────────────────────────────

class IngestorBase:
    """Abstrakte Basis für Text-Ingestoren. Für Milestone 3 Plugin-System."""

    def ingest(self, sources: List[str], config: ProjectConfig) -> dict:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────
# TextFileIngestor
# ─────────────────────────────────────────────────────────────────────────────

class TextFileIngestor(IngestorBase):
    """Liest .txt-Dateien und generiert Anki-Karten via LLM."""

    def ingest(self, sources: List[str], config: ProjectConfig) -> dict:
        """
        Liest sources, ruft LLM auf, gibt new_cards_output.json Schema zurück.

        Args:
            sources: Liste von Pfaden zu .txt Dateien.
            config: ProjectConfig des Projekts.

        Returns:
            Dict im new_cards_output.json Schema.
        """
        material = self._load_texts(sources)
        collection_context = self._build_collection_context(config)
        schema_example = json.dumps(NEW_CARDS_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)

        prompt = self._build_prompt(
            domain=config.domain,
            language=config.language,
            collection_context=collection_context,
            material=material,
            schema_example=schema_example,
        )

        safe_print(f"  -> 🤖 Rufe LLM auf ({config.get_llm_model()}) für Ingestion von {len(sources)} Datei(en)...")
        response = get_llm_decision(
            header_context="",
            prompt_body=prompt,
            model=config.get_llm_model(),
            json_mode=True,
        )

        if not response:
            safe_print("  -> ❌ LLM hat keine Antwort zurückgegeben.", "ERROR")
            return {"new_cards": []}

        result = self._parse_response(response)
        n = len(result.get("new_cards", []))
        safe_print(f"  -> ✅ LLM hat {n} Karten generiert.")
        return result

    # ── Hilfsmethoden ────────────────────────────────────────────────────────

    def _load_texts(self, sources: List[str]) -> str:
        """Liest alle Quelldateien und konkateniert ihren Inhalt."""
        parts = []
        for path in sources:
            if not os.path.exists(path):
                safe_print(f"  -> ⚠️ Datei nicht gefunden, überspringe: {path}", "WARNING")
                continue
            with open(path, encoding='utf-8') as f:
                parts.append(f.read())
        return "\n\n---\n\n".join(parts)

    def _build_collection_context(self, config: ProjectConfig) -> str:
        """Erstellt eine lesbare Übersicht der Kollektionen für den LLM-Prompt."""
        lines = []
        for key, cfg in config.collections.items():
            display = cfg.get('display_name', key)
            desc = cfg.get('description', '')
            cat_line = f"  - Key: \"{key}\"  →  {display}"
            if desc:
                cat_line += f"\n    Beschreibung: {desc}"
            lines.append(cat_line)
        return "\n".join(lines)

    def _build_prompt(self, domain: str, language: str, collection_context: str,
                      material: str, schema_example: str) -> str:
        """Baut den LLM-Prompt für die Kartengeneration."""
        templates = {
            'de': (
                f"Du bist ein Experte für {domain}. Erstelle hochwertige Anki-Lernkarten "
                f"aus dem folgenden Material.\n\n"
                f"KOLLEKTIONSSTRUKTUR (nutze exakt diese Keys für 'collection'):\n{collection_context}\n\n"
                f"AUSGABEFORMAT (JSON, exakt dieses Schema):\n{schema_example}\n\n"
                f"MATERIAL:\n{material}\n\n"
                f"Antworte NUR mit dem JSON-Objekt. Kein Prosatext davor oder danach. "
                f"Verwende ausschließlich die oben aufgeführten collection-Keys."
            ),
            'en': (
                f"You are an expert in {domain}. Create high-quality Anki flashcards "
                f"from the following material.\n\n"
                f"COLLECTION STRUCTURE (use exactly these keys for 'collection'):\n{collection_context}\n\n"
                f"OUTPUT FORMAT (JSON, exactly this schema):\n{schema_example}\n\n"
                f"MATERIAL:\n{material}\n\n"
                f"Reply ONLY with the JSON object. No prose before or after. "
                f"Use only the collection keys listed above."
            ),
        }
        return templates.get(language, templates['en'])

    def _parse_response(self, response: str) -> dict:
        """Extrahiert JSON aus LLM-Antwort (robust gegen Markdown, Prose, LaTeX-Escaping, Trunkierung)."""
        text = response.strip()
        if not text:
            return {"new_cards": []}

        # Strategy 1: direct parse (with repair for LaTeX backslashes etc.)
        result = self._try_parse_json(text)
        if result is not None:
            return self._normalize_result(result)

        # Strategy 2: extract from markdown fences (try all matches)
        for fence_match in re.finditer(r'```\w*\s*\n(.*?)\n\s*```', text, re.DOTALL):
            result = self._try_parse_json(fence_match.group(1).strip())
            if result is not None:
                return self._normalize_result(result)

        # Strategy 3: brace matching (first { to balanced })
        start = text.find('{')
        if start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        result = self._try_parse_json(text[start:i + 1])
                        if result is not None:
                            return self._normalize_result(result)
                        break

        # Strategy 4: greedy — first { to last }
        if start is not None and start != -1:
            last_brace = text.rfind('}')
            if last_brace > start:
                result = self._try_parse_json(text[start:last_brace + 1])
                if result is not None:
                    return self._normalize_result(result)

        # Strategy 5: truncated JSON recovery
        if start is not None and start != -1:
            result = self._try_parse_truncated(text[start:])
            if result is not None:
                n = len(result.get("new_cards", []))
                safe_print(f"  -> ⚠️ JSON war abgeschnitten — {n} Karten aus unvollständiger Antwort gerettet.", "WARNING")
                return self._normalize_result(result)

        # All strategies failed — dump raw response for debugging
        self._dump_debug_response(response)
        safe_print(f"  -> ⚠️ JSON-Parsing fehlgeschlagen. Antwort-Länge: {len(text)} Zeichen.", "WARNING")
        return {"new_cards": []}

    # ── JSON repair helpers ───────────────────────────────────────────────────

    def _try_parse_json(self, text: str):
        """Parse JSON, falling back to repair for LLM issues (LaTeX escapes, trailing commas)."""
        # Try direct parse first — preserves valid \b and \f if present
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Fall back to repair (fixes \delta, \Sigma, \frac, trailing commas, etc.)
        repaired = self._repair_json(text)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None

    def _repair_json(self, text: str) -> str:
        """Fix invalid backslash escapes and trailing commas in LLM-generated JSON.

        LLMs generating STEM content (LaTeX formulas, regex, file paths) produce
        invalid JSON escapes like \\delta, \\Sigma, \\frac, \\in, \\{, \\}.
        Python's json.loads() strictly rejects these.  This method escapes them
        as \\\\delta etc., preserving the original content in the parsed string.

        Note: \\b (backspace) and \\f (form feed) are also escaped because they
        never appear intentionally in Anki card content but ARE common LaTeX
        prefixes (\\beta, \\begin, \\frac, \\forall).  This only runs as a
        fallback after direct json.loads() has already failed.
        """
        # Step 1: Protect already-escaped backslashes (\\) with a placeholder
        PLACEHOLDER = '\x00ESCAPED_BS\x00'
        text = text.replace('\\\\', PLACEHOLDER)
        # Step 2: Fix \uXXXX where XXXX is NOT 4 hex digits (e.g., \undefined)
        text = re.sub(r'\\u(?![0-9a-fA-F]{4})', PLACEHOLDER + 'u', text)
        # Step 3: Fix remaining single backslashes not followed by valid JSON escape chars
        # Only preserve: " \ / n r t (and \uXXXX handled above)
        # Intentionally escape \b (backspace) and \f (form feed) — these are
        # virtually always LaTeX (\beta, \frac) in STEM card content.
        text = re.sub(r'\\(?!["\\/nrtu])', PLACEHOLDER, text)
        # Step 4: Restore all placeholders as properly escaped backslashes
        text = text.replace(PLACEHOLDER, '\\\\')
        # Step 5: Fix trailing commas in arrays/objects: ,] or ,}
        text = re.sub(r',(\s*[\]}])', r'\1', text)
        return text

    def _try_parse_truncated(self, text: str):
        """Attempt to recover cards from truncated JSON by backtracking to the last complete card.

        Scans } positions from right to left, counting unclosed delimiters at each
        candidate cut point.  The first candidate that produces valid JSON wins —
        this preserves as many complete cards as possible.
        """
        repaired = self._repair_json(text)
        # Find all } positions — potential cut points
        brace_positions = [i for i, c in enumerate(repaired) if c == '}']
        if not brace_positions:
            return None
        for pos in reversed(brace_positions):
            candidate = repaired[:pos + 1]
            # Count unclosed delimiters outside strings
            depth_b = depth_k = 0
            in_str = esc = False
            for ch in candidate:
                if esc:
                    esc = False
                    continue
                if in_str:
                    if ch == '\\':
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == '{':
                    depth_b += 1
                elif ch == '}':
                    depth_b -= 1
                elif ch == '[':
                    depth_k += 1
                elif ch == ']':
                    depth_k -= 1
            if depth_b < 0 or depth_k < 0:
                continue
            # Try both possible closing orders
            for closing in (']' * depth_k + '}' * depth_b,
                            '}' * depth_b + ']' * depth_k):
                try:
                    result = json.loads(candidate + closing)
                    if isinstance(result, dict):
                        return result
                except json.JSONDecodeError:
                    continue
        return None

    def _normalize_result(self, result) -> dict:
        """Ensure result is in the expected {"new_cards": [...]} format."""
        if isinstance(result, list):
            return {"new_cards": result}
        if isinstance(result, dict) and "new_cards" not in result:
            for key in ("cards", "flashcards", "anki_cards"):
                if key in result and isinstance(result[key], list):
                    return {"new_cards": result[key]}
            if "front" in result and "back" in result:
                return {"new_cards": [result]}
        return result

    def _dump_debug_response(self, response: str):
        """Save raw LLM response to file for debugging when all parse strategies fail."""
        debug_path = os.path.join(os.getcwd(), "llm_response_debug.txt")
        try:
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write(response)
            safe_print(f"  -> Raw-Antwort gespeichert: {debug_path}", "WARNING")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Convenience-Wrapper
# ─────────────────────────────────────────────────────────────────────────────

def ingest_text(sources: List[str], config: ProjectConfig, output_path: str) -> bool:
    """
    Convenience-Wrapper: ingested Texte und schreibt new_cards_output.json.

    Args:
        sources: Liste von Pfaden zu .txt Dateien.
        config: ProjectConfig des Projekts.
        output_path: Zielpfad für new_cards_output.json.

    Returns:
        True bei Erfolg.
    """
    ingestor = TextFileIngestor()
    result = ingestor.ingest(sources, config)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    safe_print(f"  ✅ Ingestion abgeschlossen: {output_path} ({len(result.get('new_cards', []))} Karten)")
    return True
