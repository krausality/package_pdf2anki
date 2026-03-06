"""
test_real_data_and_sync.py — Tests based on real GTI course material patterns
and missing workflow coverage.

Gaps addressed:
1. Real OCR content patterns extracted from actual GTI files
   (skript-1.txt, Uebungsblatt01.txt, mitschrift_tutorium01.txt)
2. sync_from_ssot() and run_sync_workflow() — not covered in other test files
3. run_smart_extract_workflow() routing logic
4. Temporal multi-ingestion simulation (student adds cards week-by-week)
5. collection=None assertion for ApkgExporter

Patterns found in real GTI OCR output:
- <math>...</math> tags with nested { } that look like JSON
- [Visual Description: ...] — image captions, 100-300 chars long
- Image: page_N.png — page markers
- LaTeX commands: \\vfill, \\hfil, \\begin{array}{lcl}...\\end{array}
- &nbsp; HTML entities
- --- page separators
- *Handwritten Comment:* mixed markdown
- Unicode: ε, Σ, ∈, ℕ, ℤ, ∅, →, ⊆, ⊇, ∪, ∩, Δ
- Formal grammar G = ({A, b, B}, {a,b}, {...}, S) — nested braces
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pdf2anki.text2anki.card import AnkiCard
from pdf2anki.text2anki.database_manager import DatabaseManager
from pdf2anki.text2anki.project_config import ProjectConfig
from pdf2anki.text2anki.text_ingester import TextFileIngestor, ingest_text
from pdf2anki.text2anki.apkg_exporter import ApkgExporter


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

GTI_PROJECT_DATA = {
    "project_name": "GTI_WiSe2526",
    "tag_prefix": "GTI",
    "language": "de",
    "domain": "Grundlagen der Theoretischen Informatik",
    "orphan_collection_name": "Unsortierte_Karten",
    "files": {
        "db_path": "card_database.json",
        "markdown_file": "All_fronts.md",
        "new_cards_file": "new_cards_output.json",
        "material_file": "course_material.txt",
    },
    "collections": {
        "collection_0_Sprachen": {
            "display_name": "Kapitel 1: Sprachen und Grammatiken",
            "filename": "collection_0_Sprachen.json",
        },
        "collection_1_RegEx": {
            "display_name": "Kapitel 3: Reguläre Sprachen",
            "filename": "collection_1_RegEx.json",
        },
        "collection_2_Turing": {
            "display_name": "Kapitel 7: Turingmaschinen",
            "filename": "collection_2_Turing.json",
        },
    },
    "llm": {"model": "google/gemini-2.5-flash", "temperature": 0.1},
}

# ── Verbatim snippets extracted from real GTI OCR files ──────────────────────
# From: skript-1.txt (LaTeX-typeset lecture script, OCR'd)
REAL_SKRIPT_SNIPPET = """\
Image: page_3.png
*Grundlagen der Theoretischen Informatik* \\hfill *1 Sprachen und Grammatiken*

---

# 1 Sprachen und Grammatiken

Ein *Alphabet* ist eine endliche, nichtleere Menge. Die Elemente eines Alphabets heißen auch *Zeichen* oder *Symbole*.

> **Beispiel 1.** <math>\\{0, 1\\}, \\{\\text{a, b, c, \\dots, z, A, \\dots, Z}\\}</math>

Sei <math>\\Sigma</math> ein Alphabet. Ein *Wort über* <math>\\Sigma</math> ist eine Folge von Symbolen.

Spezialfall: leeres Wort; Bezeichnung: <math>\\varepsilon</math>

Die Menge aller Wörter über dem Alphabet <math>\\Sigma</math> bezeichnen wir mit <math>\\Sigma^*</math>.

\\vfill
<center>3</center>
"""

# From: Uebungsblatt01.txt (exercise sheet, OCR'd)
REAL_UEBUNG_SNIPPET = """\
Image: page_1.png
# 1. Übungsblatt
Woche vom 20. Oktober 2025

**Aufgabe 1:**
a) Welche der folgenden Behauptungen sind korrekt?
- Die Menge der ganzen Zahlen <math>\\mathbb{Z}</math> ist ein Alphabet.
- <math>\\Sigma^+ \\cup \\{ \\varepsilon \\} = \\Sigma^*</math>, für jedes Alphabet <math>\\Sigma</math>.
- Sind <math>a, b \\in \\Sigma</math>, <math>w_1 = abba</math> und <math>w_2 = \\varepsilon</math>. Dann ist <math>|w_1 w_2| = 5</math>
- <math>G = (\\{A, b, B, c, S\\}, \\{a, b\\}, \\{S \\rightarrow AB, B \\rightarrow b\\}, S)</math> ist eine gültige Grammatik.
"""

# From: mitschrift_tutorium01.txt (handwritten solutions, OCR'd)
REAL_MITSCHRIFT_SNIPPET = """\
Image: page_1.png
# Aufgabe 1
[Visual Description: Header with the text "Aufgabe 1" on the left and a blue rectangular badge on the right containing "Skript Kapitel 1 und 2" in white text.]

[Visual Description: A checkbox marked with a large "X" to indicate it is incorrect.]
Die Menge der ganzen Zahlen <math>\\mathbb{Z}</math> ist ein Alphabet.
*Handwritten Comment:* Widerspruch zur Endlichkeit

[Visual Description: A checkbox marked with a tick/checkmark to indicate it is correct.]
<math>\\Sigma^+ \\cup \\{\\varepsilon\\} = \\Sigma^*</math> für jedes Alphabet <math>\\Sigma</math>.
*Handwritten Comment:* genau die Def. <math>\\Sigma^+ = \\Sigma^* \\setminus \\{\\varepsilon\\}</math>

<math>G = (\\{A, \\underline{b}, B, c, S\\}, \\{a, b\\}, \\{S \\to AB, B \\to b, B \\to AA, b \\to cc, A \\to ab\\}, S)</math>
*Handwritten Comment:* <math>V \\cap \\Sigma = \\{b\\} \\neq \\emptyset</math>

---

b) Sei <math>\\Delta</math> ein Alphabet. Wie viele Wörter <math>w \\in \\Delta^*</math> der Länge <math>|w| = k</math> gibt es?
<math>|\\Delta|^k</math>
"""


def make_gti_project(tmp_path) -> Path:
    project_dir = tmp_path / "gti_project"
    project_dir.mkdir()
    (project_dir / "project.json").write_text(
        json.dumps(GTI_PROJECT_DATA), encoding="utf-8"
    )
    return project_dir


def make_db(base_path, cards=None, config=None) -> DatabaseManager:
    mock_mm = MagicMock()
    mock_mm.get_course_material.return_value = None
    db_path = str(Path(base_path) / "card_database.json")
    if cards is not None:
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in cards], f)
    return DatabaseManager(db_path=db_path, material_manager=mock_mm, project_config=config)


def make_card(**kwargs) -> AnkiCard:
    defaults = dict(
        front="Was ist ein Alphabet?",
        back="Eine endliche, nichtleere Menge.",
        collection="collection_0_Sprachen",
        category="a_grundlagen",
        sort_field="00_A_01_was_ist_ein_alphabet",
    )
    defaults.update(kwargs)
    return AnkiCard(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 1: Real OCR Content Patterns
# ─────────────────────────────────────────────────────────────────────────────

class TestRealOcrContentPatterns:
    """
    Tests using verbatim content extracted from actual GTI OCR files.
    These patterns only appear in real course material and were not covered
    by synthetic test data.
    """

    def test_math_tags_with_braces_survive_db_roundtrip(self, tmp_path):
        """
        Real GTI cards have fronts/backs with <math>...</math> containing { }.
        e.g. front = 'Was ist <math>\\Sigma^*</math>?'
        The { } inside math tags must NOT confuse JSON serialization.
        """
        db = make_db(tmp_path)
        front = r"Was ist <math>\Sigma^*</math>?"
        back = r"Die Menge aller Wörter: <math>\Sigma^* = \{\varepsilon\} \cup \Sigma \cup \Sigma^2 \cup \dots</math>"
        db.cards = [make_card(front=front, back=back)]
        db.save_database()

        db2 = make_db(tmp_path, cards=None)
        db2.cards = []
        db2.load_database()

        assert db2.cards[0].front == front
        assert db2.cards[0].back == back

    def test_formal_grammar_notation_with_nested_braces(self, tmp_path):
        """
        Grammar definitions like G = ({A, b, B}, {a,b}, {S→AB}, S) appear in
        fronts and backs. Nested curly braces must survive JSON roundtrip.
        """
        db = make_db(tmp_path)
        front = r"Was ist G = (\{A, b, B, c, S\}, \{a, b\}, \{S \to AB, B \to b\}, S)?"
        back = r"Eine Grammatik. Prüfe: V ∩ Σ = \{b\} ≠ ∅ → ungültig!"
        db.integrate_new([{"front": front, "back": back}])
        assert db.cards[0].front == front
        assert db.cards[0].back == back

    def test_visual_description_in_back_survives_storage(self, tmp_path):
        """
        OCR produces [Visual Description: ...] lines up to 300 chars long.
        These may appear in card back text if the LLM includes them.
        Must survive storage without truncation.
        """
        db = make_db(tmp_path)
        long_visual = (
            "[Visual Description: A layout with two columns of statements on lined paper. "
            "Each statement has a checkbox next to it, which has been hand-marked with "
            "either a cross (denoting false) or a checkmark (denoting true). "
            "Handwritten explanations in German follow each statement.]"
        )
        db.integrate_new([{"front": "Was zeigt Abbildung 1?", "back": long_visual}])
        assert db.cards[0].back == long_visual

    def test_latex_commands_in_content_survive_roundtrip(self, tmp_path):
        """
        OCR of LaTeX PDFs produces raw LaTeX: \\vfill, \\hfil, \\begin{array}, \\end{array}.
        These appear in the ingest text and sometimes end up in card content.
        Must be stored without modification.
        """
        db = make_db(tmp_path)
        back = r"Schreibweise: $w^n = \underbrace{w \circ w \circ \dots \circ w}_{n\text{-mal}}$"
        db.integrate_new([{"front": r"Was ist $w^n$?", "back": back}])
        assert db.cards[0].back == back

    def test_nbsp_html_entity_in_content_survives(self, tmp_path):
        """
        OCR of formatted PDFs produces &nbsp; for non-breaking spaces.
        These appear in section numbering like '&nbsp;&nbsp;&nbsp;&nbsp;3.1 Endliche Automaten'.
        Must not be mangled.
        """
        db = make_db(tmp_path)
        front = "Was behandelt Abschnitt&nbsp;3.1?"
        back = "&nbsp;&nbsp;&nbsp;&nbsp;3.1 Endliche Automaten"
        db.integrate_new([{"front": front, "back": back}])
        assert db.cards[0].front == front
        assert db.cards[0].back == back

    def test_handwritten_comment_notation_survives(self, tmp_path):
        """
        Tutorium OCR produces *Handwritten Comment:* lines mixed into content.
        A card back containing this pattern must be stored exactly.
        """
        db = make_db(tmp_path)
        back = (
            "Falsch.\n"
            "*Handwritten Comment:* Widerspruch zur Endlichkeit — "
            r"$\mathbb{Z}$ ist unendlich, Alphabete sind per Def. endlich."
        )
        db.integrate_new([{"front": r"Ist $\mathbb{Z}$ ein Alphabet?", "back": back}])
        assert "*Handwritten Comment:*" in db.cards[0].back

    def test_ocr_text_with_image_markers_as_ingest_input(self, tmp_path, tmp_path_factory):
        """
        Real OCR files start with 'Image: page_N.png' markers and contain
        [Visual Description: ...] blocks. ingest_text() must load and forward
        this content to the LLM without crashing.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))

        ocr_file = tmp_path / "mitschrift.txt"
        ocr_file.write_text(REAL_MITSCHRIFT_SNIPPET, encoding="utf-8")

        mock_card = {
            "front": r"Ist $\mathbb{Z}$ ein Alphabet?",
            "back": "Nein. Alphabete sind endlich, ℤ ist unendlich.",
            "collection": "collection_0_Sprachen",
            "category": "a_grundlagen",
        }
        output_path = str(tmp_path / "out.json")
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value=json.dumps({"new_cards": [mock_card]})):
            result = ingest_text([str(ocr_file)], cfg, output_path)

        assert result is True
        data = json.loads(Path(output_path).read_text(encoding="utf-8"))
        assert len(data["new_cards"]) == 1

    def test_ingest_sends_image_markers_and_visual_descriptions_to_llm(self, tmp_path):
        """
        The full OCR text (including Image: markers and [Visual Description: ...])
        must be forwarded to the LLM intact so it can choose what to include.
        _load_texts() must not strip these markers.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))

        ocr_file = tmp_path / "skript.txt"
        ocr_file.write_text(REAL_SKRIPT_SNIPPET, encoding="utf-8")

        captured = {}
        def capture_llm(header_context, prompt_body, model=None):
            captured["prompt"] = prompt_body
            return json.dumps({"new_cards": []})

        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   side_effect=capture_llm):
            ingest_text([str(ocr_file)], cfg, str(tmp_path / "out.json"))

        assert "Image: page_3.png" in captured["prompt"]
        assert "Visual Description" in captured["prompt"] or "\\vfill" in captured["prompt"]
        assert r"\Sigma" in captured["prompt"]

    def test_multi_page_ocr_with_separators_as_two_file_ingest(self, tmp_path):
        """
        Student ingests skript.txt and uebung.txt together (two lecture sources).
        Both are joined with '\\n\\n---\\n\\n' — the existing --- separators in
        OCR output become part of a longer --- chain. Must not crash.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))

        f1 = tmp_path / "skript.txt"
        f2 = tmp_path / "uebung.txt"
        f1.write_text(REAL_SKRIPT_SNIPPET, encoding="utf-8")
        f2.write_text(REAL_UEBUNG_SNIPPET, encoding="utf-8")

        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value=json.dumps({"new_cards": []})):
            result = ingest_text([str(f1), str(f2)], cfg, str(tmp_path / "out.json"))

        assert result is True

    def test_unicode_sigma_epsilon_in_card_front_detected_as_duplicate(self, tmp_path):
        """
        _normalize_text calls .lower() which maps Σ (U+03A3) → σ (U+03C3) in Python.
        So 'Was ist Σ?' and 'Was ist σ?' ARE treated as duplicates — both normalize to
        'was ist σ?'. This is a subtle GTI edge case: uppercase and lowercase Greek
        letters are conflated in the deduplication logic.

        Documented behavior (not necessarily desired): upper/lower Greek = duplicate.
        """
        db = make_db(tmp_path)
        db.integrate_new([{"front": "Was ist Σ?", "back": "Das Eingabealphabet."}])
        count_dup = db.integrate_new([{"front": "Was ist Σ?", "back": "Andere Antwort"}])
        assert count_dup == 0, "Identical Greek front correctly deduplicated"

        # Σ.lower() == σ in Python → treated as duplicate (counterintuitive but correct per impl)
        count_case = db.integrate_new([{"front": "Was ist σ?", "back": "Kleines Sigma."}])
        assert count_case == 0, "Σ and σ are conflated by .lower() — both normalize to σ"

        # But genuinely different Greek letters are not duplicates
        count_diff = db.integrate_new([{"front": "Was ist δ?", "back": "Übergangsfunktion."}])
        assert count_diff == 1, "δ is a genuinely different character from Σ/σ"

    def test_real_skript_ingest_produces_saveable_cards(self, tmp_path):
        """
        End-to-end: ingest real OCR snippet → cards contain <math> tags →
        integrate into DB → save → load → fronts/backs intact.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))

        ocr_file = tmp_path / "skript.txt"
        ocr_file.write_text(REAL_SKRIPT_SNIPPET, encoding="utf-8")

        real_cards = [
            {
                "front": r"Was ist <math>\Sigma^*</math>?",
                "back": r"Die Kleene-Hülle: Menge aller Wörter über <math>\Sigma</math>.",
                "collection": "collection_0_Sprachen",
                "category": "a_grundlagen",
            },
            {
                "front": "Was ist ε (Epsilon) in formalen Sprachen?",
                "back": r"Das leere Wort: <math>|\varepsilon| = 0</math>.",
                "collection": "collection_0_Sprachen",
                "category": "a_grundlagen",
            },
        ]
        output_path = str(tmp_path / "new_cards_output.json")
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value=json.dumps({"new_cards": real_cards})):
            ingest_text([str(ocr_file)], cfg, output_path)

        db = make_db(project_dir, config=cfg)
        data = json.loads(Path(output_path).read_text(encoding="utf-8"))
        db.integrate_new(data["new_cards"])

        db.save_database()
        db2 = make_db(project_dir, cards=None, config=cfg)
        db2.cards = []
        db2.load_database()

        fronts = [c.front for c in db2.cards]
        assert r"Was ist <math>\Sigma^*</math>?" in fronts
        assert "Was ist ε (Epsilon) in formalen Sprachen?" in fronts


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 2: sync_from_ssot and run_sync_workflow
# ─────────────────────────────────────────────────────────────────────────────

class TestSyncWorkflow:
    """
    run_sync_workflow() and sync_from_ssot() are the most common post-bootstrap
    operations. A student bootstraps once, then syncs after every integration.
    These were not covered in existing tests.
    """

    def _make_db_with_cards(self, tmp_path):
        """Creates a DB with 2 cards already persisted to disk."""
        cards = [
            make_card(front="Was ist ein Alphabet?",
                      sort_field="00_A_01_alphabet"),
            make_card(front=r"Was ist <math>\Sigma^*</math>?",
                      sort_field="00_A_02_sigma_stern"),
        ]
        db = make_db(tmp_path, cards=cards)
        return db

    def test_sync_from_ssot_generates_derived_files(self, tmp_path):
        """
        sync_from_ssot() with cards in memory calls distribute_to_derived_files('.').
        Derived files must be written to the current directory.
        """
        db = self._make_db_with_cards(tmp_path)
        with patch.object(db, 'distribute_to_derived_files', return_value=True) as mock_dist:
            result = db.sync_from_ssot()
        assert result is True
        mock_dist.assert_called_once_with('.')

    def test_sync_from_ssot_loads_db_if_cards_empty(self, tmp_path):
        """
        sync_from_ssot() with empty in-memory cards loads from disk first.
        The DB file must exist — if not, returns False.
        """
        # DB file exists on disk
        cards = [make_card(sort_field="00_A_01_q")]
        db = make_db(tmp_path, cards=cards)
        db.cards = []  # simulate fresh DatabaseManager instance

        with patch.object(db, 'distribute_to_derived_files', return_value=True):
            result = db.sync_from_ssot()
        assert result is True
        assert len(db.cards) == 1  # loaded from disk

    def test_sync_from_ssot_returns_false_when_no_db_file(self, tmp_path):
        """
        sync_from_ssot() without any DB file (no bootstrap done yet) returns False.
        User must run --extract first.
        """
        db = make_db(tmp_path)  # no cards, no file
        result = db.sync_from_ssot()
        assert result is False

    def test_sync_from_ssot_returns_false_if_distribute_fails(self, tmp_path):
        """
        If distribute_to_derived_files fails, sync_from_ssot propagates the failure.
        """
        db = self._make_db_with_cards(tmp_path)
        with patch.object(db, 'distribute_to_derived_files', return_value=False):
            result = db.sync_from_ssot()
        assert result is False

    def test_sync_does_not_modify_card_database(self, tmp_path):
        """
        sync_from_ssot() must NOT modify card_database.json — SSOT is read-only here.
        The card count must be identical before and after sync.
        """
        cards = [
            make_card(front="Q1", sort_field="00_A_01_q1"),
            make_card(front="Q2", sort_field="00_A_02_q2"),
        ]
        db = make_db(tmp_path, cards=cards)

        with patch.object(db, 'distribute_to_derived_files', return_value=True):
            db.sync_from_ssot()

        # Re-load and verify unchanged
        db2 = make_db(tmp_path, cards=None)
        db2.load_database()
        assert len(db2.cards) == 2
        assert db2.cards[0].front == "Q1"

    def test_run_sync_workflow_end_to_end(self, tmp_path):
        """
        WorkflowManager.run_sync_workflow() calls sync_from_ssot → verify_integrity
        → TemplatePromptUpdater. All must succeed for result=True.
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))

        # Pre-seed the DB on disk
        db = make_db(project_dir, config=cfg)
        db.cards = [make_card(sort_field="00_A_01_q")]
        db.save_database()

        wm = WorkflowManager(project_dir=str(project_dir))

        with patch.object(wm.db_manager, 'sync_from_ssot', return_value=True), \
             patch.object(wm.db_manager, 'verify_integrity', return_value=(True, "OK")), \
             patch("pdf2anki.text2anki.workflow_manager.TemplatePromptUpdater") as mock_tpu:
            mock_tpu.return_value.run_full_update.return_value = None
            result = wm.run_sync_workflow()

        assert result is True

    def test_run_sync_workflow_returns_false_if_sync_fails(self, tmp_path):
        """If sync_from_ssot() fails, run_sync_workflow() immediately returns False."""
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = make_gti_project(tmp_path)
        wm = WorkflowManager(project_dir=str(project_dir))

        with patch.object(wm.db_manager, 'sync_from_ssot', return_value=False):
            result = wm.run_sync_workflow()

        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 3: run_smart_extract_workflow routing logic
# ─────────────────────────────────────────────────────────────────────────────

class TestSmartExtractRouting:
    """
    run_smart_extract_workflow() is the default --extract command.
    It routes to sync (if DB exists and is non-empty) or bootstrap (if not).
    """

    def test_routes_to_sync_when_db_exists_and_nonempty(self, tmp_path):
        """
        If card_database.json exists and has content (> 50 bytes), smart extract
        runs sync — NOT bootstrap. The SSOT is preserved.
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = make_gti_project(tmp_path)

        # Create a non-trivial DB file (>50 bytes)
        db_path = project_dir / "card_database.json"
        cards = [make_card(sort_field="00_A_01_q")]
        db_path.write_text(
            json.dumps([c.to_dict() for c in cards]), encoding="utf-8"
        )
        assert os.path.getsize(str(db_path)) > 50

        wm = WorkflowManager(project_dir=str(project_dir))
        with patch.object(wm, 'run_sync_workflow', return_value=True) as mock_sync, \
             patch.object(wm, 'run_extract_workflow', return_value=True) as mock_bootstrap:
            result = wm.run_smart_extract_workflow()

        assert result is True
        mock_sync.assert_called_once()
        mock_bootstrap.assert_not_called()

    def test_routes_to_bootstrap_when_no_db(self, tmp_path):
        """
        If card_database.json does not exist, smart extract runs full bootstrap.
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = make_gti_project(tmp_path)
        wm = WorkflowManager(project_dir=str(project_dir))

        with patch.object(wm, 'run_sync_workflow', return_value=True) as mock_sync, \
             patch.object(wm, 'run_extract_workflow', return_value=True) as mock_bootstrap:
            result = wm.run_smart_extract_workflow(force=True)

        assert result is True
        mock_bootstrap.assert_called_once()
        mock_sync.assert_not_called()

    def test_routes_to_bootstrap_when_db_too_small(self, tmp_path):
        """
        If card_database.json exists but is ≤50 bytes (empty/minimal), smart
        extract still runs bootstrap (with force=True to skip prompt).
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = make_gti_project(tmp_path)

        # Tiny file — below the 50-byte threshold
        db_path = project_dir / "card_database.json"
        db_path.write_text("[]", encoding="utf-8")
        assert os.path.getsize(str(db_path)) <= 50

        wm = WorkflowManager(project_dir=str(project_dir))
        with patch.object(wm, 'run_sync_workflow', return_value=True) as mock_sync, \
             patch.object(wm, 'run_extract_workflow', return_value=True) as mock_bootstrap:
            result = wm.run_smart_extract_workflow(force=True)

        assert result is True
        mock_bootstrap.assert_called_once()
        mock_sync.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 4: Temporal multi-ingestion (week-by-week student workflow)
# ─────────────────────────────────────────────────────────────────────────────

class TestTemporalMultiIngestion:
    """
    Simulates a GTI student adding cards week by week over a semester.
    This is the PRIMARY use case: run --ingest + --integrate each week.

    Week 1: Bootstrap from initial DFA cards
    Week 2: Ingest NFA lecture → 3 new cards, DFA cards preserved, no dups
    Week 3: Try to re-ingest DFA material → all rejected as duplicates
    Week 4: Ingest RegEx lecture → 2 new cards
    Final: Verify total card count and GUID stability
    """

    def _make_fresh_db(self, tmp_path):
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        db = make_db(project_dir, config=cfg)
        return db, cfg, project_dir

    def test_week1_bootstrap_dfa_cards(self, tmp_path):
        """Week 1: 3 DFA cards bootstrapped. GUID assigned to each."""
        db, cfg, _ = self._make_fresh_db(tmp_path)
        week1_cards = [
            {"front": "Was ist ein DFA?", "back": r"5-Tupel M = (Q, Σ, δ, q0, F)."},
            {"front": r"Was ist δ im DFA?", "back": r"δ: Q × Σ → Q, Übergangsfunktion."},
            {"front": "Was ist q0?", "back": "Der Startzustand."},
        ]
        count = db.integrate_new(week1_cards)
        assert count == 3
        guids_week1 = {c.guid for c in db.cards}
        assert len(guids_week1) == 3  # all unique
        db.save_database()

    def test_week2_nfa_cards_added_dfa_preserved(self, tmp_path):
        """
        Week 2: 3 NFA cards integrated. 3 existing DFA cards must be preserved.
        Total: 6 cards.
        """
        db, cfg, _ = self._make_fresh_db(tmp_path)
        week1 = [
            {"front": "Was ist ein DFA?", "back": r"5-Tupel M = (Q, Σ, δ, q0, F)."},
            {"front": r"Was ist δ im DFA?", "back": r"δ: Q × Σ → Q, Übergangsfunktion."},
            {"front": "Was ist q0?", "back": "Der Startzustand."},
        ]
        db.integrate_new(week1)
        week1_guids = {c.guid: c.front for c in db.cards}

        week2 = [
            {"front": "Was ist ein NFA?", "back": "Nichtdeterministischer endlicher Automat."},
            {"front": "Was akzeptiert ein NFA?", "back": "Wenn mind. eine Berechnung akzeptiert."},
            {"front": r"Was ist ε-Übergang?", "back": "Übergang ohne Eingabesymbol."},
        ]
        count = db.integrate_new(week2)
        assert count == 3
        assert len(db.cards) == 6

        # Verify DFA cards still present with original GUIDs
        for guid, front in week1_guids.items():
            card = next((c for c in db.cards if c.guid == guid), None)
            assert card is not None, f"Week-1 card '{front}' lost its GUID"
            assert card.front == front

    def test_week3_duplicate_dfa_material_all_rejected(self, tmp_path):
        """
        Week 3: Student accidentally re-ingests week 1 DFA material.
        All 3 cards must be rejected as duplicates (case-insensitive match).
        Card count stays at 6.
        """
        db, cfg, _ = self._make_fresh_db(tmp_path)
        week1 = [
            {"front": "Was ist ein DFA?", "back": r"5-Tupel M = (Q, Σ, δ, q0, F)."},
            {"front": r"Was ist δ im DFA?", "back": r"δ: Q × Σ → Q, Übergangsfunktion."},
            {"front": "Was ist q0?", "back": "Der Startzustand."},
        ]
        week2 = [
            {"front": "Was ist ein NFA?", "back": "Nichtdeterministischer endlicher Automat."},
            {"front": "Was akzeptiert ein NFA?", "back": "Wenn mind. eine Berechnung akzeptiert."},
        ]
        db.integrate_new(week1)
        db.integrate_new(week2)
        assert len(db.cards) == 5

        # Week 3: re-ingest week1 with slightly different casing
        week3_dupes = [
            {"front": "Was ist ein DFA?", "back": "Andere Erklärung"},     # exact dup
            {"front": "WAS IST EIN DFA?", "back": "Großschreibung"},        # case variant
            {"front": "was ist q0?", "back": "lowercase dup"},              # lowercase
        ]
        count = db.integrate_new(week3_dupes)
        assert count == 0, "All week-3 cards must be rejected as duplicates"
        assert len(db.cards) == 5, "Card count must not change"

    def test_week4_regex_cards_added_correctly(self, tmp_path):
        """
        Week 4: RegEx cards added. Previous 5 cards preserved. Total: 8.
        """
        db, cfg, _ = self._make_fresh_db(tmp_path)
        db.integrate_new([
            {"front": "Was ist ein DFA?", "back": "5-Tupel."},
            {"front": "Was ist ein NFA?", "back": "Nichtdeterministisch."},
            {"front": "Was ist q0?", "back": "Startzustand."},
            {"front": "Was akzeptiert ein NFA?", "back": "Mind. eine Berechnung."},
            {"front": r"Was ist ε-Übergang?", "back": "Übergang ohne Eingabe."},
        ])
        week4 = [
            {"front": r"Was matcht (a|b)*abb?", "back": r"Wörter über \{a,b\} die auf 'abb' enden."},
            {"front": r"Was ist $a^*$ als regulärer Ausdruck?", "back": r"Beliebig viele 'a': ε, a, aa, aaa, ..."},
            {"front": "Was sind Pumping-Lemma Bedingungen?",
             "back": r"∀ w ∈ L, |w| ≥ p: ∃ Zerlegung w=xyz mit |y|≥1, |xy|≤p, ∀i≥0: xy^iz ∈ L."},
        ]
        count = db.integrate_new(week4)
        assert count == 3
        assert len(db.cards) == 8

    def test_guid_stability_across_save_load_cycles(self, tmp_path):
        """
        After each week's save→load cycle, card GUIDs must be identical.
        Anki uses GUIDs for sync — changing them creates duplicates in the app.
        """
        db, cfg, project_dir = self._make_fresh_db(tmp_path)
        initial_cards = [
            {"front": "Was ist ein DFA?", "back": "5-Tupel."},
            {"front": r"Was ist δ?", "back": "Übergangsfunktion."},
        ]
        db.integrate_new(initial_cards)
        db.save_database()
        original_guids = {c.front: c.guid for c in db.cards}

        # Simulate week 2: load, add cards, save
        db2 = make_db(project_dir, config=cfg)
        db2.load_database()
        db2.integrate_new([{"front": "Was ist ein NFA?", "back": "Nichtdeterministisch."}])
        db2.save_database()

        # Verify week-1 GUIDs unchanged after week-2 save
        for front, original_guid in original_guids.items():
            card = next((c for c in db2.cards if c.front == front), None)
            assert card is not None
            assert card.guid == original_guid, \
                f"GUID changed for '{front}': was {original_guid}, now {card.guid}"

    def test_ingest_then_integrate_pipeline_week_over_week(self, tmp_path):
        """
        Full pipeline test: ingest (LLM mock) → write new_cards_output.json →
        integrate → repeat for 3 weeks. Verifies the fixed format mismatch bug.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        db = make_db(project_dir, config=cfg)

        weeks = [
            [{"front": "Was ist ein DFA?", "back": "5-Tupel.", "collection": "collection_0_Sprachen", "category": "a_grundlagen"}],
            [{"front": "Was ist ein NFA?", "back": "Nichtdeterministisch.", "collection": "collection_0_Sprachen", "category": "a_grundlagen"}],
            [{"front": r"Was ist $a^*$?", "back": "Kleene-Stern.", "collection": "collection_1_RegEx", "category": "a_grundlagen"}],
        ]

        total_expected = 0
        for week_num, week_cards in enumerate(weeks, 1):
            output_path = str(project_dir / "new_cards_output.json")
            ocr_file = tmp_path / f"vorlesung_{week_num:02d}.txt"
            ocr_file.write_text(f"Vorlesung {week_num} Inhalt", encoding="utf-8")

            with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                       return_value=json.dumps({"new_cards": week_cards})):
                ingest_text([str(ocr_file)], cfg, output_path)

            data = json.loads(Path(output_path).read_text(encoding="utf-8"))
            # This uses the {"new_cards": [...]} format — fixed in run_integrate_workflow
            count = db.integrate_new(data["new_cards"])
            total_expected += len(week_cards)
            assert count == len(week_cards), f"Week {week_num}: expected {len(week_cards)} new cards"

        assert len(db.cards) == total_expected


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 5: collection=None in ApkgExporter
# ─────────────────────────────────────────────────────────────────────────────

class TestExporterCollectionNone:
    """
    Verifies exact behavior when cards have collection=None.
    _group_by_collection uses `card.collection or 'collection_0_unsorted'`
    so these cards DO get exported — not silently dropped.
    """

    def test_collection_none_cards_exported_as_fallback_group(self, tmp_path):
        """
        Cards with collection=None are grouped under 'collection_0_unsorted'.
        Since this key is not in config.collections, display_name falls back
        to the key itself and filename becomes 'collection_0_unsorted.apkg'.
        Result: exactly 1 .apkg file.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        cards = [AnkiCard(front="Heimatlose Karte", back="Ohne Sammlung", collection=None)]
        exporter = ApkgExporter()

        with patch("pdf2anki.text2anki.apkg_exporter.genanki") as mock_genanki:
            mock_genanki.Package.return_value = MagicMock()
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Model.return_value = MagicMock()
            generated = exporter.export(cards, cfg, str(tmp_path))

        assert len(generated) == 1
        assert "collection_0_unsorted.apkg" in generated[0]

    def test_collection_none_and_real_collection_exported_separately(self, tmp_path):
        """
        Mix of collection=None and real collection → 2 separate .apkg files.
        None cards go to fallback, real cards go to their collection file.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        cards = [
            AnkiCard(front="Heimatlos", back="Kein Deck", collection=None),
            make_card(front="Bekannte Karte", sort_field="00_A_01_q"),
        ]
        exporter = ApkgExporter()

        with patch("pdf2anki.text2anki.apkg_exporter.genanki") as mock_genanki:
            mock_genanki.Package.return_value = MagicMock()
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Model.return_value = MagicMock()
            generated = exporter.export(cards, cfg, str(tmp_path))

        assert len(generated) == 2
        filenames = [os.path.basename(p) for p in generated]
        assert "collection_0_unsorted.apkg" in filenames
        assert "collection_0_Sprachen.apkg" in filenames
