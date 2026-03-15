"""Tests for non-standard collection keys (e.g. 'Skript_ws_25' instead of 'collection_N_name').

Covers fixes for:
- P0: Lazy mode skip_gate in integrate call
- P1: Gate check _is_ssot_derived_file (inverted logic)
- P2: Collection sort with _collection_sort_key + enumerate-based markers
"""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pdf2anki.text2anki.card import AnkiCard
from pdf2anki.text2anki.database_manager import (
    DatabaseManager,
    _collection_sort_key,
    _is_ssot_derived_file,
    _is_non_ssot_file,
)


# ─────────────────────────────────────────────────────────────────────────────
# Project data mimicking the Alex GTI run
# ─────────────────────────────────────────────────────────────────────────────

GTI_PROJECT_DATA = {
    "project_name": "GTI_WiSe2526",
    "tag_prefix": "GTI",
    "language": "de",
    "domain": "Grundlagen der Technischen Informatik",
    "orphan_collection_name": "Unsortierte_Karten",
    "files": {
        "db_path": "card_database.json",
        "markdown_file": "All_fronts.md",
        "new_cards_file": "new_cards_output.json",
        "material_file": "course_material.txt",
    },
    "collections": {
        "Skript_ws_25": {
            "display_name": "Skript Wintersemester 25/26",
            "filename": "Skript_ws_25.json",
            "description": "Vorlesungsskript",
        },
        "Uebung_Hausuebungen": {
            "display_name": "Hausuebungen",
            "filename": "Uebung_Hausuebungen.json",
            "description": "Hausuebungsaufgaben",
        },
        "Uebung_Uebungsblaetter": {
            "display_name": "Uebungsblaetter",
            "filename": "Uebung_Uebungsblaetter.json",
            "description": "Uebungsblaetter",
        },
    },
    "llm": {"model": "google/gemini-2.5-flash", "temperature": 0.1},
}


def _make_gti_config(tmp_path):
    """Write GTI project.json and return a ProjectConfig."""
    (tmp_path / "project.json").write_text(
        json.dumps(GTI_PROJECT_DATA), encoding="utf-8"
    )
    from pdf2anki.text2anki.project_config import ProjectConfig
    return ProjectConfig.from_file(str(tmp_path))


def _make_gti_db(tmp_path, cards=None):
    """Create a DatabaseManager with GTI config, optionally pre-seeded."""
    config = _make_gti_config(tmp_path)
    mock_mm = MagicMock()
    mock_mm.get_course_material.return_value = None
    db_path = str(tmp_path / "card_database.json")
    if cards:
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in cards], f)
    return DatabaseManager(db_path=db_path, material_manager=mock_mm, project_config=config)


def _make_gti_cards():
    """Return cards mimicking Alex's GTI run with non-standard keys."""
    return [
        AnkiCard(
            front="Was ist ein Alphabet?",
            back="Eine endliche, nichtleere Menge von Zeichen.",
            collection="Skript_ws_25",
            category="a_grundlagen",
            sort_field="00_A_01_was_ist_ein_alphabet",
            tags=["GTI::Cws_25::A_Grundlagen"],
        ),
        AnkiCard(
            front="Was ist ein Wort?",
            back="Eine Folge von Symbolen aus einem Alphabet.",
            collection="Skript_ws_25",
            category="b_chomsky",
            sort_field="00_A_02_was_ist_ein_wort",
            tags=["GTI::Cws_25::B_Chomsky"],
        ),
        AnkiCard(
            front="Ist Z ein Alphabet?",
            back="Nein, Z ist unendlich.",
            collection="Uebung_Hausuebungen",
            category="a_grundlagen",
            sort_field="00_A_03_ist_z_ein_alphabet",
            tags=["GTI::CHausuebungen_::A_Grundlagen"],
        ),
        AnkiCard(
            front="Was ist eine Grammatik?",
            back="Ein 4-Tupel G = (V, Sigma, P, S).",
            collection="Uebung_Uebungsblaetter",
            category="a_grundlagen",
            sort_field="00_A_04_was_ist_eine_grammatik",
            tags=["GTI::CUebungsblaetter_::A_Grundlagen"],
        ),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# B2: _collection_sort_key handles non-standard keys without crash
# ─────────────────────────────────────────────────────────────────────────────

class TestCollectionSortKey:
    """Verify _collection_sort_key works for both legacy and non-standard keys."""

    def test_legacy_keys_sort_numerically(self):
        keys = ["collection_2_C", "collection_0_A", "collection_1_B"]
        result = sorted(keys, key=_collection_sort_key)
        assert result == ["collection_0_A", "collection_1_B", "collection_2_C"]

    def test_nonstandard_keys_do_not_crash(self):
        keys = ["Skript_ws_25", "Uebung_Hausuebungen", "Uebung_Uebungsblaetter"]
        result = sorted(keys, key=_collection_sort_key)
        # Should sort alphabetically without raising
        assert len(result) == 3

    def test_mixed_keys_legacy_first(self):
        keys = ["Skript_ws_25", "collection_0_A", "Uebung_Hausuebungen"]
        result = sorted(keys, key=_collection_sort_key)
        # Legacy (tuple starts with 0) sorts before non-standard (tuple starts with 1)
        assert result[0] == "collection_0_A"

    def test_single_part_key(self):
        # Edge case: key with no underscore
        result = _collection_sort_key("Alleinstehend")
        assert isinstance(result, tuple)


# ─────────────────────────────────────────────────────────────────────────────
# B3: Gate check with .txt/.pdf in directory does not fail on fresh project
# ─────────────────────────────────────────────────────────────────────────────

class TestGateCheckFreshProject:
    """verify_integrity should pass when DB is empty and only non-SSOT files exist."""

    def test_is_ssot_derived_file_ignores_pdf_and_txt(self):
        known = frozenset({"Skript_ws_25.json", "All_fronts.md"})
        assert not _is_ssot_derived_file("skript.pdf", known)
        assert not _is_ssot_derived_file("skript.txt", known)
        assert not _is_ssot_derived_file("desktop.ini", known)
        assert not _is_ssot_derived_file(".gptignore", known)
        assert not _is_ssot_derived_file("skript.ocr_state.json", known)

    def test_is_ssot_derived_file_recognizes_collection_json(self):
        known = frozenset({"Skript_ws_25.json", "Uebung_Hausuebungen.json"})
        assert _is_ssot_derived_file("Skript_ws_25.json", known)
        assert _is_ssot_derived_file("Uebung_Hausuebungen.json", known)

    def test_is_ssot_derived_file_recognizes_markdown(self):
        assert _is_ssot_derived_file("All_collections_only_fronts.md")
        assert _is_ssot_derived_file("All_fronts.md")

    def test_is_ssot_derived_file_unknown_json_not_derived(self):
        known = frozenset({"Skript_ws_25.json"})
        assert not _is_ssot_derived_file("random_notes.json", known)

    def test_verify_integrity_passes_with_pdfs_and_txts(self, tmp_path):
        """Fresh project: empty DB, directory has PDFs and .txt files — gate must pass."""
        db = _make_gti_db(tmp_path)
        assert len(db.cards) == 0

        # Simulate a project dir with OCR outputs but no card files
        (tmp_path / "skript.pdf").write_bytes(b"%PDF")
        (tmp_path / "skript.txt").write_text("OCR output", encoding="utf-8")
        (tmp_path / "skript.ocr_state.json").write_text("{}", encoding="utf-8")
        (tmp_path / "desktop.ini").write_text("", encoding="utf-8")

        ok, message = db.verify_integrity(str(tmp_path))
        assert ok is True
        assert "leer" in message.lower() or "erfolgreich" in message.lower()

    def test_verify_integrity_fails_when_derived_files_present(self, tmp_path):
        """Empty DB but collection JSON exists — gate should fail."""
        db = _make_gti_db(tmp_path)
        assert len(db.cards) == 0

        # Write a derived collection JSON that the SSOT should have generated
        (tmp_path / "Skript_ws_25.json").write_text("[]", encoding="utf-8")

        ok, message = db.verify_integrity(str(tmp_path))
        assert ok is False


# ─────────────────────────────────────────────────────────────────────────────
# B4: Lazy mode calls integrate with skip_gate=True
# ─────────────────────────────────────────────────────────────────────────────

class TestLazyModeSkipGate:
    """Verify lazy_runner passes skip_gate=True to run_integrate_workflow."""

    def test_integrate_called_with_skip_gate(self, tmp_path):
        (tmp_path / "project.json").write_text(
            json.dumps(GTI_PROJECT_DATA), encoding="utf-8"
        )
        (tmp_path / "vl.pdf").write_bytes(b"%PDF")
        (tmp_path / "vl.txt").write_text("content", encoding="utf-8")

        from pdf2anki.text2anki.lazy_runner import run_lazy_mode

        with patch("pdf2anki.text2anki.lazy_runner.WorkflowManager", autospec=True) as MockWM:
            instance = MockWM.return_value
            instance.run_ingest_workflow.return_value = True
            instance.run_integrate_workflow.return_value = True
            instance.run_export_workflow.return_value = True
            run_lazy_mode(tmp_path)
            instance.run_integrate_workflow.assert_called_once_with(skip_gate=True)


# ─────────────────────────────────────────────────────────────────────────────
# B5: Markdown markers are valid numeric indices
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkdownGeneration:
    """Verify _generate_markdown_card_list produces numeric markers for non-standard keys."""

    def test_markers_are_numeric_with_nonstandard_keys(self, tmp_path):
        cards = _make_gti_cards()
        db = _make_gti_db(tmp_path, cards=cards)
        md = db._generate_markdown_card_list()

        assert "<!-- COLLECTION_0_START -->" in md
        assert "<!-- COLLECTION_0_END -->" in md
        # Should have 3 collections (indices 0, 1, 2)
        assert "<!-- COLLECTION_1_START -->" in md
        assert "<!-- COLLECTION_2_START -->" in md
        # Must NOT contain non-numeric markers
        assert "COLLECTION_ws_START" not in md
        assert "COLLECTION_Hausuebungen_START" not in md

    def test_no_valueerror_with_nonstandard_keys(self, tmp_path):
        """The exact crash scenario from Alex's run."""
        cards = _make_gti_cards()
        db = _make_gti_db(tmp_path, cards=cards)
        # This used to raise ValueError: invalid literal for int() with base 10: 'ws'
        md = db._generate_markdown_card_list()
        assert len(md) > 0

    def test_card_fronts_appear_in_markdown(self, tmp_path):
        cards = _make_gti_cards()
        db = _make_gti_db(tmp_path, cards=cards)
        md = db._generate_markdown_card_list()
        for card in cards:
            assert card.front in md

    def test_legacy_keys_still_produce_numeric_markers(self, tmp_path, sample_config):
        """Backward compat: collection_N_name keys still work."""
        mock_mm = MagicMock()
        mock_mm.get_course_material.return_value = None
        db = DatabaseManager(
            db_path=str(tmp_path / "card_database.json"),
            material_manager=mock_mm,
            project_config=sample_config,
        )
        db.cards = [
            AnkiCard(front="Q1", back="A1", collection="collection_0_Kapitel1",
                     category="a_grund", sort_field="00_A_01"),
            AnkiCard(front="Q2", back="A2", collection="collection_1_Kapitel2",
                     category="a_grund", sort_field="00_A_02"),
        ]
        md = db._generate_markdown_card_list()
        assert "<!-- COLLECTION_0_START -->" in md
        assert "<!-- COLLECTION_1_START -->" in md


# ─────────────────────────────────────────────────────────────────────────────
# B6: Bootstrap roundtrip — generated markdown can be parsed back
# ─────────────────────────────────────────────────────────────────────────────

class TestBootstrapRoundtrip:
    """Markdown generated with enumerate-based markers can be parsed by bootstrap_from_legacy."""

    def test_markers_parseable_by_bootstrap_regex(self, tmp_path):
        import re
        cards = _make_gti_cards()
        db = _make_gti_db(tmp_path, cards=cards)
        md = db._generate_markdown_card_list()

        # The regex used by bootstrap_from_legacy
        blocks = re.findall(
            r'<!-- COLLECTION_(\d+)_START -->(.*?)<!-- COLLECTION_\1_END -->',
            md, re.DOTALL,
        )
        # Should find all 3 collections
        assert len(blocks) == 3
        # IDs should be numeric strings
        assert all(block_id.isdigit() for block_id, _ in blocks)


# ─────────────────────────────────────────────────────────────────────────────
# B7: distribute_to_derived_files works with non-standard keys
# ─────────────────────────────────────────────────────────────────────────────

class TestDistributeNonstandard:
    """Distributing cards with non-standard collection keys creates correct files."""

    def test_creates_collection_jsons_for_nonstandard_keys(self, tmp_path):
        cards = _make_gti_cards()
        db = _make_gti_db(tmp_path, cards=cards)
        result = db.distribute_to_derived_files(str(tmp_path))
        assert result is True
        assert (tmp_path / "Skript_ws_25.json").exists()
        assert (tmp_path / "Uebung_Hausuebungen.json").exists()
        assert (tmp_path / "Uebung_Uebungsblaetter.json").exists()

    def test_creates_markdown_for_nonstandard_keys(self, tmp_path):
        cards = _make_gti_cards()
        db = _make_gti_db(tmp_path, cards=cards)
        db.distribute_to_derived_files(str(tmp_path))
        assert (tmp_path / "All_collections_only_fronts.md").exists()

    def test_integrate_then_distribute_nonstandard(self, tmp_path):
        """Full integrate+distribute pipeline with non-standard keys."""
        db = _make_gti_db(tmp_path)

        new_cards = [
            {"front": "Was ist ein DFA?", "back": "Deterministischer endlicher Automat.",
             "collection": "Skript_ws_25", "category": "c_regulaere_sprachen"},
            {"front": "Was ist Pumping?", "back": "Ein Lemma fuer regulaere Sprachen.",
             "collection": "Uebung_Uebungsblaetter", "category": "c_regulaere_sprachen"},
        ]

        with patch("pdf2anki.text2anki.database_manager.get_llm_decision"):
            added = db.integrate_new(new_cards)

        assert added == 2
        result = db.distribute_to_derived_files(str(tmp_path))
        assert result is True
        assert (tmp_path / "Skript_ws_25.json").exists()
        assert (tmp_path / "Uebung_Uebungsblaetter.json").exists()
        # Markdown should exist and be valid
        assert (tmp_path / "All_collections_only_fronts.md").exists()
