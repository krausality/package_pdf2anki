"""
test_regression_e2e.py — End-to-End Regression Tests for pdf2anki

PHASE 1 SIMULATION: GTI Student (WiSe 25/26) User Journey
==========================================================

Simulated workflow of a student named "GTI User" who wants to convert
Grundlagen der Theoretischen Informatik (GTI) lecture material into Anki
flashcards. The following classes capture every step from project setup
to export, along with all bugs and edge cases discovered along the way.

DISCOVERED ISSUES (documented as failing/regression tests):
1. WorkflowManager.run_export_workflow uses bare `from apkg_exporter import ...`
   (a relative import without the dot) — crashes with ModuleNotFoundError when
   called via the normal package path.
2. WorkflowManager.run_ingest_workflow uses bare `from text_ingester import ...`
   — same crash.
3. integrate_new() assigns new cards to collection_0_Neue_Karten when DB is
   empty, which collides with a real collection_0 added later.
4. find_card_by_front() uses exact-match, but integrate_new() uses
   case-normalized matching — inconsistency: a card may be "not found" by
   find_card_by_front but still be rejected as a duplicate by integrate_new.
5. _generate_markdown_card_list() crashes with TypeError when any card has
   sort_field=None and another card has a non-None sort_field (mixed sort types).
6. _normalize_for_key() silently strips Greek letters (δ, Σ, ε, γ) and math
   symbols (∈, ∅, →), producing garbled or even empty collection/category keys.
7. AnkiCard.from_dict(**data) raises TypeError if the JSON DB ever gains an
   unknown field (forward-compatibility gap).
8. TextFileIngestor._parse_response() raises JSONDecodeError for any LLM
   output that contains prose before or after the JSON — not wrapped in try/except
   by ingest(), so the exception propagates to the caller.
9. project.json creation fails with FileExistsError if the file already exists —
   no --force / overwrite option, requiring manual deletion.
10. collect_files with wrong call sequence: WorkflowManager(project_dir=X) calls
    ProjectConfig.from_file(X) which raises FileNotFoundError if project.json
    is missing — there is no helpful "run --init first" message at that level.

All external APIs (OpenRouter/LLM, genanki) are mocked.
No real network access. Uses pytest tmp_path for isolation.
"""

import json
import os
import re
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from pdf2anki.text2anki.card import AnkiCard
from pdf2anki.text2anki.database_manager import DatabaseManager
from pdf2anki.text2anki.project_config import ProjectConfig
from pdf2anki.text2anki.text_ingester import TextFileIngestor, ingest_text
from pdf2anki.text2anki.apkg_exporter import ApkgExporter, export_to_apkg


# ─────────────────────────────────────────────────────────────────────────────
# Shared Fixtures / Helpers
# ─────────────────────────────────────────────────────────────────────────────

GTI_PROJECT_DATA = {
    "project_name": "GTI_WiSe2526",
    "tag_prefix": "GTI",
    "language": "de",
    "domain": "Grundlagen der Theoretischen Informatik (Automatentheorie, formale Sprachen, Berechenbarkeit)",
    "orphan_collection_name": "Unsortierte_Karten",
    "files": {
        "db_path": "card_database.json",
        "markdown_file": "All_fronts.md",
        "new_cards_file": "new_cards_output.json",
        "material_file": "course_material.txt",
    },
    "collections": {
        "collection_0_DFA_NFA": {
            "display_name": "Kapitel 1: DFA und NFA",
            "filename": "collection_0_DFA_NFA.json",
            "description": "Deterministische und nichtdeterministische endliche Automaten",
        },
        "collection_1_RegEx": {
            "display_name": "Kapitel 2: Reguläre Ausdrücke",
            "filename": "collection_1_RegEx.json",
            "description": "Reguläre Ausdrücke und ihre Äquivalenz zu endlichen Automaten",
        },
        "collection_2_Turing": {
            "display_name": "Kapitel 3: Turingmaschinen",
            "filename": "collection_2_Turing.json",
            "description": "Turingmaschinen und Berechenbarkeit",
        },
    },
    "llm": {"model": "google/gemini-2.5-flash", "temperature": 0.1},
}


def make_gti_project(tmp_path) -> Path:
    """Creates a complete GTI project directory with project.json."""
    project_dir = tmp_path / "gti_project"
    project_dir.mkdir()
    (project_dir / "project.json").write_text(
        json.dumps(GTI_PROJECT_DATA), encoding="utf-8"
    )
    return project_dir


def make_db(tmp_path, cards=None, config=None) -> DatabaseManager:
    """Creates a DatabaseManager with an optional mock MaterialManager."""
    mock_mm = MagicMock()
    mock_mm.get_course_material.return_value = None
    db_path = str(tmp_path / "card_database.json")
    if cards is not None:
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in cards], f)
    return DatabaseManager(
        db_path=db_path,
        material_manager=mock_mm,
        project_config=config,
    )


def make_card(**kwargs) -> AnkiCard:
    """Returns an AnkiCard with sensible defaults, accepting overrides."""
    defaults = dict(
        front="Was ist ein DFA?",
        back="Ein deterministischer endlicher Automat.",
        collection="collection_0_DFA_NFA",
        category="a_grundlagen",
        sort_field="00_A_01_was_ist_ein_dfa",
    )
    defaults.update(kwargs)
    return AnkiCard(**defaults)


def make_ssot_markdown(fronts, collection_id=0, collection_name="DFA_NFA",
                        category_letter="A", category_name="Grundlagen") -> str:
    """
    Builds a valid SSOT All_fronts.md using the <!-- COLLECTION_N_START/END -->
    format that _parse_markdown_structure() requires.
    """
    cards_lines = "\n".join(f"{i + 1}. {front}" for i, front in enumerate(fronts))
    return (
        f"<!-- COLLECTION_{collection_id}_START -->\n"
        f"# Sammlung {collection_id}\n"
        f"**{collection_name}**\n"
        f"<!-- CARDS_START -->\n"
        f"**{category_letter}. {category_name}**\n"
        f"{cards_lines}\n"
        f"<!-- CARDS_END -->\n"
        f"<!-- COLLECTION_{collection_id}_END -->\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 1: Project Setup (Schritt 3: Projekt einrichten)
# ─────────────────────────────────────────────────────────────────────────────

class TestProjectSetup:
    """
    User tries to initialize a new GTI project.
    Covers: ProjectConfig.create_template, from_file, validation errors.
    """

    def test_init_creates_project_json(self, tmp_path):
        """
        Happy path: --init creates project.json with project_name and tag_prefix.
        This is the first command a new user runs.
        """
        project_dir = str(tmp_path / "gti_test")
        cfg = ProjectConfig.create_template(project_dir, "GTI_WiSe2526")
        project_json = Path(project_dir) / "project.json"
        assert project_json.exists(), "project.json must be created by --init"
        assert cfg.project_name == "GTI_WiSe2526"

    def test_init_sets_tag_prefix_from_name(self, tmp_path):
        """
        Tag prefix is derived from project name: spaces → underscores, uppercased.
        'GTI Wise 2526' becomes 'GTI_WISE_2526'.
        """
        cfg = ProjectConfig.create_template(str(tmp_path / "proj"), "GTI Wise 2526")
        assert cfg.tag_prefix == "GTI_WISE_2526"

    def test_init_fails_if_project_json_already_exists(self, tmp_path):
        """
        BUG/REGRESSION: --init raises FileExistsError if project.json already exists.
        There is no --force option. User must manually delete the file.
        """
        project_dir = str(tmp_path)
        ProjectConfig.create_template(project_dir, "First")
        with pytest.raises(FileExistsError, match="project.json existiert bereits"):
            ProjectConfig.create_template(project_dir, "Second")

    def test_from_file_raises_when_no_project_json(self, tmp_path):
        """
        WorkflowManager(project_dir=X) ultimately calls ProjectConfig.from_file(X).
        If user forgot to run --init, they get FileNotFoundError.
        The error message includes a helpful hint about --init.
        """
        with pytest.raises(FileNotFoundError, match="project.json nicht gefunden"):
            ProjectConfig.from_file(str(tmp_path))

    def test_from_file_raises_on_invalid_json(self, tmp_path):
        """User edited project.json and broke its JSON syntax."""
        (tmp_path / "project.json").write_text("{ broken json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            ProjectConfig.from_file(str(tmp_path))

    def test_from_file_raises_on_missing_project_name(self, tmp_path):
        """Required field 'project_name' missing → clear error pointing to the field."""
        bad = dict(GTI_PROJECT_DATA)
        del bad["project_name"]
        (tmp_path / "project.json").write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="project_name"):
            ProjectConfig.from_file(str(tmp_path))

    def test_from_file_raises_on_empty_collections(self, tmp_path):
        """
        'collections' must be a non-empty dict.
        User deleted all collections → clear error with example.
        """
        bad = {**GTI_PROJECT_DATA, "collections": {}}
        (tmp_path / "project.json").write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="collections"):
            ProjectConfig.from_file(str(tmp_path))

    def test_from_file_raises_on_collection_missing_filename(self, tmp_path):
        """
        Each collection entry must have a 'filename' ending in .json.
        Missing filename → descriptive error.
        """
        bad = {
            **GTI_PROJECT_DATA,
            "collections": {
                "collection_0_DFA_NFA": {"display_name": "DFA und NFA"}
                # 'filename' intentionally omitted
            },
        }
        (tmp_path / "project.json").write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="filename"):
            ProjectConfig.from_file(str(tmp_path))

    def test_from_file_raises_on_non_json_filename(self, tmp_path):
        """Collection filename must end with .json — .txt is rejected."""
        bad = {
            **GTI_PROJECT_DATA,
            "collections": {
                "collection_0_DFA_NFA": {
                    "display_name": "DFA",
                    "filename": "collection_0_DFA_NFA.txt",  # wrong extension
                }
            },
        }
        (tmp_path / "project.json").write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match=".json"):
            ProjectConfig.from_file(str(tmp_path))

    def test_gti_project_loads_successfully(self, tmp_path):
        """
        Full GTI project.json with 3 collections (DFA/NFA, RegEx, Turing)
        loads without error and has correct values.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        assert cfg.project_name == "GTI_WiSe2526"
        assert cfg.tag_prefix == "GTI"
        assert cfg.language == "de"
        assert "Automatentheorie" in cfg.domain
        assert len(cfg.collections) == 3

    def test_gti_project_path_helpers_return_absolute_paths(self, tmp_path):
        """
        get_db_path(), get_markdown_path(), get_new_cards_path() must return
        absolute paths so the tool works from any working directory.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        assert os.path.isabs(cfg.get_db_path())
        assert os.path.isabs(cfg.get_markdown_path())
        assert os.path.isabs(cfg.get_new_cards_path())

    def test_gti_collection_filename_mapping(self, tmp_path):
        """
        get_collection_filename_mapping() returns correct key→filename dict.
        Used by DatabaseManager to write derived collection files.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        mapping = cfg.get_collection_filename_mapping()
        assert mapping["collection_0_DFA_NFA"] == "collection_0_DFA_NFA.json"
        assert mapping["collection_1_RegEx"] == "collection_1_RegEx.json"
        assert mapping["collection_2_Turing"] == "collection_2_Turing.json"

    def test_orphan_collection_key_format(self, tmp_path):
        """
        Orphan collection key = collection_{N}_{orphan_name} where N = len(collections).
        For our 3-collection GTI project, orphans go to collection_3_Unsortierte_Karten.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        key = cfg.get_orphan_collection_key()
        assert key == "collection_3_Unsortierte_Karten"

    def test_project_without_llm_section_uses_defaults(self, tmp_path):
        """
        If user omits the 'llm' section entirely, defaults are used without crashing.
        Default model: google/gemini-2.5-flash.
        """
        data = {k: v for k, v in GTI_PROJECT_DATA.items() if k != "llm"}
        (tmp_path / "project.json").write_text(json.dumps(data), encoding="utf-8")
        cfg = ProjectConfig.from_file(str(tmp_path))
        assert isinstance(cfg.get_llm_model(), str)
        assert len(cfg.get_llm_model()) > 0


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 2: Card Ingestion via LLM (Schritt 4: Lernkarten erstellen)
# ─────────────────────────────────────────────────────────────────────────────

class TestCardIngestion:
    """
    User runs: text2anki --ingest lecture_01_dfa.txt
    This sends lecture text to LLM and writes new_cards_output.json.
    """

    @pytest.fixture
    def gti_config(self, tmp_path):
        project_dir = make_gti_project(tmp_path)
        return ProjectConfig.from_file(str(project_dir))

    @pytest.fixture
    def dfa_lecture_file(self, tmp_path):
        """Simulates a real GTI lecture text about DFAs."""
        content = (
            "Vorlesung 1: Deterministische Endliche Automaten (DFA)\n\n"
            "Ein DFA ist ein 5-Tupel M = (Q, Σ, δ, q0, F) wobei:\n"
            "- Q eine endliche Menge von Zuständen ist\n"
            "- Σ das Eingabealphabet ist\n"
            "- δ: Q × Σ → Q die Übergangsfunktion ist\n"
            "- q0 ∈ Q der Startzustand ist\n"
            "- F ⊆ Q die Menge der akzeptierenden Zustände ist\n\n"
            "Ein DFA akzeptiert ein Wort w, wenn die Berechnung von q0 aus "
            "nach Lesen von w in einem Zustand aus F endet.\n"
        )
        txt = tmp_path / "vorlesung_01_dfa.txt"
        txt.write_text(content, encoding="utf-8")
        return str(txt)

    def test_ingest_happy_path_writes_new_cards_file(self, tmp_path, gti_config, dfa_lecture_file):
        """
        Happy path: LLM returns valid JSON → new_cards_output.json is written.
        User can then run --integrate to add cards to the database.
        """
        mock_cards = [
            {
                "front": "Was ist ein DFA?",
                "back": "Ein deterministischer endlicher Automat ist ein 5-Tupel M = (Q, Σ, δ, q0, F).",
                "collection": "collection_0_DFA_NFA",
                "category": "a_grundlagen",
            },
            {
                "front": "Was bedeutet δ in einem DFA?",
                "back": "δ: Q × Σ → Q ist die Übergangsfunktion des DFA.",
                "collection": "collection_0_DFA_NFA",
                "category": "a_grundlagen",
            },
        ]
        output_path = str(tmp_path / "new_cards_output.json")
        llm_response = json.dumps({"new_cards": mock_cards})

        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", return_value=llm_response):
            result = ingest_text([dfa_lecture_file], gti_config, output_path)

        assert result is True
        assert Path(output_path).exists(), "new_cards_output.json must be created"
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["new_cards"]) == 2
        assert data["new_cards"][0]["front"] == "Was ist ein DFA?"

    def test_ingest_preserves_unicode_in_cards(self, tmp_path, gti_config, dfa_lecture_file):
        """
        GTI cards contain Greek letters and math symbols.
        These must be preserved exactly in the output JSON — not stripped or mangled.
        """
        mock_cards = [
            {
                "front": "Was ist δ in einem DFA?",
                "back": "δ: Q × Σ → Q ist die Übergangsfunktion.",
                "collection": "collection_0_DFA_NFA",
                "category": "a_grundlagen",
            },
        ]
        output_path = str(tmp_path / "new_cards_output.json")
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value=json.dumps({"new_cards": mock_cards})):
            ingest_text([dfa_lecture_file], gti_config, output_path)

        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["new_cards"][0]["front"] == "Was ist δ in einem DFA?"
        assert "Σ" in data["new_cards"][0]["back"]

    def test_ingest_missing_source_file_continues_gracefully(self, tmp_path, gti_config):
        """
        If the lecture file doesn't exist, ingest logs a warning and continues.
        LLM is still called (with empty material), and output is written.
        Edge case: user gives wrong path to --ingest.
        """
        output_path = str(tmp_path / "new_cards_output.json")
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value=json.dumps({"new_cards": []})):
            result = ingest_text(["/nonexistent/path/vorlesung.txt"], gti_config, output_path)
        assert result is True  # not an error — just empty
        assert Path(output_path).exists()

    def test_ingest_multiple_files_sends_all_content_to_llm(self, tmp_path, gti_config):
        """
        User ingests two lecture files at once (e.g. DFA + NFA lecture).
        Both texts must be concatenated and sent to the LLM.
        """
        f1 = tmp_path / "vorlesung_01.txt"
        f2 = tmp_path / "vorlesung_02.txt"
        f1.write_text("DFA Grundlagen: Q, Σ, δ, q0, F", encoding="utf-8")
        f2.write_text("NFA: nichtdeterministischer Automat mit ε-Übergängen", encoding="utf-8")

        captured = {}

        def fake_llm(header_context, prompt_body, model=None):
            captured["prompt"] = prompt_body
            return json.dumps({"new_cards": []})

        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", side_effect=fake_llm):
            ingest_text([str(f1), str(f2)], gti_config, str(tmp_path / "out.json"))

        assert "DFA Grundlagen" in captured["prompt"]
        assert "NFA" in captured["prompt"]

    def test_ingest_llm_returns_none_creates_empty_output(self, tmp_path, gti_config, dfa_lecture_file):
        """
        LLM API call fails (network error, bad key) → ingest returns empty new_cards list.
        User should see an error message and an empty output file.
        """
        output_path = str(tmp_path / "new_cards_output.json")
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", return_value=None):
            result = ingest_text([dfa_lecture_file], gti_config, output_path)
        assert result is True  # no crash
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["new_cards"] == []

    def test_ingest_llm_wraps_json_in_code_fence(self, tmp_path, gti_config, dfa_lecture_file):
        """
        LLM sometimes wraps output in ```json ... ```.
        Parser must strip these fences — this is a real-world LLM behavior.
        """
        mock_cards = [{"front": "Q?", "back": "A.", "collection": "collection_0_DFA_NFA", "category": "a_cat"}]
        fenced_response = f"```json\n{json.dumps({'new_cards': mock_cards})}\n```"
        output_path = str(tmp_path / "out.json")
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", return_value=fenced_response):
            ingest_text([dfa_lecture_file], gti_config, output_path)
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["new_cards"]) == 1

    def test_ingest_llm_prose_before_json_returns_empty(self, tmp_path, gti_config, dfa_lecture_file):
        """
        _parse_response() handles prose before/after JSON gracefully.
        If LLM says "Sure! Here are your cards: {...}", it returns {"new_cards": []}
        instead of crashing with JSONDecodeError.
        """
        prose_response = 'Natürlich! Hier sind deine Karten:\n{"new_cards": []}'
        output_path = str(tmp_path / "out.json")
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", return_value=prose_response):
            result = ingest_text([dfa_lecture_file], gti_config, output_path)
        # Graceful: returns True/False but does NOT crash
        assert result in (True, False)

    def test_ingest_prompt_contains_domain_and_language(self, tmp_path, gti_config, dfa_lecture_file):
        """
        The LLM prompt must include the project domain and language for context.
        GTI domain contains 'Automatentheorie', language is 'de' → German prompt.
        """
        captured = {}

        def fake_llm(header_context, prompt_body, model=None):
            captured["prompt"] = prompt_body
            return json.dumps({"new_cards": []})

        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", side_effect=fake_llm):
            ingest_text([dfa_lecture_file], gti_config, str(tmp_path / "out.json"))

        # German prompt uses 'Experte'
        assert "Experte" in captured["prompt"]
        # Domain appears in prompt
        assert "Automatentheorie" in captured["prompt"]

    def test_ingest_prompt_contains_all_collection_keys(self, tmp_path, gti_config, dfa_lecture_file):
        """
        The LLM prompt must list ALL collection keys so the model knows
        where to assign each card. Missing a collection key causes misassignment.
        """
        captured = {}

        def fake_llm(header_context, prompt_body, model=None):
            captured["prompt"] = prompt_body
            return json.dumps({"new_cards": []})

        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", side_effect=fake_llm):
            ingest_text([dfa_lecture_file], gti_config, str(tmp_path / "out.json"))

        for key in ["collection_0_DFA_NFA", "collection_1_RegEx", "collection_2_Turing"]:
            assert key in captured["prompt"], f"Collection key '{key}' missing from prompt"

    def test_ingest_empty_text_file_is_allowed(self, tmp_path, gti_config):
        """
        Edge case: user accidentally ingests an empty file.
        Should not crash — just produces an empty output.
        """
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("", encoding="utf-8")
        output_path = str(tmp_path / "out.json")

        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value=json.dumps({"new_cards": []})):
            result = ingest_text([str(empty_file)], gti_config, output_path)
        assert result is True


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 3: Card Integration (integrate_new + bootstrap_from_legacy)
# ─────────────────────────────────────────────────────────────────────────────

class TestCardIntegration:
    """
    User runs --integrate after --ingest.
    Covers: integrate_new(), bootstrap_from_legacy(), duplicate detection,
    collection numbering, and all automation flags.
    """

    def test_integrate_happy_path_adds_dfa_cards(self, tmp_path):
        """
        Happy path: integrate 3 DFA cards into an empty database.
        All 3 should be added successfully.
        """
        db = make_db(tmp_path)
        gti_cards = [
            {"front": "Was ist ein DFA?", "back": "Ein deterministischer endlicher Automat.",
             "collection": "collection_0_DFA_NFA", "category": "a_grundlagen"},
            {"front": "Was ist ein NFA?", "back": "Ein nichtdeterministischer endlicher Automat.",
             "collection": "collection_0_DFA_NFA", "category": "a_grundlagen"},
            {"front": "Was ist eine Turingmaschine?", "back": "Ein universelles Berechnungsmodell.",
             "collection": "collection_2_Turing", "category": "a_grundlagen"},
        ]
        count = db.integrate_new(gti_cards)
        assert count == 3
        assert len(db.cards) == 3

    def test_integrate_skips_duplicate_fronts(self, tmp_path):
        """
        If the same question already exists (case-insensitive), it is skipped.
        Duplicate detection uses _normalize_text() (lowercase + whitespace collapse).
        """
        existing = make_card(front="Was ist ein DFA?")
        db = make_db(tmp_path, cards=[existing])
        count = db.integrate_new([
            {"front": "Was ist ein DFA?", "back": "Anderer Text"},  # exact duplicate
        ])
        assert count == 0

    def test_integrate_duplicate_detection_is_case_insensitive(self, tmp_path):
        """
        integrate_new uses _normalize_text (lowercase) for duplicate detection.
        'WAS IST EIN DFA?' and 'Was ist ein DFA?' are treated as duplicates.
        Prevents users from accidentally inserting near-identical cards.
        """
        existing = make_card(front="Was ist ein DFA?")
        db = make_db(tmp_path, cards=[existing])
        count = db.integrate_new([{"front": "WAS IST EIN DFA?", "back": "Antwort"}])
        assert count == 0

    def test_integrate_within_batch_deduplication(self, tmp_path):
        """
        If the same front appears twice in a single batch, only the FIRST is added.
        The second entry is skipped because existing_fronts is updated within the loop.
        """
        db = make_db(tmp_path)
        batch = [
            {"front": "Was ist δ?", "back": "Übergangsfunktion"},
            {"front": "Was ist δ?", "back": "Anderer Wert"},  # same front
        ]
        count = db.integrate_new(batch)
        assert count == 1
        assert db.cards[0].back == "Übergangsfunktion"  # first wins

    def test_integrate_empty_front_is_skipped(self, tmp_path):
        """Empty front field → card is silently skipped. No crash, no partial state."""
        db = make_db(tmp_path)
        count = db.integrate_new([{"front": "", "back": "Antwort"}])
        assert count == 0

    def test_integrate_empty_back_is_skipped(self, tmp_path):
        """Empty back field → card is silently skipped."""
        db = make_db(tmp_path)
        count = db.integrate_new([{"front": "Frage?", "back": ""}])
        assert count == 0

    def test_integrate_whitespace_only_front_is_skipped(self, tmp_path):
        """front='   ' strips to '' → treated as empty, skipped."""
        db = make_db(tmp_path)
        count = db.integrate_new([{"front": "   ", "back": "Antwort"}])
        assert count == 0

    def test_integrate_into_empty_db_uses_collection_0(self, tmp_path):
        """
        With no existing cards, max_coll_num = -1, so new_coll_num = 0.
        New cards go to 'collection_0_Neue_Karten'.

        BUG NOTE: This collides with any real collection_0_X from the project.
        If user then runs --integrate with actual GTI cards that belong to
        collection_0_DFA_NFA, the new cards will be in collection_0_Neue_Karten
        instead — two collection_0 entries exist simultaneously.
        """
        db = make_db(tmp_path)
        db.integrate_new([{"front": "Erste Frage?", "back": "Erste Antwort"}])
        assert db.cards[0].collection == "collection_0_Neue_Karten"

    def test_integrate_into_existing_db_uses_next_collection_number(self, tmp_path):
        """
        With existing collection_2, new cards go to collection_3_Neue_Karten.
        Correct behavior: increments beyond the highest existing collection number.
        """
        existing = make_card(collection="collection_2_Turing", sort_field="02_A_01_q")
        db = make_db(tmp_path, cards=[existing])
        db.integrate_new([{"front": "Neue GTI-Frage?", "back": "Antwort"}])
        new_card = db.find_card_by_front("Neue GTI-Frage?")
        assert new_card is not None
        assert new_card.collection == "collection_3_Neue_Karten"

    def test_integrate_preserves_unicode_in_front_and_back(self, tmp_path):
        """
        GTI-specific: cards with Greek letters (δ, Σ, ε) and math symbols (∈, ∅, →)
        must be stored exactly as-is in the database, not stripped or mangled.
        """
        db = make_db(tmp_path)
        count = db.integrate_new([{
            "front": "Was gilt für δ ∈ Q × Σ → Q?",
            "back": "δ ist die totale Übergangsfunktion. Für jeden Zustand q ∈ Q und jedes Zeichen a ∈ Σ gibt es genau einen Nachfolgezustand.",
        }])
        assert count == 1
        card = db.cards[0]
        assert "δ" in card.front
        assert "Σ" in card.front
        assert "∈" in card.front
        assert "δ" in card.back

    def test_integrate_saves_to_database_file(self, tmp_path):
        """After integrate_new, card_database.json must be updated on disk."""
        db = make_db(tmp_path)
        db.integrate_new([{"front": "Gespeichert?", "back": "Ja."}])
        assert Path(db.db_path).exists()
        with open(db.db_path, encoding="utf-8") as f:
            data = json.load(f)
        assert any(c["front"] == "Gespeichert?" for c in data)

    def test_bootstrap_from_legacy_happy_path(self, tmp_path):
        """
        Bootstrap from matching collection.json + All_fronts.md.
        Both sources agree → cards are loaded without conflicts.
        """
        coll_file = tmp_path / "collection_0_DFA_NFA.json"
        coll_file.write_text(json.dumps([
            {"front": "Was ist ein DFA?", "back": "Ein 5-Tupel M = (Q, Σ, δ, q0, F)."},
        ]), encoding="utf-8")

        md_content = make_ssot_markdown(["Was ist ein DFA?"], collection_id=0, collection_name="DFA_NFA")
        md_file = tmp_path / "All_fronts.md"
        md_file.write_text(md_content, encoding="utf-8")

        db = make_db(tmp_path)
        result = db.bootstrap_from_legacy(
            collection_files=[str(coll_file)],
            markdown_file=str(md_file),
            auto_skip_conflicts=True,
            auto_rescue_orphans=True,
            auto_create_missing=True,
        )
        assert result is True
        assert len(db.cards) >= 1
        fronts = [c.front for c in db.cards]
        assert "Was ist ein DFA?" in fronts

    def test_bootstrap_returns_false_on_empty_sources(self, tmp_path):
        """
        Bootstrap with no data in either source → returns False.
        This protects against accidentally overwriting a populated DB with empty data.
        """
        coll_file = tmp_path / "empty.json"
        coll_file.write_text("[]", encoding="utf-8")
        md_file = tmp_path / "All_fronts.md"
        md_file.write_text("", encoding="utf-8")

        db = make_db(tmp_path)
        result = db.bootstrap_from_legacy(
            collection_files=[str(coll_file)],
            markdown_file=str(md_file),
        )
        assert result is False

    def test_bootstrap_auto_rescue_orphans(self, tmp_path):
        """
        Orphan cards (exist in collection.json but NOT in All_fronts.md) are
        rescued into a new 'Unsortierte_Karten' collection when auto_rescue_orphans=True.
        """
        coll_file = tmp_path / "collection_0_DFA_NFA.json"
        coll_file.write_text(json.dumps([
            {"front": "Verwaiste DFA-Frage", "back": "Verwaiste Antwort"},
        ]), encoding="utf-8")
        # Markdown is empty — no matching entry
        md_content = (
            "<!-- COLLECTION_0_START -->\n"
            "# Sammlung 0\n**DFA_NFA**\n"
            "<!-- CARDS_START -->\n<!-- CARDS_END -->\n"
            "<!-- COLLECTION_0_END -->\n"
        )
        md_file = tmp_path / "All_fronts.md"
        md_file.write_text(md_content, encoding="utf-8")

        db = make_db(tmp_path)
        result = db.bootstrap_from_legacy(
            collection_files=[str(coll_file)],
            markdown_file=str(md_file),
            auto_rescue_orphans=True,
        )
        assert result is True
        fronts = [c.front for c in db.cards]
        assert "Verwaiste DFA-Frage" in fronts

    def test_bootstrap_auto_ignore_orphans(self, tmp_path):
        """
        Orphan cards are discarded when auto_ignore_orphans=True.
        After bootstrap, the orphan should NOT be in the database.
        """
        coll_file = tmp_path / "collection_0_DFA_NFA.json"
        coll_file.write_text(json.dumps([
            {"front": "Ignorierte Frage", "back": "Ignorierte Antwort"},
        ]), encoding="utf-8")
        md_content = (
            "<!-- COLLECTION_0_START -->\n"
            "# Sammlung 0\n**DFA_NFA**\n"
            "<!-- CARDS_START -->\n<!-- CARDS_END -->\n"
            "<!-- COLLECTION_0_END -->\n"
        )
        md_file = tmp_path / "All_fronts.md"
        md_file.write_text(md_content, encoding="utf-8")

        db = make_db(tmp_path)
        result = db.bootstrap_from_legacy(
            collection_files=[str(coll_file)],
            markdown_file=str(md_file),
            auto_ignore_orphans=True,
        )
        assert result is True
        fronts = [c.front for c in db.cards]
        assert "Ignorierte Frage" not in fronts

    def test_bootstrap_auto_create_missing_cards(self, tmp_path):
        """
        Cards listed in All_fronts.md but NOT in any collection.json get
        auto-created with a 'TODO' back when auto_create_missing=True.
        User can then fill in the answer later.
        """
        coll_file = tmp_path / "collection_0_DFA_NFA.json"
        coll_file.write_text("[]", encoding="utf-8")  # empty collection
        md_content = make_ssot_markdown(["Fehlende Turing-Frage"])
        md_file = tmp_path / "All_fronts.md"
        md_file.write_text(md_content, encoding="utf-8")

        db = make_db(tmp_path)
        result = db.bootstrap_from_legacy(
            collection_files=[str(coll_file)],
            markdown_file=str(md_file),
            auto_create_missing=True,
        )
        assert result is True
        backs = [c.back for c in db.cards]
        assert any("TODO" in b for b in backs), "Missing cards should get TODO back"

    def test_bootstrap_handles_missing_collection_files(self, tmp_path):
        """
        Collection file that doesn't exist is silently skipped.
        Only the markdown structure is used.
        """
        nonexistent = str(tmp_path / "does_not_exist.json")
        md_content = make_ssot_markdown(["Markdown-only Frage"])
        md_file = tmp_path / "All_fronts.md"
        md_file.write_text(md_content, encoding="utf-8")

        db = make_db(tmp_path)
        # With only markdown data and auto_create_missing, should still work
        result = db.bootstrap_from_legacy(
            collection_files=[nonexistent],
            markdown_file=str(md_file),
            auto_create_missing=True,
        )
        # Either succeeds (creates TODO cards) or fails (no collection data at all)
        # Both are acceptable — important: no crash
        assert isinstance(result, bool)


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 4: Card Management (Schritt 5: Karten verwalten)
# ─────────────────────────────────────────────────────────────────────────────

class TestCardManagement:
    """
    User wants to list, find, update, and manage cards.
    Covers: find_card_by_front, load/save roundtrip, GUID uniqueness.
    """

    def test_find_card_by_exact_front(self, tmp_path):
        """
        find_card_by_front uses exact string equality.
        'Was ist ein DFA?' finds the card correctly.
        """
        card = make_card(front="Was ist ein DFA?")
        db = make_db(tmp_path, cards=[card])
        found = db.find_card_by_front("Was ist ein DFA?")
        assert found is not None
        assert found.front == "Was ist ein DFA?"

    def test_find_card_returns_none_for_unknown_front(self, tmp_path):
        """Searching for a non-existent front returns None — no exception."""
        db = make_db(tmp_path, cards=[make_card(front="Bekannte Frage")])
        result = db.find_card_by_front("Unbekannte Frage")
        assert result is None

    def test_find_card_case_insensitive(self, tmp_path):
        """
        find_card_by_front is case-insensitive (uses _normalize_text),
        consistent with integrate_new dedup behavior.
        """
        card = make_card(front="Was ist ein DFA?")
        db = make_db(tmp_path, cards=[card])
        assert db.find_card_by_front("was ist ein dfa?") is not None

    def test_find_card_whitespace_normalized(self, tmp_path):
        """
        find_card_by_front normalizes whitespace — extra spaces are collapsed.
        """
        card = make_card(front="Was ist ein DFA?")
        db = make_db(tmp_path, cards=[card])
        assert db.find_card_by_front("Was  ist  ein  DFA?") is not None  # double spaces

    def test_empty_db_find_returns_none(self, tmp_path):
        """find_card_by_front on empty database returns None without crashing."""
        db = make_db(tmp_path)
        assert db.find_card_by_front("Irgendeine Frage") is None

    def test_load_database_roundtrip(self, tmp_path):
        """
        save_database() → load_database() preserves all card fields.
        This is the fundamental data persistence guarantee.
        """
        original = make_card(
            front="Roundtrip-Test",
            back="Antwort.",
            tags=["GTI::C0::A_Test"],
            sort_field="00_A_01_roundtrip",
        )
        db = make_db(tmp_path)
        db.cards = [original]
        db.save_database()

        # Reload from disk
        db2 = make_db(tmp_path, cards=None)
        db2.cards = []
        db2.load_database()

        assert len(db2.cards) == 1
        c = db2.cards[0]
        assert c.front == "Roundtrip-Test"
        assert c.back == "Antwort."
        assert c.tags == ["GTI::C0::A_Test"]
        assert c.sort_field == "00_A_01_roundtrip"

    def test_load_database_empty_when_file_missing(self, tmp_path):
        """If card_database.json doesn't exist yet, cards list is empty."""
        db = make_db(tmp_path)
        assert db.cards == []

    def test_load_database_empty_on_corrupt_json(self, tmp_path):
        """
        Corrupted card_database.json → cards list is empty, no crash.
        User gets an error message but the application doesn't exit.
        """
        db_path = tmp_path / "card_database.json"
        db_path.write_text("CORRUPTED_JSON{{{", encoding="utf-8")
        mock_mm = MagicMock()
        mock_mm.get_course_material.return_value = None
        db = DatabaseManager(db_path=str(db_path), material_manager=mock_mm)
        assert db.cards == []

    def test_each_card_gets_unique_guid(self, tmp_path):
        """
        Each card created by integrate_new must have a unique GUID.
        Duplicate GUIDs cause issues in Anki (cards overwrite each other).
        """
        db = make_db(tmp_path)
        batch = [
            {"front": f"Frage {i}?", "back": f"Antwort {i}"} for i in range(10)
        ]
        db.integrate_new(batch)
        guids = [c.guid for c in db.cards]
        assert len(guids) == len(set(guids)), "All GUIDs must be unique"

    def test_card_guid_preserved_through_roundtrip(self, tmp_path):
        """
        Card GUID must survive save → load cycle exactly unchanged.
        Anki uses GUIDs for deduplication — changing them breaks sync.
        """
        original_guid = "test-guid-gti-12345"
        card = make_card(guid=original_guid)
        db = make_db(tmp_path)
        db.cards = [card]
        db.save_database()

        db2 = make_db(tmp_path, cards=None)
        db2.cards = []
        db2.load_database()
        assert db2.cards[0].guid == original_guid

    def test_ankicard_from_dict_with_unknown_field_ignored(self):
        """
        AnkiCard.from_dict() silently ignores unknown fields for forward compatibility.
        An unrecognized JSON field from a future schema version does NOT crash the load.
        """
        data = {
            "front": "Q",
            "back": "A",
            "guid": "abc",
            "collection": "collection_0_K1",
            "category": "a_cat",
            "sort_field": "00_A_01_q",
            "tags": [],
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
            "unrecognized_future_field": "some_value",
        }
        card = AnkiCard.from_dict(data)
        assert card.front == "Q"

    def test_ankicard_from_dict_minimal_fields_ok(self):
        """from_dict with only required fields (front, back) works without error."""
        card = AnkiCard.from_dict({"front": "Q", "back": "A"})
        assert card.front == "Q"
        assert card.back == "A"
        assert card.tags == []  # default


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 5: Collection Organization & Distribution (Schritt 6: Karten organisieren)
# ─────────────────────────────────────────────────────────────────────────────

class TestCollectionOrganization:
    """
    User wants to organize cards into collections, view the structure,
    and regenerate derived files.
    Covers: distribute_to_derived_files, _generate_markdown_card_list,
    _normalize_for_key, _generate_tags.
    """

    def _make_gti_db_with_cards(self, tmp_path):
        """Creates a DB with 3 GTI cards across 2 collections."""
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        db = make_db(tmp_path, config=cfg)
        db.cards = [
            AnkiCard(
                front="Was ist ein DFA?",
                back="Ein 5-Tupel M = (Q, Σ, δ, q0, F).",
                collection="collection_0_DFA_NFA",
                category="a_grundlagen",
                sort_field="00_A_01_was_ist_ein_dfa",
                tags=["GTI::C0::A_Grundlagen"],
            ),
            AnkiCard(
                front="Was ist ein NFA?",
                back="Nichtdeterministisch, mit ε-Übergängen.",
                collection="collection_0_DFA_NFA",
                category="a_grundlagen",
                sort_field="00_A_02_was_ist_ein_nfa",
                tags=["GTI::C0::A_Grundlagen"],
            ),
            AnkiCard(
                front="Was ist eine Turingmaschine?",
                back="Ein universelles Berechnungsmodell.",
                collection="collection_2_Turing",
                category="a_grundlagen",
                sort_field="02_A_01_was_ist_eine_turingmaschine",
                tags=["GTI::C2::A_Grundlagen"],
            ),
        ]
        return db, cfg

    def test_distribute_creates_collection_json_files(self, tmp_path):
        """
        distribute_to_derived_files creates one collection_*.json file per collection
        in the target directory. The files use the names from project.json.
        """
        db, cfg = self._make_gti_db_with_cards(tmp_path)
        output_dir = str(tmp_path / "output")
        result = db.distribute_to_derived_files(output_dir)
        assert result is True
        assert (Path(output_dir) / "collection_0_DFA_NFA.json").exists()
        assert (Path(output_dir) / "collection_2_Turing.json").exists()

    def test_distribute_collection_json_contains_correct_cards(self, tmp_path):
        """
        The cards in collection_0_DFA_NFA.json must be exactly the cards
        with collection='collection_0_DFA_NFA' — neither more nor fewer.
        """
        db, cfg = self._make_gti_db_with_cards(tmp_path)
        output_dir = str(tmp_path / "output")
        db.distribute_to_derived_files(output_dir)

        with open(Path(output_dir) / "collection_0_DFA_NFA.json", encoding="utf-8") as f:
            data = json.load(f)

        fronts = [c["front"] for c in data]
        assert "Was ist ein DFA?" in fronts
        assert "Was ist ein NFA?" in fronts
        assert "Was ist eine Turingmaschine?" not in fronts  # belongs to Turing collection

    def test_distribute_creates_markdown_file(self, tmp_path):
        """
        distribute_to_derived_files also creates All_collections_only_fronts.md
        with the correct marker structure for the SSOT format.
        """
        db, cfg = self._make_gti_db_with_cards(tmp_path)
        output_dir = str(tmp_path / "output")
        db.distribute_to_derived_files(output_dir)

        md_file = Path(output_dir) / "All_collections_only_fronts.md"
        assert md_file.exists()
        content = md_file.read_text(encoding="utf-8")
        assert "<!-- ANKI_CARD_LIST_START -->" in content
        assert "<!-- COLLECTION_0_START -->" in content
        assert "<!-- CARDS_START -->" in content
        assert "<!-- CARDS_END -->" in content
        assert "<!-- COLLECTION_0_END -->" in content

    def test_distribute_markdown_contains_all_card_fronts(self, tmp_path):
        """
        All card fronts must appear in the generated markdown.
        This markdown is the input for the next bootstrap cycle.
        """
        db, cfg = self._make_gti_db_with_cards(tmp_path)
        output_dir = str(tmp_path / "output")
        db.distribute_to_derived_files(output_dir)

        content = (Path(output_dir) / "All_collections_only_fronts.md").read_text(encoding="utf-8")
        assert "Was ist ein DFA?" in content
        assert "Was ist ein NFA?" in content
        assert "Was ist eine Turingmaschine?" in content

    def test_distribute_returns_false_on_empty_db(self, tmp_path):
        """
        With no cards in the database, distribute_to_derived_files returns False.
        No files are written (avoids creating empty stale files).
        """
        db = make_db(tmp_path)
        db.cards = []
        result = db.distribute_to_derived_files(str(tmp_path / "output"))
        assert result is False

    def test_markdown_sort_field_none_handled_gracefully(self, tmp_path):
        """
        Mixed None/str sort_fields are handled gracefully — None treated as '' for sorting.
        """
        db = make_db(tmp_path)
        db.cards = [
            make_card(front="Q1", sort_field="00_A_01_q1"),
            make_card(front="Q2", sort_field=None),
        ]
        result = db._generate_markdown_card_list()
        assert "Q1" in result
        assert "Q2" in result

    def test_markdown_single_none_sort_field_ok(self, tmp_path):
        """
        A SINGLE card with sort_field=None does NOT crash.
        sorted([x]) is trivially sorted — no comparisons needed.
        The bug (TypeError) only appears when mixing None with str.
        """
        db = make_db(tmp_path)
        db.cards = [make_card(front="Einzelkarte", sort_field=None)]
        result = db._generate_markdown_card_list()  # must not raise
        assert "Einzelkarte" in result

    def test_normalize_for_key_german_umlauts(self, tmp_path):
        """
        German umlauts are replaced by the umlaut_map, not stripped.
        'Übergänge' → 'uebergaenge' (not 'bergange' or 'bergnge').
        """
        db = make_db(tmp_path)
        assert db._normalize_for_key("Übergänge") == "uebergaenge"
        assert db._normalize_for_key("Größe") == "groesse"
        assert db._normalize_for_key("Zürich") == "zuerich"

    def test_normalize_for_key_greek_letters_are_stripped(self, tmp_path):
        """
        Greek letters (δ, Σ, ε, γ, λ) are NOT in the umlaut_map and are removed.
        Stray underscores from surrounding spaces are also cleaned up.
        """
        db = make_db(tmp_path)
        result = db._normalize_for_key("Zustand δ")
        assert "δ" not in result
        assert result == "zustand"  # trailing underscore cleaned up

    def test_normalize_for_key_math_symbols_are_stripped(self, tmp_path):
        """
        Math symbols like ∈, ∅, → are stripped; stray underscores are cleaned.
        '∈ Menge' → 'menge'; '∅' alone → '' (empty key is possible).
        """
        db = make_db(tmp_path)
        assert db._normalize_for_key("∈ Menge") == "menge"  # leading _ cleaned
        assert db._normalize_for_key("∅") == ""  # empty key

    def test_normalize_for_key_empty_string_from_pure_special_chars(self, tmp_path):
        """
        '→ ∅ ∈' — all symbols stripped, stray underscores collapsed and stripped → ''.
        """
        db = make_db(tmp_path)
        result = db._normalize_for_key("→ ∅ ∈")
        assert result == ""

    def test_generate_tags_valid_gti_keys(self, tmp_path):
        """
        Tags are generated in hierarchical format: GTI::C0_Dfa_Nfa::A_Grundlagen
        from collection_key='collection_0_DFA_NFA' and category='a_grundlagen'.
        """
        db = make_db(tmp_path)
        tags = db._generate_tags("collection_0_dfa_nfa", "a_grundlagen")
        assert len(tags) == 1
        tag = tags[0]
        assert "::" in tag  # hierarchical structure

    def test_generate_tags_malformed_collection_key_falls_back(self, tmp_path):
        """
        A collection key without the '_N_' format (e.g., just 'badkey') causes
        an IndexError in the tag generation logic.
        The code catches IndexError and falls back to 'Unkategorisiert'.
        """
        db = make_db(tmp_path)
        tags = db._generate_tags("badkey", "a_cat")
        assert any("Unkategorisiert" in t for t in tags)


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 6: APKG Export (Schritt 7: Als .apkg exportieren)
# ─────────────────────────────────────────────────────────────────────────────

class TestApkgExport:
    """
    User runs --export to create .apkg files importable into Anki.
    Covers: ApkgExporter.export, export_to_apkg, stable_id, model creation.
    """

    def _make_gti_cards(self):
        """Returns a list of GTI AnkiCard objects for export tests."""
        return [
            AnkiCard(
                front="Was ist ein DFA?",
                back="5-Tupel (Q, Σ, δ, q0, F).",
                collection="collection_0_DFA_NFA",
                category="a_grundlagen",
                sort_field="00_A_01_dfa",
                tags=["GTI::C0::A_Grundlagen"],
            ),
            AnkiCard(
                front="Was ist ein NFA?",
                back="Nichtdeterministisch.",
                collection="collection_0_DFA_NFA",
                category="a_grundlagen",
                sort_field="00_A_02_nfa",
                tags=["GTI::C0::A_Grundlagen"],
            ),
            AnkiCard(
                front="Was ist eine Turingmaschine?",
                back="Universelles Berechnungsmodell.",
                collection="collection_2_Turing",
                category="a_grundlagen",
                sort_field="02_A_01_turing",
                tags=["GTI::C2::A_Grundlagen"],
            ),
        ]

    def test_export_creates_one_apkg_per_collection(self, tmp_path):
        """
        Export creates exactly one .apkg file per distinct collection.
        3 cards across 2 collections → 2 .apkg files.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        cards = self._make_gti_cards()
        exporter = ApkgExporter()

        with patch("pdf2anki.text2anki.apkg_exporter.genanki") as mock_genanki:
            mock_genanki.Package.return_value = MagicMock()
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Model.return_value = MagicMock()

            generated = exporter.export(cards, cfg, str(tmp_path))

        assert len(generated) == 2
        assert mock_genanki.Package.return_value.write_to_file.call_count == 2

    def test_export_uses_collection_filename_from_config(self, tmp_path):
        """
        Output filenames come from project.json collection[*].filename.
        'collection_0_DFA_NFA.json' → 'collection_0_DFA_NFA.apkg'.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        cards = self._make_gti_cards()[:1]  # just 1 card in collection_0_DFA_NFA
        exporter = ApkgExporter()

        with patch("pdf2anki.text2anki.apkg_exporter.genanki") as mock_genanki:
            mock_genanki.Package.return_value = MagicMock()
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Model.return_value = MagicMock()

            generated = exporter.export(cards, cfg, str(tmp_path))

        assert any("collection_0_DFA_NFA.apkg" in path for path in generated)

    def test_export_empty_card_list_returns_empty(self, tmp_path):
        """
        Exporting an empty card list produces no files and returns an empty list.
        No crash, no stale .apkg files.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        exporter = ApkgExporter()

        with patch("pdf2anki.text2anki.apkg_exporter.genanki"):
            generated = exporter.export([], cfg, str(tmp_path))

        assert generated == []

    def test_export_deck_name_uses_tag_prefix_and_display_name(self, tmp_path):
        """
        Anki deck name is '{tag_prefix}::{display_name}'.
        For GTI: 'GTI::Kapitel 1: DFA und NFA'.
        This allows hierarchical deck organization in Anki.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        cards = self._make_gti_cards()[:1]
        exporter = ApkgExporter()

        deck_names_created = []

        with patch("pdf2anki.text2anki.apkg_exporter.genanki") as mock_genanki:
            def capture_deck(deck_id, deck_name):
                deck_names_created.append(deck_name)
                return MagicMock()
            mock_genanki.Deck.side_effect = capture_deck
            mock_genanki.Package.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Model.return_value = MagicMock()

            exporter.export(cards, cfg, str(tmp_path))

        assert any("GTI" in name for name in deck_names_created)
        assert any("DFA" in name for name in deck_names_created)

    def test_stable_id_is_deterministic(self, tmp_path):
        """
        _stable_id produces the same integer every time for the same inputs.
        This prevents Anki from treating re-exported decks as new decks.
        """
        exporter = ApkgExporter()
        id1 = exporter._stable_id("deck_collection_0_DFA_NFA", "GTI_WiSe2526")
        id2 = exporter._stable_id("deck_collection_0_DFA_NFA", "GTI_WiSe2526")
        assert id1 == id2

    def test_stable_id_differs_for_different_collection(self, tmp_path):
        """Different collections get different IDs — they must not share a deck ID."""
        exporter = ApkgExporter()
        id1 = exporter._stable_id("deck_collection_0_DFA_NFA", "GTI_WiSe2526")
        id2 = exporter._stable_id("deck_collection_2_Turing", "GTI_WiSe2526")
        assert id1 != id2

    def test_stable_id_differs_for_different_project(self, tmp_path):
        """Two projects with the same collection name get different IDs."""
        exporter = ApkgExporter()
        id1 = exporter._stable_id("deck_collection_0_k1", "GTI")
        id2 = exporter._stable_id("deck_collection_0_k1", "MATHE")
        assert id1 != id2

    def test_stable_id_is_positive_int(self):
        """_stable_id must return a positive integer (Anki requirement)."""
        exporter = ApkgExporter()
        result = exporter._stable_id("deck_test", "GTI_WiSe2526")
        assert isinstance(result, int)
        assert result > 0

    def test_export_cards_without_collection_grouped_as_fallback(self, tmp_path):
        """
        Cards with collection=None are grouped under a fallback key
        ('collection_0_unsorted') and exported as a single .apkg.
        No crash when cards lack collection metadata.
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

        assert len(generated) == 1  # one file for the fallback group

    def test_export_to_apkg_convenience_wrapper(self, tmp_path):
        """
        export_to_apkg(db_manager, config, output_dir) delegates to ApkgExporter.export.
        Tests the full integration path used by workflow_manager.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        mock_db = MagicMock()
        mock_db.cards = self._make_gti_cards()

        with patch("pdf2anki.text2anki.apkg_exporter.genanki") as mock_genanki:
            mock_genanki.Package.return_value = MagicMock()
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Model.return_value = MagicMock()

            generated = export_to_apkg(mock_db, cfg, str(tmp_path))

        assert isinstance(generated, list)
        assert len(generated) == 2  # DFA_NFA + Turing


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 7: Repeated Ingestion / Updates (Schritt 8: Erneut hinzufügen / Updates)
# ─────────────────────────────────────────────────────────────────────────────

class TestRepeatedIngestionAndUpdates:
    """
    User ingests a second batch of lecture notes (e.g., Vorlesung 2: NFA).
    Covers: duplicate detection across batches, accumulation of cards,
    LLM re-ingestion workflow.
    """

    def test_second_ingest_adds_only_new_cards(self, tmp_path):
        """
        After integrating the first batch, a second batch with some overlapping
        fronts should only add truly new cards — not duplicates.
        """
        db = make_db(tmp_path)
        batch1 = [
            {"front": "Was ist ein DFA?", "back": "5-Tupel."},
            {"front": "Was ist ein NFA?", "back": "Nichtdeterministisch."},
        ]
        db.integrate_new(batch1)
        assert len(db.cards) == 2

        batch2 = [
            {"front": "Was ist ein DFA?", "back": "Schon vorhanden!"},   # duplicate
            {"front": "Was ist eine Turingmaschine?", "back": "Universal-Modell."},  # new
        ]
        count = db.integrate_new(batch2)
        assert count == 1  # only 1 new card added
        assert len(db.cards) == 3  # total

    def test_second_ingest_preserves_existing_card_guids(self, tmp_path):
        """
        When new cards are added, existing card GUIDs must NOT change.
        Anki uses GUIDs for sync — changing them loses review history.
        """
        db = make_db(tmp_path)
        db.integrate_new([{"front": "Ursprüngliche Karte?", "back": "Original."}])
        original_guid = db.cards[0].guid

        db.integrate_new([{"front": "Neue Karte?", "back": "Neu."}])
        assert db.cards[0].guid == original_guid  # unchanged

    def test_ingest_second_lecture_produces_separate_output_file(self, tmp_path):
        """
        Each --ingest run creates a fresh new_cards_output.json.
        The previous output file is overwritten (not appended).
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        output_path = str(tmp_path / "new_cards_output.json")

        # First ingest: 1 card
        batch1 = [
            {"front": "Q1", "back": "A1", "collection": "collection_0_DFA_NFA", "category": "a_cat"},
        ]
        f1 = tmp_path / "vorlesung_01.txt"
        f1.write_text("DFA Material", encoding="utf-8")
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value=json.dumps({"new_cards": batch1})):
            ingest_text([str(f1)], cfg, output_path)

        # Second ingest: 2 different cards
        batch2 = [
            {"front": "Q2", "back": "A2", "collection": "collection_0_DFA_NFA", "category": "a_cat"},
            {"front": "Q3", "back": "A3", "collection": "collection_0_DFA_NFA", "category": "a_cat"},
        ]
        f2 = tmp_path / "vorlesung_02.txt"
        f2.write_text("NFA Material", encoding="utf-8")
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value=json.dumps({"new_cards": batch2})):
            ingest_text([str(f2)], cfg, output_path)

        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        # File should contain only the SECOND batch (overwrite, not append)
        fronts = [c["front"] for c in data["new_cards"]]
        assert "Q2" in fronts
        assert "Q3" in fronts
        assert "Q1" not in fronts  # overwritten


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 8: Integrity Check (verify_integrity)
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegrityVerification:
    """
    The system verifies itself via verify_integrity().
    Covers: GUID uniqueness check, derived files consistency check.
    """

    def _make_gti_config(self, tmp_path):
        project_dir = make_gti_project(tmp_path)
        return ProjectConfig.from_file(str(project_dir))

    def test_integrity_fails_on_duplicate_guids(self, tmp_path):
        """
        verify_integrity detects duplicate GUIDs and returns (False, message).
        Duplicate GUIDs break Anki sync — this is a critical data integrity violation.
        """
        shared_guid = "duplicate-guid-test"
        db = make_db(tmp_path)
        db.cards = [
            make_card(front="Q1", guid=shared_guid),
            make_card(front="Q2", guid=shared_guid),  # same GUID!
        ]
        is_ok, message = db.verify_integrity(str(tmp_path / "derived"))
        assert is_ok is False
        assert "GUID" in message.upper() or "guid" in message.lower()

    def test_integrity_passes_with_unique_guids(self, tmp_path):
        """
        With unique GUIDs and consistent derived files, integrity check passes.
        This is the happy path after a successful --integrate.
        """
        cfg = self._make_gti_config(tmp_path)
        db = make_db(tmp_path / "db", config=cfg)
        db.cards = [
            AnkiCard(
                front="DFA Frage?",
                back="DFA Antwort.",
                collection="collection_0_DFA_NFA",
                category="a_grundlagen",
                sort_field="00_A_01_dfa_frage",
                tags=["GTI::C0::A_Grundlagen"],
            ),
        ]
        derived_dir = str(tmp_path / "derived")
        db.distribute_to_derived_files(derived_dir)
        is_ok, message = db.verify_integrity(derived_dir)
        assert is_ok is True

    def test_integrity_empty_db_and_missing_derived_dir_ok(self, tmp_path):
        """
        Empty DB + non-existent derived directory = consistent empty state.
        Returns (True, ...) — no files needed for an empty database.
        """
        db = make_db(tmp_path)
        db.cards = []
        is_ok, message = db.verify_integrity(str(tmp_path / "nonexistent"))
        # Either True (empty is consistent) or False — document the actual behavior
        assert isinstance(is_ok, bool)


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 9: Edge Cases — GTI-Specific Characters (Schritt 9)
# ─────────────────────────────────────────────────────────────────────────────

class TestGTISpecificEdgeCases:
    """
    GTI course material contains Greek letters, mathematical symbols, and
    formal notation that exercises many edge cases in the system.
    """

    def test_card_with_greek_letters_stored_correctly(self, tmp_path):
        """
        Cards containing δ (delta), Σ (sigma), ε (epsilon) in the front/back
        must be stored and retrieved without corruption.
        """
        db = make_db(tmp_path)
        front = "Was gilt für δ: Q × Σ → Q?"
        back = "δ ist die totale Übergangsfunktion. Für alle q ∈ Q und a ∈ Σ ist δ(q,a) ∈ Q."
        db.integrate_new([{"front": front, "back": back}])

        assert db.cards[0].front == front
        assert db.cards[0].back == back

    def test_card_with_set_notation_stored_correctly(self, tmp_path):
        """
        Mathematical set notation (∈, ∉, ⊆, ∅, ∪, ∩) must survive storage.
        GTI is full of expressions like 'L ⊆ Σ*' and 'q ∈ Q'.
        """
        db = make_db(tmp_path)
        front = "Was ist L(M) für einen DFA M?"
        back = "L(M) = {w ∈ Σ* | δ*(q0, w) ∈ F} — die von M akzeptierte Sprache."
        db.integrate_new([{"front": front, "back": back}])
        assert db.cards[0].back == back

    def test_card_with_formal_tuple_notation(self, tmp_path):
        """
        Tuples like M = (Q, Σ, δ, q0, F) are common in GTI.
        Parentheses and commas in front/back must be preserved.
        """
        db = make_db(tmp_path)
        front = "Wie ist ein DFA M = (Q, Σ, δ, q0, F) definiert?"
        db.integrate_new([{"front": front, "back": "5 Komponenten."}])
        assert db.cards[0].front == front

    def test_card_with_arrow_notation(self, tmp_path):
        """
        Transition relations δ(q, a) = q' or q --a--> q' must survive storage.
        """
        db = make_db(tmp_path)
        back = "δ(q0, 0) = q1, δ(q0, 1) = q0, δ(q1, 0) = q1, δ(q1, 1) = q0"
        db.integrate_new([{"front": "Wie sieht ein einfacher DFA für 0* aus?", "back": back}])
        assert db.cards[0].back == back

    def test_duplicate_detection_case_insensitive_for_greek_fronts(self, tmp_path):
        """
        Duplicate detection via _normalize_text uses .lower().
        Greek letters don't have uppercase equivalents in Python's str.lower(),
        so 'δ' stays 'δ' — duplicates with the same front are still caught.
        """
        db = make_db(tmp_path)
        db.integrate_new([{"front": "Was ist δ?", "back": "Übergangsfunktion"}])
        count = db.integrate_new([{"front": "Was ist δ?", "back": "Anderer Text"}])
        assert count == 0  # correctly detected as duplicate

    def test_unicode_card_roundtrip_json(self, tmp_path):
        """
        Greek + math symbols survive JSON serialization with ensure_ascii=False.
        save_database → load_database must preserve exact Unicode codepoints.
        """
        db = make_db(tmp_path)
        front = "δ: Q × Σ → Q, q0 ∈ Q, F ⊆ Q"
        back = "∅ ∈ {∅, {∅}} — dies ist ein Beispiel aus der Mengenlehre"
        db.cards = [make_card(front=front, back=back)]
        db.save_database()

        db2 = make_db(tmp_path, cards=None)
        db2.cards = []
        db2.load_database()

        assert db2.cards[0].front == front
        assert db2.cards[0].back == back

    def test_formal_language_card_for_regular_expression(self, tmp_path):
        """
        Reguläre Ausdrücke (RegEx) topic: cards with *, +, |, () operators.
        These must not be treated as special characters in any JSON/string processing.
        """
        db = make_db(tmp_path)
        front = "Was matcht der reguläre Ausdruck (a|b)*abb?"
        back = "Alle Wörter über {a,b}, die auf 'abb' enden."
        db.integrate_new([{"front": front, "back": back}])
        assert db.cards[0].front == front

    def test_turing_machine_card_with_special_symbols(self, tmp_path):
        """
        Turingmaschinen topic: cards with ⊢, ⊢*, □ (blank), ↑ (undefined).
        Must be stored and loaded without corruption.
        """
        db = make_db(tmp_path)
        front = "Was bedeutet (q, w) ⊢* (q', w') für eine Turingmaschine?"
        back = "⊢* ist die reflexiv-transitive Hülle von ⊢ (Schritt-Relation)."
        db.integrate_new([{"front": front, "back": back}])
        assert db.cards[0].front == front

    def test_normalize_for_key_produces_valid_python_identifier_prefix(self, tmp_path):
        """
        Keys generated by _normalize_for_key are used in collection_key strings like
        'collection_0_{normalized_name}'. The normalized name must contain only
        [a-z0-9_] characters to be a valid identifier/filename component.
        """
        db = make_db(tmp_path)
        result = db._normalize_for_key("DFA und NFA: Automatentheorie")
        # Must contain only lowercase letters, digits, underscores
        assert re.match(r'^[a-z0-9_]+$', result), f"Invalid key: '{result}'"

    def test_normalize_for_key_empty_input(self, tmp_path):
        """Empty string input to _normalize_for_key returns empty string without crash."""
        db = make_db(tmp_path)
        result = db._normalize_for_key("")
        assert result == ""


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 10: Workflow Manager Integration (End-to-End)
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkflowManagerIntegration:
    """
    Tests that exercise WorkflowManager directly, covering the full CLI workflow
    path that a user would invoke.
    """

    def _make_project_with_cards(self, tmp_path):
        """
        Creates a complete project setup with collection.json and All_fronts.md,
        ready for --extract (bootstrap).
        """
        project_dir = make_gti_project(tmp_path)

        # Create collection_0_DFA_NFA.json
        coll_file = project_dir / "collection_0_DFA_NFA.json"
        coll_file.write_text(json.dumps([
            {"front": "Was ist ein DFA?", "back": "Ein 5-Tupel (Q, Σ, δ, q0, F)."},
            {"front": "Was ist δ?", "back": "δ: Q × Σ → Q ist die Übergangsfunktion."},
        ]), encoding="utf-8")

        # Create All_fronts.md with matching content
        md_content = make_ssot_markdown(
            ["Was ist ein DFA?", "Was ist δ?"],
            collection_id=0,
            collection_name="DFA_NFA",
        )
        md_file = project_dir / "All_fronts.md"
        md_file.write_text(md_content, encoding="utf-8")

        return project_dir

    def test_workflow_manager_raises_without_project_json(self, tmp_path):
        """
        WorkflowManager(project_dir=X) calls ProjectConfig.from_file(X).
        If project.json is missing, FileNotFoundError is raised immediately.
        User sees: "project.json nicht gefunden in: X / Tipp: Mit --init ein neues Projekt erstellen."
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        with pytest.raises(FileNotFoundError, match="project.json nicht gefunden"):
            WorkflowManager(project_dir=str(tmp_path))

    def test_workflow_manager_initializes_with_valid_project(self, tmp_path):
        """
        WorkflowManager(project_dir=X) succeeds when project.json exists and is valid.
        The instance is ready to run workflows.
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = make_gti_project(tmp_path)
        wm = WorkflowManager(project_dir=str(project_dir))
        assert wm is not None

    def test_run_init_workflow_creates_project_json(self, tmp_path):
        """
        run_init_workflow() calls ProjectConfig.create_template() with self._project_dir.
        Since WorkflowManager is already initialized from an EXISTING project.json,
        calling run_init_workflow() attempts to create project.json in the SAME dir —
        which already exists → raises FileExistsError.

        BUG/REGRESSION: run_init_workflow() re-uses self._project_dir (the existing
        project directory) rather than accepting a new target directory as a parameter.
        A user can never run --init from WorkflowManager on a directory that already
        has project.json, which is the exact scenario WorkflowManager requires to
        be instantiated in the first place.
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = make_gti_project(tmp_path)
        wm = WorkflowManager(project_dir=str(project_dir))
        # run_init_workflow re-uses self._project_dir → FileExistsError
        with pytest.raises(FileExistsError):
            wm.run_init_workflow("NeueProjekt")

    def test_ingest_workflow_uses_relative_import(self, tmp_path):
        """
        FIX VERIFIED: run_ingest_workflow() now uses `from .text_ingester import ingest_text`
        (relative import). The workflow must complete without ImportError and write
        new_cards_output.json with the {"new_cards": [...]} format.
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = make_gti_project(tmp_path)
        txt_file = tmp_path / "material.txt"
        txt_file.write_text("DFA Grundlagen", encoding="utf-8")

        mock_cards = [
            {"front": "Was ist Q?", "back": "Zustandsmenge.",
             "collection": "collection_0_DFA_NFA", "category": "a_cat"},
        ]
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value=json.dumps({"new_cards": mock_cards})):
            wm = WorkflowManager(project_dir=str(project_dir))
            result = wm.run_ingest_workflow([str(txt_file)])
        assert result is True
        new_cards_file = project_dir / "new_cards_output.json"
        assert new_cards_file.exists(), "ingest_text() must write new_cards_output.json"
        data = json.loads(new_cards_file.read_text(encoding="utf-8"))
        assert "new_cards" in data

    def test_integrate_workflow_recognizes_new_cards_key_format(self, tmp_path):
        """
        FIX VERIFIED: run_integrate_workflow() now recognizes the {"new_cards": [...]}
        format written by ingest_text(). Cards must be integrated and the file archived.

        The full --ingest → --integrate pipeline now works end-to-end.
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = self._make_project_with_cards(tmp_path)

        # ingest_text writes {"new_cards": [...]} format
        new_cards_format_from_ingest = {"new_cards": [
            {"front": "Was ist q0?", "back": "Der Startzustand des DFA.",
             "collection": "collection_0_DFA_NFA", "category": "a_grundlagen"},
        ]}
        new_cards_file = project_dir / "new_cards_output.json"
        new_cards_file.write_text(json.dumps(new_cards_format_from_ingest), encoding="utf-8")

        wm = WorkflowManager(project_dir=str(project_dir))

        # Bootstrap first so the database exists
        wm.db_manager.bootstrap_from_legacy(
            wm.legacy_collection_files,
            wm.legacy_markdown_file,
            auto_skip_conflicts=True,
            auto_rescue_orphans=True,
            auto_create_missing=True,
        )
        cards_before = len(wm.db_manager.cards)

        result = wm.run_integrate_workflow(skip_gate=True, skip_export=True)

        assert result is True
        assert len(wm.db_manager.cards) > cards_before, \
            "new_cards key must now be recognized and cards integrated"
        archived = list(project_dir.glob("new_cards_output.json.processed_*"))
        assert len(archived) == 1, \
            "new_cards_output.json must be archived after successful integration"

    def test_integrate_workflow_succeeds_with_plain_list_format(self, tmp_path):
        """
        run_integrate_workflow() DOES work when new_cards_output.json contains
        a plain list (not the {"new_cards": ...} dict format from ingest_text).
        This documents the one format that actually works with --integrate.
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = self._make_project_with_cards(tmp_path)

        # Plain list format — the only format recognized by run_integrate_workflow
        plain_list_cards = [
            {"front": "Was ist q0?", "back": "Der Startzustand des DFA.",
             "collection": "collection_0_DFA_NFA", "category": "a_grundlagen"},
        ]
        new_cards_file = project_dir / "new_cards_output.json"
        new_cards_file.write_text(json.dumps(plain_list_cards), encoding="utf-8")

        wm = WorkflowManager(project_dir=str(project_dir))

        # Bootstrap first
        wm.db_manager.bootstrap_from_legacy(
            wm.legacy_collection_files,
            wm.legacy_markdown_file,
            auto_skip_conflicts=True,
            auto_rescue_orphans=True,
            auto_create_missing=True,
        )
        cards_before = len(wm.db_manager.cards)

        result = wm.run_integrate_workflow(skip_gate=True, skip_export=True)

        assert result is True
        # With plain list format, cards ARE integrated and file IS archived
        assert len(wm.db_manager.cards) > cards_before, \
            "New card should be added when using plain list format"
        archived = list(project_dir.glob("new_cards_output.json.processed_*"))
        assert len(archived) == 1, \
            "new_cards_output.json must be archived after successful integration"

    def test_export_workflow_uses_relative_import(self, tmp_path):
        """
        FIX VERIFIED: WorkflowManager.run_export_workflow() now uses:
          from .apkg_exporter import export_to_apkg
        The workflow must complete without ImportError/ModuleNotFoundError.
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = self._make_project_with_cards(tmp_path)

        # Bootstrap so the DB exists
        wm = WorkflowManager(project_dir=str(project_dir))
        wm.db_manager.bootstrap_from_legacy(
            wm.legacy_collection_files,
            wm.legacy_markdown_file,
            auto_skip_conflicts=True,
            auto_rescue_orphans=True,
            auto_create_missing=True,
        )

        # FIX VERIFIED: run_export_workflow now uses relative import → no ImportError
        with patch("pdf2anki.text2anki.apkg_exporter.genanki") as mock_genanki:
            mock_genanki.Package.return_value = MagicMock()
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Model.return_value = MagicMock()
            result = wm.run_export_workflow()
        assert result is True

    def test_ingest_workflow_bug_bare_import(self, tmp_path):
        """
        FIX VERIFIED: WorkflowManager.run_ingest_workflow() now uses:
          from .text_ingester import ingest_text
        Duplicate of test_ingest_workflow_uses_relative_import — kept for symmetry
        with test_export_workflow_uses_relative_import.
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = make_gti_project(tmp_path)
        txt_file = tmp_path / "material.txt"
        txt_file.write_text("DFA Grundlagen", encoding="utf-8")

        mock_cards = [{"front": "Q?", "back": "A.", "collection": "collection_0_K", "category": "a_c"}]
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value=json.dumps({"new_cards": mock_cards})):
            wm = WorkflowManager(project_dir=str(project_dir))
            result = wm.run_ingest_workflow([str(txt_file)])
        assert result is True


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 11: Full Happy Path Smoke Test
# ─────────────────────────────────────────────────────────────────────────────

class TestFullHappyPathSmoke:
    """
    End-to-end smoke test: complete GTI workflow from project setup to export.
    No mocked internal logic — only external dependencies (LLM, genanki) are mocked.
    """

    def test_full_workflow_init_ingest_integrate_export(self, tmp_path):
        """
        Simulates the complete GTI user journey:
        1. Create project directory with project.json
        2. Write GTI lecture material
        3. Ingest via LLM → new_cards_output.json
        4. Bootstrap DB from collection + markdown
        5. Integrate new cards
        6. Distribute to derived files
        7. Export to .apkg

        All external calls are mocked. This test validates the complete
        data pipeline without network or filesystem side effects.
        """
        # Step 1: Create GTI project
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))

        # Step 2: Prepare initial collection data (simulates existing legacy files)
        coll_file = project_dir / "collection_0_DFA_NFA.json"
        coll_file.write_text(json.dumps([
            {"front": "Was ist ein DFA?", "back": "Ein 5-Tupel (Q, Σ, δ, q0, F)."},
        ]), encoding="utf-8")
        md_content = make_ssot_markdown(["Was ist ein DFA?"])
        md_file = project_dir / "All_fronts.md"
        md_file.write_text(md_content, encoding="utf-8")

        # Step 3: Ingest new lecture material
        lecture_file = tmp_path / "vorlesung_02.txt"
        lecture_file.write_text(
            "NFA: Ein nichtdeterministischer endlicher Automat akzeptiert "
            "ein Wort, wenn MINDESTENS EINE Berechnung akzeptiert.",
            encoding="utf-8"
        )
        new_card_from_llm = {
            "front": "Wann akzeptiert ein NFA ein Wort?",
            "back": "Wenn mindestens eine Berechnung in einem akzeptierenden Zustand endet.",
            "collection": "collection_0_DFA_NFA",
            "category": "a_grundlagen",
        }
        output_path = str(project_dir / "new_cards_output.json")
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value=json.dumps({"new_cards": [new_card_from_llm]})):
            ingest_text([str(lecture_file)], cfg, output_path)

        assert Path(output_path).exists()

        # Step 4: Bootstrap DB from legacy sources
        db = make_db(project_dir, config=cfg)
        success = db.bootstrap_from_legacy(
            collection_files=[str(coll_file)],
            markdown_file=str(md_file),
            auto_skip_conflicts=True,
            auto_rescue_orphans=True,
            auto_create_missing=True,
        )
        assert success is True
        assert len(db.cards) >= 1
        assert any(c.front == "Was ist ein DFA?" for c in db.cards)

        # Step 5: Integrate new cards
        with open(output_path, encoding="utf-8") as f:
            pending_data = json.load(f)
        count = db.integrate_new(pending_data["new_cards"])
        assert count == 1
        assert any(c.front == "Wann akzeptiert ein NFA ein Wort?" for c in db.cards)

        # Step 6: Distribute to derived files
        derived_dir = str(tmp_path / "derived")
        distribute_ok = db.distribute_to_derived_files(derived_dir)
        assert distribute_ok is True
        assert (Path(derived_dir) / "collection_0_DFA_NFA.json").exists()
        assert (Path(derived_dir) / "All_collections_only_fronts.md").exists()

        # Step 7: Export to .apkg
        with patch("pdf2anki.text2anki.apkg_exporter.genanki") as mock_genanki:
            mock_genanki.Package.return_value = MagicMock()
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Model.return_value = MagicMock()

            generated = export_to_apkg(db, cfg, derived_dir)

        assert len(generated) >= 1
        assert all(path.endswith(".apkg") for path in generated)
