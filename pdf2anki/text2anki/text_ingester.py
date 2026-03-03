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
        """Extrahiert JSON aus LLM-Antwort (robust gegen Markdown-Code-Blöcke)."""
        cleaned = response.strip()
        # Entferne ```json ... ``` oder ``` ... ``` Wrapper
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned.strip(), flags=re.MULTILINE)
        return json.loads(cleaned.strip())


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
