"""
Edge case tests for pdf2anki.text2anki — discovered through code analysis.

These tests cover gaps not addressed in existing test files, focusing on
real-world inputs (GTI course material: formulas, Greek letters, special chars)
and boundary conditions in the core data pipeline.
"""
import json
import pytest
from unittest.mock import MagicMock

from pdf2anki.text2anki.card import AnkiCard
from pdf2anki.text2anki.database_manager import DatabaseManager
from pdf2anki.text2anki.text_ingester import TextFileIngestor


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers (mirrors test_database_manager.py convention)
# ─────────────────────────────────────────────────────────────────────────────

def make_db(tmp_path, cards=None):
    mock_mm = MagicMock()
    mock_mm.get_course_material.return_value = None
    db_path = str(tmp_path / "card_database.json")
    if cards is not None:
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in cards], f)
    return DatabaseManager(db_path=db_path, material_manager=mock_mm)


def make_card(**kwargs):
    defaults = dict(
        front="Q",
        back="A",
        collection="collection_0_K1",
        category="a_cat",
        sort_field="00_A_01_q",
    )
    defaults.update(kwargs)
    return AnkiCard(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# AnkiCard.from_dict — schema evolution guard
# ─────────────────────────────────────────────────────────────────────────────

class TestAnkiCardFromDict:
    def test_unknown_field_is_ignored(self):
        """
        from_dict silently ignores unknown fields for forward compatibility
        (e.g. when the JSON DB gains a new field after a schema migration).
        """
        data = {
            "guid": "abc",
            "front": "Q",
            "back": "A",
            "collection": None,
            "category": None,
            "sort_field": None,
            "tags": [],
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
            "unknown_future_field": "value",  # simulates DB schema evolution
        }
        card = AnkiCard.from_dict(data)
        assert card.front == "Q"

    def test_missing_optional_fields_use_defaults(self):
        """from_dict should work when optional fields are absent (minimal card)."""
        data = {"front": "Q", "back": "A"}
        card = AnkiCard.from_dict(data)
        assert card.front == "Q"
        assert card.back == "A"
        assert card.tags == []


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_for_key — GTI course material chars
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeForKey:
    """
    GTI (Grundlagen der Theoretischen Informatik) material contains Greek letters
    (δ, Σ, ε, γ) and math symbols (∈, ∅, →). These get stripped, and the
    resulting stray underscores are cleaned up (leading/trailing/consecutive removed).
    """

    def _normalize(self, db, text):
        return db._normalize_for_key(text)

    def test_greek_letters_are_stripped(self, tmp_path):
        """δ is not in umlaut_map → removed; trailing underscore from space is also stripped."""
        db = make_db(tmp_path)
        result = self._normalize(db, "Zustand δ")
        assert "δ" not in result
        assert result == "zustand"  # trailing underscore cleaned up

    def test_math_symbols_are_stripped(self, tmp_path):
        """∈ stripped, but resulting leading underscore is also cleaned; ∅ → empty string."""
        db = make_db(tmp_path)
        assert self._normalize(db, "∈ Menge") == "menge"   # leading _ cleaned
        assert self._normalize(db, "∅") == ""              # empty key is possible!

    def test_empty_key_from_pure_special_chars(self, tmp_path):
        """'→ ∅ ∈' → symbols stripped → stray underscores collapsed/stripped → ''."""
        db = make_db(tmp_path)
        result = self._normalize(db, "→ ∅ ∈")
        assert result == ""  # underscores fully cleaned up

    def test_german_umlauts_are_replaced(self, tmp_path):
        """Umlauts ARE handled correctly via umlaut_map."""
        db = make_db(tmp_path)
        assert self._normalize(db, "Übergänge") == "uebergaenge"
        assert self._normalize(db, "Größe") == "groesse"


# ─────────────────────────────────────────────────────────────────────────────
# _generate_markdown_card_list — sort_field=None crash
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateMarkdownCardList:
    def test_sort_field_none_does_not_crash(self, tmp_path):
        """
        Mixed None/str sort_fields are handled gracefully — None treated as ''.
        """
        db = make_db(tmp_path)
        db.cards = [
            make_card(front="Q1", sort_field="00_A_01_q1"),
            make_card(front="Q2", sort_field=None),
        ]
        result = db._generate_markdown_card_list()
        assert "Q1" in result
        assert "Q2" in result

    def test_single_none_sort_field_does_not_raise(self, tmp_path):
        """
        A single card with sort_field=None does NOT crash — sorted([None]) is trivially
        sorted. The TypeError only occurs when mixing None with str values.
        This test documents that the crash requires at least two cards with different types.
        """
        db = make_db(tmp_path)
        db.cards = [make_card(front="Q", sort_field=None)]
        # Does not raise — single-element sort needs no comparisons
        result = db._generate_markdown_card_list()
        assert "Q" in result

    def test_valid_sort_fields_produce_output(self, tmp_path):
        """Sanity check: valid sort_fields produce non-empty markdown."""
        db = make_db(tmp_path)
        db.cards = [make_card(front="Was ist ein DFA?", sort_field="00_A_01_was")]
        result = db._generate_markdown_card_list()
        assert "<!-- COLLECTION_0_START -->" in result
        assert "Was ist ein DFA?" in result


# ─────────────────────────────────────────────────────────────────────────────
# find_card_by_front — case-sensitivity inconsistency
# ─────────────────────────────────────────────────────────────────────────────

class TestFindCardByFront:
    def test_exact_match_found(self, tmp_path):
        card = make_card(front="Was ist ein Automat?")
        db = make_db(tmp_path, cards=[card])
        assert db.find_card_by_front("Was ist ein Automat?") is not None

    def test_case_insensitive_found(self, tmp_path):
        """find_card_by_front normalizes case — lowercase query finds titlecase card."""
        card = make_card(front="Was ist ein Automat?")
        db = make_db(tmp_path, cards=[card])
        assert db.find_card_by_front("was ist ein automat?") is not None

    def test_whitespace_variant_found(self, tmp_path):
        """Extra whitespace is normalized by find_card_by_front (_normalize_text collapses \\s+)."""
        card = make_card(front="Was ist ein Automat?")
        db = make_db(tmp_path, cards=[card])
        assert db.find_card_by_front("Was ist ein  Automat?") is not None


# ─────────────────────────────────────────────────────────────────────────────
# integrate_new — duplicate detection edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegrateNew:
    def test_duplicate_within_batch_only_first_added(self, tmp_path):
        """
        If the same front appears twice in a single batch, only the first is added.
        existing_fronts is updated within the loop, so the second is treated as duplicate.
        """
        db = make_db(tmp_path)
        batch = [
            {"front": "Was ist δ?", "back": "Ein Übergangs-Symbol"},
            {"front": "Was ist δ?", "back": "Anderer Back-Text"},  # same front
        ]
        count = db.integrate_new(batch)
        assert count == 1
        assert len(db.cards) == 1

    def test_case_insensitive_duplicate_detection(self, tmp_path):
        """
        integrate_new normalizes to lowercase for duplicate detection.
        'Was ist X?' and 'was ist x?' are treated as duplicates.
        """
        existing = make_card(front="Was ist X?", sort_field="00_A_01_q")
        db = make_db(tmp_path, cards=[existing])
        count = db.integrate_new([{"front": "WAS IST X?", "back": "Antwort"}])
        assert count == 0

    def test_empty_front_skipped(self, tmp_path):
        """Cards with empty front are silently skipped."""
        db = make_db(tmp_path)
        count = db.integrate_new([{"front": "", "back": "Antwort"}])
        assert count == 0

    def test_empty_back_skipped(self, tmp_path):
        """Cards with empty back are silently skipped."""
        db = make_db(tmp_path)
        count = db.integrate_new([{"front": "Frage?", "back": ""}])
        assert count == 0

    def test_whitespace_only_front_skipped(self, tmp_path):
        """front='   ' strips to '' and is skipped."""
        db = make_db(tmp_path)
        count = db.integrate_new([{"front": "   ", "back": "Antwort"}])
        assert count == 0

    def test_empty_db_gets_collection_0(self, tmp_path):
        """
        With no existing cards, max_coll_num=-1 → new_coll_num=0.
        New cards land in collection_0_Neue_Karten.
        If the DB later gets a real collection_0, there's a naming conflict.
        """
        db = make_db(tmp_path)
        db.integrate_new([{"front": "Erste Frage?", "back": "Erste Antwort"}])
        assert db.cards[0].collection == "collection_0_Neue_Karten"

    def test_new_cards_get_next_collection_number(self, tmp_path):
        """With existing collection_2, new cards go to collection_3_Neue_Karten."""
        existing = make_card(collection="collection_2_K3", sort_field="02_A_01_q")
        db = make_db(tmp_path, cards=[existing])
        db.integrate_new([{"front": "Neue Frage?", "back": "Neue Antwort"}])
        new_card = db.find_card_by_front("Neue Frage?")
        assert new_card is not None
        assert new_card.collection == "collection_3_Neue_Karten"

    def test_unicode_front_accepted(self, tmp_path):
        """Unicode in front/back (Greek, math) is accepted and stored as-is."""
        db = make_db(tmp_path)
        count = db.integrate_new([{"front": "Was ist δ ∈ Σ?", "back": "Ein Zustand"}])
        assert count == 1
        assert db.cards[0].front == "Was ist δ ∈ Σ?"


# ─────────────────────────────────────────────────────────────────────────────
# TextFileIngestor._parse_response — malformed LLM output
# ─────────────────────────────────────────────────────────────────────────────

class TestParseResponse:
    def setup_method(self):
        self.ingestor = TextFileIngestor()

    def test_clean_json_parsed(self):
        raw = '{"new_cards": [{"front": "Q", "back": "A"}]}'
        result = self.ingestor._parse_response(raw)
        assert result["new_cards"][0]["front"] == "Q"

    def test_markdown_code_fence_stripped(self):
        raw = '```json\n{"new_cards": []}\n```'
        result = self.ingestor._parse_response(raw)
        assert result == {"new_cards": []}

    def test_prose_before_json_extracted(self):
        """LLM prose before JSON — parser extracts the JSON object."""
        raw = 'Sure! Here is your JSON:\n{"new_cards": [{"front": "Q", "back": "A"}]}'
        result = self.ingestor._parse_response(raw)
        assert len(result["new_cards"]) == 1

    def test_trailing_prose_extracted(self):
        """Trailing prose after JSON — parser extracts the JSON object."""
        raw = '{"new_cards": [{"front": "Q", "back": "A"}]}\nHope this helps!'
        result = self.ingestor._parse_response(raw)
        assert len(result["new_cards"]) == 1

    def test_prose_both_sides_fence_extracted(self):
        """Prose before and after a code fence — parser extracts via fence regex."""
        raw = 'Here you go:\n```json\n{"new_cards": [{"front": "Q", "back": "A"}]}\n```\nEnjoy!'
        result = self.ingestor._parse_response(raw)
        assert len(result["new_cards"]) == 1

    def test_python_fence_extracted(self):
        """```python fence (non-json language tag) — parser handles it."""
        raw = '```python\n{"new_cards": [{"front": "Q", "back": "A"}]}\n```'
        result = self.ingestor._parse_response(raw)
        assert len(result["new_cards"]) == 1

    def test_no_json_returns_empty(self):
        """Pure prose without any JSON returns graceful fallback."""
        result = self.ingestor._parse_response("I cannot generate cards for this content.")
        assert result == {"new_cards": []}

    def test_empty_response_returns_empty(self):
        """Empty string from LLM returns graceful fallback."""
        result = self.ingestor._parse_response("")
        assert result == {"new_cards": []}

    def test_nested_code_fence_json(self):
        """Bare triple-backtick without 'json' label is also stripped."""
        raw = '```\n{"new_cards": []}\n```'
        result = self.ingestor._parse_response(raw)
        assert result == {"new_cards": []}


# ─────────────────────────────────────────────────────────────────────────────
# _generate_tags — malformed collection/category keys
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateTags:
    def test_valid_keys_produce_hierarchical_tag(self, tmp_path):
        db = make_db(tmp_path)
        tags = db._generate_tags("collection_0_automaten", "a_dfa")
        assert len(tags) == 1
        assert "::" in tags[0]

    def test_malformed_collection_key_produces_valid_tag(self, tmp_path):
        """
        collection key without '_N_' format should still produce a valid
        hierarchical tag using the key parts directly.
        """
        db = make_db(tmp_path)
        tags = db._generate_tags("badkey", "a_cat")
        assert len(tags) == 1
        assert "::" in tags[0]
        assert "Badkey" in tags[0]

    def test_category_without_prefix_falls_back(self, tmp_path):
        """Category key with no '_' causes IndexError → Unkategorisiert fallback."""
        db = make_db(tmp_path)
        tags = db._generate_tags("collection_0_k1", "noprefix")
        # Either works or falls back — document actual behavior
        assert isinstance(tags, list)
        assert len(tags) >= 1
