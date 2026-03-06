"""
test_specification.py — Specification Tests (Prescriptive / Target Behavior)

These tests define DESIRED future behavior. They are currently RED.
Each test documents:
  - the observed deficiency (current behavior)
  - the specified target behavior
  - a failing assertion that will turn green once the code is fixed

Specs defined here:
  SPEC-1  AnkiCard.from_dict ignores unknown fields (forward-compatibility)
  SPEC-2  _normalize_for_key strips leading/trailing underscores and collapses
          consecutive underscores from stripped-away characters
  SPEC-3  _generate_sort_field expands umlauts (ä→ae) consistently with
          _normalize_for_key, rather than dropping them silently
  SPEC-4  _generate_markdown_card_list treats sort_field=None as "" (no crash)
  SPEC-5  _parse_response returns {"new_cards": []} on parse failure instead of
          raising JSONDecodeError
  SPEC-6  find_card_by_front matches case-insensitively, consistent with
          integrate_new deduplication
"""

import json
import pytest
from unittest.mock import MagicMock

from pdf2anki.text2anki.card import AnkiCard
from pdf2anki.text2anki.database_manager import DatabaseManager
from pdf2anki.text2anki.text_ingester import TextFileIngestor


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_db(tmp_path) -> DatabaseManager:
    mock_mm = MagicMock()
    mock_mm.get_course_material.return_value = None
    return DatabaseManager(
        db_path=str(tmp_path / "card_database.json"),
        material_manager=mock_mm,
    )


def make_card(**kwargs) -> AnkiCard:
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
# SPEC-1: AnkiCard.from_dict — forward-compatibility with unknown fields
# ─────────────────────────────────────────────────────────────────────────────

class TestSpec1FromDictForwardCompatibility:
    """
    SPEC: AnkiCard.from_dict must silently ignore fields not in the dataclass.

    Current behavior:  from_dict(**data) passes all keys as kwargs → TypeError
                       for any unrecognised field.
    Target behavior:   Unknown fields are stripped before construction.
                       The card is created from known fields only.

    Motivation: The on-disk card_database.json schema will evolve. Any new field
    added to the DB (e.g. by a future version of the tool, or by a manual edit)
    must not prevent loading existing cards. Forward-compatibility is a
    non-negotiable data-persistence guarantee.
    """

    def test_unknown_field_is_ignored_not_raised(self):
        """
        SPEC-1a: from_dict with an extra field does NOT raise TypeError.
        The card is constructed from known fields only.
        """
        data = {
            "front": "Q",
            "back": "A",
            "guid": "test-guid",
            "collection": None,
            "category": None,
            "sort_field": None,
            "tags": [],
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
            "unknown_future_field": "some_value",
        }
        # SPEC: must not raise
        card = AnkiCard.from_dict(data)
        assert card.front == "Q"
        assert card.back == "A"
        assert card.guid == "test-guid"

    def test_multiple_unknown_fields_all_ignored(self):
        """
        SPEC-1b: Multiple unknown fields are all silently ignored.
        """
        data = {
            "front": "Q",
            "back": "A",
            "new_field_1": 42,
            "new_field_2": ["list", "value"],
            "new_field_3": {"nested": "dict"},
        }
        card = AnkiCard.from_dict(data)
        assert card.front == "Q"
        assert card.back == "A"

    def test_load_database_with_unknown_field_in_json_succeeds(self, tmp_path):
        """
        SPEC-1c: load_database() must succeed when card_database.json contains
        cards with extra fields. The current crash propagates from from_dict
        through load_database to the caller — this must not happen.
        """
        card_with_extra = {
            "front": "Q",
            "back": "A",
            "guid": "abc",
            "collection": "collection_0_K1",
            "category": "a_cat",
            "sort_field": "00_A_01_q",
            "tags": [],
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
            "added_by_future_version": True,
        }
        db_path = tmp_path / "card_database.json"
        db_path.write_text(json.dumps([card_with_extra]), encoding="utf-8")

        db = make_db(tmp_path)
        # SPEC: must load successfully
        assert len(db.cards) == 1
        assert db.cards[0].front == "Q"


# ─────────────────────────────────────────────────────────────────────────────
# SPEC-2: _normalize_for_key — clean underscore output
# ─────────────────────────────────────────────────────────────────────────────

class TestSpec2NormalizeForKeyCleanUnderscores:
    """
    SPEC: _normalize_for_key must produce clean keys — no leading underscores,
    no trailing underscores, no consecutive underscores.

    Current behavior:  Stripped characters leave their space-converted underscores
                       behind. "∈ Menge" → "_menge" (leading _). "ε, Σ, ∈" → "____".
    Target behavior:   - Leading and trailing underscores are stripped from result.
                       - Consecutive underscores are collapsed to a single underscore.
                       - A key consisting only of underscores becomes "".

    Motivation: Keys are used as collection/category identifiers and as components
    of filenames. Leading underscores and runs of underscores are meaningless noise
    that makes keys harder to read and potentially causes filesystem issues.
    """

    def test_leading_underscore_stripped(self, tmp_path):
        """
        SPEC-2a: "∈ Menge" → "menge" (not "_menge").
        The ∈ is stripped, the space becomes _, then leading _ is removed.
        """
        db = make_db(tmp_path)
        result = db._normalize_for_key("∈ Menge")
        assert not result.startswith("_"), f"Leading underscore not stripped: '{result}'"
        assert result == "menge"

    def test_trailing_underscore_stripped(self, tmp_path):
        """
        SPEC-2b: "Menge ∈" → "menge" (not "menge_").
        The trailing space+∈ becomes _, then trailing _ is removed.
        """
        db = make_db(tmp_path)
        result = db._normalize_for_key("Menge ∈")
        assert not result.endswith("_"), f"Trailing underscore not stripped: '{result}'"
        assert result == "menge"

    def test_consecutive_underscores_collapsed(self, tmp_path):
        """
        SPEC-2c: "Menge  ∈  der" → "menge_der" (not "menge___der").
        Multiple stripped characters between words collapse to a single separator.
        """
        db = make_db(tmp_path)
        result = db._normalize_for_key("Menge  ∈  der")
        assert "__" not in result, f"Consecutive underscores not collapsed: '{result}'"
        assert result == "menge_der"

    def test_all_special_chars_produces_empty_string(self, tmp_path):
        """
        SPEC-2d: "ε, Σ, ∈, ℕ, ∅" → "" (empty string, not "____").
        When all meaningful content is stripped, the result is empty — not underscores.
        """
        db = make_db(tmp_path)
        result = db._normalize_for_key("ε, Σ, ∈, ℕ, ∅")
        assert result == "", f"Expected empty string, got: '{result}'"

    def test_clean_input_unaffected(self, tmp_path):
        """
        SPEC-2e: Clean ASCII input is unaffected by the new stripping logic.
        "Kapitel 1" → "kapitel_1" (no change from current behavior).
        """
        db = make_db(tmp_path)
        assert db._normalize_for_key("Kapitel 1") == "kapitel_1"
        assert db._normalize_for_key("Reguläre Sprachen") == "regulaere_sprachen"


# ─────────────────────────────────────────────────────────────────────────────
# SPEC-3: _generate_sort_field — consistent umlaut expansion
# ─────────────────────────────────────────────────────────────────────────────

class TestSpec3SortFieldUmlautExpansion:
    """
    SPEC: _generate_sort_field must expand umlauts (ä→ae, ö→oe, ü→ue, ß→ss)
    in the front-text portion of the sort field, consistent with _normalize_for_key.

    Current behavior:  _generate_sort_field uses _normalize_text on the front,
                       which lowercases but does NOT expand umlauts. Then the
                       re.sub(r'[^a-z0-9_]') call strips the umlaut entirely.
                       "Erkläre..." → "erklre..." (ä silently dropped).
    Target behavior:   The front portion of the sort_field must expand umlauts:
                       "Erkläre..." → "erklaere..."

    Motivation: Silently dropping ä produces sort_fields that are (a) misleading
    as human-readable identifiers, and (b) can cause false collisions between
    "Erkläre X" and "Erklre X" if such a front ever exists. Expansion preserves
    meaning and matches the key-normalization behavior already used elsewhere.
    """

    def test_umlaut_ae_expanded_in_sort_field(self, tmp_path):
        """
        SPEC-3a: sort_key='00_A_01', front='Erkläre den Begriff'
        → '00_A_01_erklaere_den_begriff' (ä → ae, not dropped).
        """
        db = make_db(tmp_path)
        result = db._generate_sort_field("00_A_01", "Erkläre den Begriff")
        assert "erklaere" in result, f"Expected 'erklaere' in sort_field, got: '{result}'"
        assert result == "00_A_01_erklaere_den_begriff"

    def test_umlaut_oe_expanded_in_sort_field(self, tmp_path):
        """
        SPEC-3b: front='Größe der Menge' → sort_field contains 'groesse'.
        ö → oe (not dropped).
        """
        db = make_db(tmp_path)
        result = db._generate_sort_field("00_A_02", "Größe der Menge")
        assert "groesse" in result, f"Expected 'groesse' in sort_field, got: '{result}'"

    def test_umlaut_ue_expanded_in_sort_field(self, tmp_path):
        """
        SPEC-3c: front='Übergangsfunktion δ' → sort_field contains 'ueber'.
        ü → ue (not dropped).
        """
        db = make_db(tmp_path)
        result = db._generate_sort_field("00_A_03", "Übergangsfunktion δ")
        assert "ueber" in result, f"Expected 'ueber' in sort_field, got: '{result}'"

    def test_sz_expanded_in_sort_field(self, tmp_path):
        """
        SPEC-3d: front='Maßzahl der Komplexität' → sort_field contains 'massz'.
        ß → ss (not dropped).
        """
        db = make_db(tmp_path)
        result = db._generate_sort_field("01_A_01", "Maßzahl der Komplexität")
        assert "mass" in result, f"Expected 'mass' in sort_field, got: '{result}'"

    def test_sort_field_expansion_consistent_with_normalize_for_key(self, tmp_path):
        """
        SPEC-3e: The normalized front portion of the sort_field must be equal to
        _normalize_for_key applied to the same front (modulo the 50-char truncation).
        This ensures a single normalization path throughout the system.
        """
        db = make_db(tmp_path)
        front = "Äquivalenzklassen der regulären Sprachen"
        sort_field = db._generate_sort_field("00_A_01", front)
        key_norm = db._normalize_for_key(front)
        # The sort_field suffix (after "00_A_01_") must start with the key_norm prefix
        suffix = sort_field[len("00_A_01_"):]
        assert key_norm.startswith(suffix) or suffix.startswith(key_norm[:len(suffix)]), \
            f"Sort field suffix '{suffix}' inconsistent with _normalize_for_key '{key_norm}'"


# ─────────────────────────────────────────────────────────────────────────────
# SPEC-4: _generate_markdown_card_list — None sort_field handled gracefully
# ─────────────────────────────────────────────────────────────────────────────

class TestSpec4SortFieldNoneGraceful:
    """
    SPEC: _generate_markdown_card_list must handle sort_field=None without crashing.
    Cards with sort_field=None are sorted as if sort_field="".

    Current behavior:  sorted(..., key=lambda c: c.sort_field) raises TypeError
                       when mixing None and str values (Python 3 does not allow
                       comparison of NoneType and str).
    Target behavior:   sort_field=None is treated as "" in the sort key.
                       Cards with None appear at the beginning of the list.
                       No TypeError is raised.

    Motivation: Cards added manually (without going through integrate_new) or
    cards with legacy data may have sort_field=None. The markdown generation
    must be robust to this — a crash here prevents the entire distribute workflow.
    """

    def test_single_card_with_none_sort_field_does_not_crash(self, tmp_path):
        """
        SPEC-4a: A single card with sort_field=None produces markdown without crash.
        (Single-element lists don't trigger comparisons — already works. This test
        is here for completeness.)
        """
        db = make_db(tmp_path)
        db.cards = [make_card(front="Q", sort_field=None)]
        result = db._generate_markdown_card_list()
        assert "Q" in result

    def test_mixed_none_and_str_sort_fields_do_not_crash(self, tmp_path):
        """
        SPEC-4b: A mix of sort_field=None and sort_field=str does NOT raise TypeError.
        The None card sorts before all str cards (treated as "").
        """
        db = make_db(tmp_path)
        db.cards = [
            make_card(front="Q_with_sort", sort_field="00_A_02_q"),
            make_card(front="Q_no_sort", sort_field=None),
        ]
        # SPEC: must not raise TypeError
        result = db._generate_markdown_card_list()
        assert "Q_with_sort" in result
        assert "Q_no_sort" in result

    def test_all_none_sort_fields_do_not_crash(self, tmp_path):
        """
        SPEC-4c: Multiple cards all with sort_field=None must not raise TypeError.
        (Comparing None to None is fine in Python — but this ensures the code
        does not introduce any other None-sensitive logic.)
        """
        db = make_db(tmp_path)
        db.cards = [
            make_card(front="Q1", sort_field=None),
            make_card(front="Q2", sort_field=None),
            make_card(front="Q3", sort_field=None),
        ]
        result = db._generate_markdown_card_list()
        assert "Q1" in result
        assert "Q2" in result
        assert "Q3" in result

    def test_none_sort_field_card_appears_in_output(self, tmp_path):
        """
        SPEC-4d: Cards with sort_field=None must appear in the markdown output —
        they must not be silently dropped when sort_field is None.
        """
        db = make_db(tmp_path)
        db.cards = [make_card(front="Unsortierte Karte", sort_field=None)]
        result = db._generate_markdown_card_list()
        assert "Unsortierte Karte" in result


# ─────────────────────────────────────────────────────────────────────────────
# SPEC-5: _parse_response — graceful fallback on parse failure
# ─────────────────────────────────────────────────────────────────────────────

class TestSpec5ParseResponseGracefulFallback:
    """
    SPEC: TextFileIngestor._parse_response must return {"new_cards": []} when
    the response cannot be parsed as JSON, rather than raising JSONDecodeError.

    Current behavior:  json.loads() is called directly. Any response that is not
                       valid JSON (prose before/after, malformed JSON, empty string)
                       raises JSONDecodeError which propagates uncaught to ingest().
    Target behavior:   On parse failure, return {"new_cards": []} as a safe empty
                       result. The caller (ingest()) already handles empty results
                       gracefully — this completes the error chain.

    Motivation: LLMs frequently add conversational text around the JSON response
    ("Sure! Here are your cards: {...}" or "Hope this helps!"). These are
    recoverable situations — they should produce 0 cards, not a crash.
    """

    def setup_method(self):
        self.ingestor = TextFileIngestor()

    def test_prose_before_json_returns_empty(self):
        """
        SPEC-5a: "Sure! Here is your JSON: {...}" → {"new_cards": []}.
        Prose before the JSON currently raises JSONDecodeError.
        """
        raw = 'Sure! Here is your JSON:\n{"new_cards": []}'
        result = self.ingestor._parse_response(raw)
        assert result == {"new_cards": []}

    def test_trailing_prose_returns_empty(self):
        """
        SPEC-5b: '{"new_cards": []}\nHope this helps!' → {"new_cards": []}.
        Trailing prose after valid JSON currently raises JSONDecodeError.
        """
        raw = '{"new_cards": []}\nHope this helps!'
        result = self.ingestor._parse_response(raw)
        assert result == {"new_cards": []}

    def test_empty_response_returns_empty(self):
        """
        SPEC-5c: Empty string → {"new_cards": []}.
        LLM API failures can return empty strings.
        """
        result = self.ingestor._parse_response("")
        assert result == {"new_cards": []}

    def test_completely_invalid_response_returns_empty(self):
        """
        SPEC-5d: Completely non-JSON response → {"new_cards": []}.
        """
        result = self.ingestor._parse_response("Internal server error 500")
        assert result == {"new_cards": []}

    def test_valid_json_still_parsed_correctly(self):
        """
        SPEC-5e: Valid JSON responses must still be parsed correctly.
        Graceful fallback must not break the happy path.
        """
        raw = '{"new_cards": [{"front": "Q", "back": "A"}]}'
        result = self.ingestor._parse_response(raw)
        assert result["new_cards"][0]["front"] == "Q"

    def test_code_fence_json_still_parsed_correctly(self):
        """
        SPEC-5f: ```json ... ``` wrapping must still work after adding fallback.
        """
        raw = '```json\n{"new_cards": []}\n```'
        result = self.ingestor._parse_response(raw)
        assert result == {"new_cards": []}


# ─────────────────────────────────────────────────────────────────────────────
# SPEC-6: find_card_by_front — case-insensitive matching
# ─────────────────────────────────────────────────────────────────────────────

class TestSpec6FindCardByFrontCaseInsensitive:
    """
    SPEC: find_card_by_front must use the same normalization as integrate_new
    (i.e. _normalize_text: lowercase + collapse whitespace) for matching.

    Current behavior:  card.front == front_text (exact string equality).
                       "Was ist X?" is not found by "was ist x?" or "Was  ist  X?".
    Target behavior:   Matching is case-insensitive and whitespace-normalized,
                       consistent with how integrate_new detects duplicates.

    Motivation: A user searching for a card should not need to remember the exact
    casing used when the card was created. The inconsistency between integrate_new
    (case-insensitive) and find_card_by_front (case-sensitive) means a card can
    be "not found" while simultaneously being "a duplicate" — a contradiction.
    """

    def test_lowercase_query_finds_titlecase_card(self, tmp_path):
        """
        SPEC-6a: find_card_by_front("was ist ein automat?") finds a card stored
        as "Was ist ein Automat?".
        """
        db = make_db(tmp_path)
        db.cards = [make_card(front="Was ist ein Automat?")]
        result = db.find_card_by_front("was ist ein automat?")
        assert result is not None
        assert result.front == "Was ist ein Automat?"

    def test_uppercase_query_finds_lowercase_card(self, tmp_path):
        """
        SPEC-6b: find_card_by_front("WAS IST EIN AUTOMAT?") finds a card stored
        as "was ist ein automat?".
        """
        db = make_db(tmp_path)
        db.cards = [make_card(front="was ist ein automat?")]
        result = db.find_card_by_front("WAS IST EIN AUTOMAT?")
        assert result is not None

    def test_extra_whitespace_in_query_finds_card(self, tmp_path):
        """
        SPEC-6c: find_card_by_front("Was  ist  ein  Automat?") (double spaces)
        finds a card stored as "Was ist ein Automat?" (single spaces).
        _normalize_text collapses whitespace runs — this must apply to the query too.
        """
        db = make_db(tmp_path)
        db.cards = [make_card(front="Was ist ein Automat?")]
        result = db.find_card_by_front("Was  ist  ein  Automat?")
        assert result is not None

    def test_exact_match_still_works(self, tmp_path):
        """
        SPEC-6d: Exact-match queries must still work after adding normalization.
        The happy path must not break.
        """
        db = make_db(tmp_path)
        db.cards = [make_card(front="Was ist ein Automat?")]
        result = db.find_card_by_front("Was ist ein Automat?")
        assert result is not None
        assert result.front == "Was ist ein Automat?"

    def test_returns_none_for_genuinely_absent_card(self, tmp_path):
        """
        SPEC-6e: find_card_by_front must still return None for cards that truly
        don't exist, even with case-insensitive matching.
        """
        db = make_db(tmp_path)
        db.cards = [make_card(front="Was ist ein Automat?")]
        result = db.find_card_by_front("Was ist ein Transistor?")
        assert result is None

    def test_consistency_with_integrate_new_deduplication(self, tmp_path):
        """
        SPEC-6f: If integrate_new rejects a card as a duplicate, find_card_by_front
        must be able to find it. The two methods must use the same lookup key.

        Specifically: add "Was ist ein Automat?" via integrate_new.
        Then try to add "was ist ein automat?" — rejected as duplicate (count=0).
        Then find_card_by_front("was ist ein automat?") must return the card.
        """
        db = make_db(tmp_path)
        db.integrate_new([{"front": "Was ist ein Automat?", "back": "A."}])

        # integrate_new treats this as a duplicate
        count = db.integrate_new([{"front": "was ist ein automat?", "back": "B."}])
        assert count == 0, "Precondition: lowercase variant must be rejected as duplicate"

        # SPEC: find_card_by_front must also find it
        result = db.find_card_by_front("was ist ein automat?")
        assert result is not None, \
            "find_card_by_front must find the card that integrate_new identified as duplicate"
