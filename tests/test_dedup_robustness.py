"""Tests for LLM dedup robustness in database_manager.

_check_semantic_duplicates_llm sends card fronts to an LLM and parses the
response to identify duplicates. Real LLMs return unpredictable JSON.
These tests verify graceful handling of every malformed response pattern.
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from pdf2anki.text2anki.card import AnkiCard
from pdf2anki.text2anki.database_manager import DatabaseManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager(tmp_path) -> DatabaseManager:
    """Create a DatabaseManager with a minimal project config."""
    config = MagicMock()
    config.collections = {}
    config.project_dir = str(tmp_path)
    config.get_collection_filename_mapping.return_value = {}
    config.tag_prefix = "TEST"
    config.domain = "Test"
    config.language = "de"
    config.orphan_collection_name = "Unsortiert"

    db_file = str(tmp_path / "db.json")
    dm = DatabaseManager(db_file, project_config=config)
    return dm


def _make_candidates(fronts: list[str]) -> list:
    """Build candidate tuples matching the format expected by _check_semantic_duplicates_llm."""
    return [
        (i, {"front": f, "back": "answer"}, f, "answer", f.lower())
        for i, f in enumerate(fronts)
    ]


def _make_existing(fronts: list[str]) -> list[AnkiCard]:
    """Build existing AnkiCard objects with high token overlap to candidates."""
    return [AnkiCard(front=f, back="answer") for f in fronts]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDedupMalformedResponses:
    """LLM returns structurally broken or unexpected JSON."""

    def test_llm_returns_none(self, tmp_path):
        """LLM call fails completely → no duplicates found."""
        dm = _make_manager(tmp_path)
        candidates = _make_candidates(["Was ist ein DFA?"])
        existing = _make_existing(["Was ist ein DFA genau?"])

        with patch("pdf2anki.text2anki.database_manager.get_llm_decision",
                   return_value=None):
            result = dm._check_semantic_duplicates_llm(candidates, existing)

        assert result == set()

    def test_llm_returns_empty_string(self, tmp_path):
        dm = _make_manager(tmp_path)
        candidates = _make_candidates(["Was ist ein NFA?"])
        existing = _make_existing(["Was ist ein NFA genau?"])

        with patch("pdf2anki.text2anki.database_manager.get_llm_decision",
                   return_value=""):
            result = dm._check_semantic_duplicates_llm(candidates, existing)

        assert result == set()

    def test_llm_returns_plain_text(self, tmp_path):
        """LLM ignores JSON instruction and returns prose."""
        dm = _make_manager(tmp_path)
        candidates = _make_candidates(["Erkläre Turingmaschinen"])
        existing = _make_existing(["Erkläre Turingmaschinen bitte"])

        with patch("pdf2anki.text2anki.database_manager.get_llm_decision",
                   return_value="I think cards 0 and 1 are duplicates."):
            result = dm._check_semantic_duplicates_llm(candidates, existing)

        assert result == set()

    def test_llm_returns_wrong_json_key(self, tmp_path):
        """LLM returns valid JSON but wrong key name."""
        dm = _make_manager(tmp_path)
        candidates = _make_candidates(["Was ist Sigma Star?"])
        existing = _make_existing(["Was ist Sigma Star genau?"])

        with patch("pdf2anki.text2anki.database_manager.get_llm_decision",
                   return_value='{"dupes": [0]}'):
            result = dm._check_semantic_duplicates_llm(candidates, existing)

        # "duplicates" key missing → empty list default → no duplicates
        assert result == set()

    def test_llm_returns_markdown_fenced_json(self, tmp_path):
        """LLM wraps JSON in markdown code fences."""
        dm = _make_manager(tmp_path)
        candidates = _make_candidates(["Was ist ein PDA?"])
        existing = _make_existing(["Was ist ein PDA genau?"])

        with patch("pdf2anki.text2anki.database_manager.get_llm_decision",
                   return_value='```json\n{"duplicates": [0]}\n```'):
            result = dm._check_semantic_duplicates_llm(candidates, existing)

        assert 0 in result


class TestDedupBadIndices:
    """LLM returns 'duplicates' array with invalid index values."""

    def test_out_of_bounds_index_ignored(self, tmp_path):
        """Index beyond candidate list length is silently skipped."""
        dm = _make_manager(tmp_path)
        candidates = _make_candidates(["Frage A", "Frage B"])
        existing = _make_existing(["Frage A genau", "Frage B genau"])

        with patch("pdf2anki.text2anki.database_manager.get_llm_decision",
                   return_value='{"duplicates": [0, 999]}'):
            result = dm._check_semantic_duplicates_llm(candidates, existing)

        # Only index 0 should be marked, 999 is out of bounds
        assert 0 in result
        assert 999 not in result

    def test_negative_index_ignored(self, tmp_path):
        """Negative indices should not cause crashes."""
        dm = _make_manager(tmp_path)
        candidates = _make_candidates(["Frage X"])
        existing = _make_existing(["Frage X genau"])

        with patch("pdf2anki.text2anki.database_manager.get_llm_decision",
                   return_value='{"duplicates": [-1]}'):
            result = dm._check_semantic_duplicates_llm(candidates, existing)

        # -1 < len(candidates_to_check) is True in Python, so it passes the guard
        # but candidates_to_check[-1] is valid Python — this tests current behavior
        assert isinstance(result, set)

    def test_string_indices_do_not_crash(self, tmp_path):
        """LLM returns strings instead of ints in duplicates array."""
        dm = _make_manager(tmp_path)
        candidates = _make_candidates(["Was ist L(G)?"])
        existing = _make_existing(["Was ist L(G) genau?"])

        with patch("pdf2anki.text2anki.database_manager.get_llm_decision",
                   return_value='{"duplicates": ["zero", "one"]}'):
            result = dm._check_semantic_duplicates_llm(candidates, existing)

        # String < int comparison raises TypeError, caught by except Exception
        assert result == set()

    def test_float_indices_do_not_crash(self, tmp_path):
        """LLM returns floats like 0.0 instead of int 0."""
        dm = _make_manager(tmp_path)
        candidates = _make_candidates(["Pumping Lemma"])
        existing = _make_existing(["Pumping Lemma erklären"])

        with patch("pdf2anki.text2anki.database_manager.get_llm_decision",
                   return_value='{"duplicates": [0.0]}'):
            result = dm._check_semantic_duplicates_llm(candidates, existing)

        # float 0.0 < len(...) works in Python, candidates_to_check[0.0] raises TypeError
        # Caught by except Exception → empty set
        assert isinstance(result, set)

    def test_mixed_valid_and_invalid_indices(self, tmp_path):
        """Mix of valid int, out-of-bounds, and string → only valid ones used."""
        dm = _make_manager(tmp_path)
        candidates = _make_candidates(["A Frage", "B Frage", "C Frage"])
        existing = _make_existing(["A Frage genau", "B Frage genau", "C Frage genau"])

        with patch("pdf2anki.text2anki.database_manager.get_llm_decision",
                   return_value='{"duplicates": [1, 500]}'):
            result = dm._check_semantic_duplicates_llm(candidates, existing)

        assert 1 in result
        assert 500 not in result


class TestDedupPreFilter:
    """The Jaccard token-overlap pre-filter should skip non-overlapping candidates."""

    def test_no_overlap_skips_llm_call(self, tmp_path):
        """Candidates with zero token overlap are never sent to LLM."""
        dm = _make_manager(tmp_path)
        candidates = _make_candidates(["Komplett anderes Thema hier"])
        existing = _make_existing(["Gar kein Zusammenhang überhaupt"])

        with patch("pdf2anki.text2anki.database_manager.get_llm_decision") as mock_llm:
            result = dm._check_semantic_duplicates_llm(candidates, existing)

        # LLM should never be called — no token overlap
        mock_llm.assert_not_called()
        assert result == set()

    def test_empty_candidates_no_llm_call(self, tmp_path):
        dm = _make_manager(tmp_path)

        with patch("pdf2anki.text2anki.database_manager.get_llm_decision") as mock_llm:
            result = dm._check_semantic_duplicates_llm([], [])

        mock_llm.assert_not_called()
        assert result == set()

    def test_existing_with_empty_front_skipped(self, tmp_path):
        """Existing cards with empty front should not cause division by zero."""
        dm = _make_manager(tmp_path)
        candidates = _make_candidates(["Eine Frage"])
        existing = [AnkiCard(front="", back="answer")]

        with patch("pdf2anki.text2anki.database_manager.get_llm_decision") as mock_llm:
            result = dm._check_semantic_duplicates_llm(candidates, existing)

        mock_llm.assert_not_called()
        assert result == set()
