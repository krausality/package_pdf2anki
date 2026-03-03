"""Tests for pdf2anki.text2anki.database_manager.DatabaseManager."""
import json
import os
import pytest
from unittest.mock import MagicMock, patch

from pdf2anki.text2anki.card import AnkiCard
from pdf2anki.text2anki.database_manager import DatabaseManager


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_db(tmp_path, cards=None, config=None):
    """Create a DatabaseManager pointing at a tmp dir, optionally pre-seeded."""
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


def make_card(**kwargs):
    defaults = dict(front="Q", back="A", collection="collection_0_K1", category="a_cat")
    defaults.update(kwargs)
    return AnkiCard(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# load_database
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadDatabase:
    def test_loads_cards_from_valid_json(self, tmp_path):
        card = make_card(front="Q1", back="A1")
        db = make_db(tmp_path, cards=[card])
        assert len(db.cards) == 1
        assert db.cards[0].front == "Q1"

    def test_empty_when_no_file(self, tmp_path):
        db = make_db(tmp_path)
        assert db.cards == []

    def test_empty_on_corrupt_json(self, tmp_path):
        db_path = tmp_path / "card_database.json"
        db_path.write_text("INVALID_JSON", encoding="utf-8")
        mock_mm = MagicMock()
        mock_mm.get_course_material.return_value = None
        db = DatabaseManager(
            db_path=str(db_path),
            material_manager=mock_mm,
        )
        assert db.cards == []

    def test_multiple_cards_loaded(self, tmp_path):
        cards = [make_card(front=f"Q{i}", back=f"A{i}") for i in range(5)]
        db = make_db(tmp_path, cards=cards)
        assert len(db.cards) == 5


# ─────────────────────────────────────────────────────────────────────────────
# save_database
# ─────────────────────────────────────────────────────────────────────────────

class TestSaveDatabase:
    def test_saves_cards_to_file(self, tmp_path):
        db = make_db(tmp_path)
        db.cards = [make_card(front="SavedQ", back="SavedA")]
        result = db.save_database()
        assert result is True
        with open(db.db_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data[0]["front"] == "SavedQ"

    def test_roundtrip_preserves_fields(self, tmp_path):
        card = make_card(front="Test", back="Antwort", tags=["TAG1"])
        db = make_db(tmp_path)
        db.cards = [card]
        db.save_database()

        # Reload
        db2 = make_db(tmp_path, cards=None)
        # Manually load to avoid double-init skip
        db2.cards = []
        db2.load_database()
        assert db2.cards[0].tags == ["TAG1"]


# ─────────────────────────────────────────────────────────────────────────────
# find_card_by_front
# ─────────────────────────────────────────────────────────────────────────────

class TestFindCardByFront:
    def test_finds_existing_card(self, tmp_path):
        card = make_card(front="Target question")
        db = make_db(tmp_path, cards=[card])
        found = db.find_card_by_front("Target question")
        assert found is not None
        assert found.front == "Target question"

    def test_returns_none_when_not_found(self, tmp_path):
        db = make_db(tmp_path, cards=[make_card(front="Other")])
        assert db.find_card_by_front("Nonexistent") is None

    def test_empty_db_returns_none(self, tmp_path):
        db = make_db(tmp_path)
        assert db.find_card_by_front("Q") is None


# ─────────────────────────────────────────────────────────────────────────────
# integrate_new
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegrateNew:
    def test_adds_new_cards(self, tmp_path):
        db = make_db(tmp_path)
        new_cards = [
            {"front": "Neue Frage 1", "back": "Antwort 1", "collection": "collection_0_K1", "category": "a_cat"},
            {"front": "Neue Frage 2", "back": "Antwort 2", "collection": "collection_0_K1", "category": "a_cat"},
        ]
        count = db.integrate_new(new_cards)
        assert count == 2
        assert len(db.cards) == 2

    def test_returns_count_of_added(self, tmp_path):
        db = make_db(tmp_path, cards=[make_card(front="Existing")])
        initial = len(db.cards)
        new = [{"front": "New Q", "back": "New A", "collection": "collection_0_K1", "category": "a_cat"}]
        count = db.integrate_new(new)
        assert count == 1
        assert len(db.cards) == initial + 1

    def test_empty_list_adds_nothing(self, tmp_path):
        db = make_db(tmp_path, cards=[make_card()])
        count = db.integrate_new([])
        assert count == 0
        assert len(db.cards) == 1


# ─────────────────────────────────────────────────────────────────────────────
# bootstrap_from_legacy
# ─────────────────────────────────────────────────────────────────────────────

class TestBootstrapFromLegacy:
    def _make_collection_file(self, tmp_path, name, cards):
        """Write a legacy collection JSON file."""
        p = tmp_path / name
        p.write_text(json.dumps(cards), encoding="utf-8")
        return str(p)

    def _make_markdown_file(self, tmp_path, content):
        """Write a minimal All_fronts.md."""
        p = tmp_path / "All_fronts.md"
        p.write_text(content, encoding="utf-8")
        return str(p)

    def _make_ssot_markdown(self, fronts, collection_id=0, collection_name="Kapitel1", category_letter="A", category_name="Grundlagen"):
        """
        Build a valid SSOT markdown using the <!-- COLLECTION_N_START/END --> format
        that _parse_markdown_structure() expects.
        """
        cards_lines = "\n".join(f"{i+1}. {front}" for i, front in enumerate(fronts))
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

    def test_bootstrap_from_simple_data(self, tmp_path):
        """Bootstrap populates cards from matching collection + markdown."""
        coll_file = self._make_collection_file(
            tmp_path,
            "collection_0_K1.json",
            [{"front": "Was ist Python?", "back": "Eine Sprache."}],
        )
        md_content = self._make_ssot_markdown(["Was ist Python?"])
        md_file = self._make_markdown_file(tmp_path, md_content)

        db = make_db(tmp_path)
        result = db.bootstrap_from_legacy(
            collection_files=[coll_file],
            markdown_file=md_file,
            auto_skip_conflicts=True,
            auto_rescue_orphans=True,
            auto_create_missing=True,
        )
        assert result is True
        assert len(db.cards) >= 1

    def test_bootstrap_returns_false_with_empty_sources(self, tmp_path):
        """Bootstrap should fail gracefully when no data is found."""
        # Empty collection file
        coll_file = self._make_collection_file(tmp_path, "empty_coll.json", [])
        # Blank markdown
        md_file = self._make_markdown_file(tmp_path, "")

        db = make_db(tmp_path)
        result = db.bootstrap_from_legacy(
            collection_files=[coll_file],
            markdown_file=md_file,
        )
        assert result is False

    def test_bootstrap_auto_rescue_orphans(self, tmp_path):
        """Orphan cards (in collection but not in markdown) get rescued."""
        coll_file = self._make_collection_file(
            tmp_path,
            "collection_0_K1.json",
            [{"front": "Orphan Frage", "back": "Orphan Antwort"}],
        )
        # Markdown has no matching entries (empty CARDS area)
        md_content = (
            "<!-- COLLECTION_0_START -->\n"
            "# Sammlung 0\n**Kapitel1**\n"
            "<!-- CARDS_START -->\n<!-- CARDS_END -->\n"
            "<!-- COLLECTION_0_END -->\n"
        )
        md_file = self._make_markdown_file(tmp_path, md_content)

        db = make_db(tmp_path)
        result = db.bootstrap_from_legacy(
            collection_files=[coll_file],
            markdown_file=md_file,
            auto_rescue_orphans=True,
        )
        assert result is True
        # Orphan should be rescued into a new collection
        fronts = [c.front for c in db.cards]
        assert "Orphan Frage" in fronts

    def test_bootstrap_auto_ignore_orphans(self, tmp_path):
        """Orphan cards get ignored when auto_ignore_orphans=True."""
        coll_file = self._make_collection_file(
            tmp_path,
            "collection_0_K1.json",
            [{"front": "Orphan X", "back": "Antwort X"}],
        )
        md_content = (
            "<!-- COLLECTION_0_START -->\n"
            "# Sammlung 0\n**Kapitel1**\n"
            "<!-- CARDS_START -->\n<!-- CARDS_END -->\n"
            "<!-- COLLECTION_0_END -->\n"
        )
        md_file = self._make_markdown_file(tmp_path, md_content)

        db = make_db(tmp_path)
        result = db.bootstrap_from_legacy(
            collection_files=[coll_file],
            markdown_file=md_file,
            auto_ignore_orphans=True,
        )
        assert result is True
        # Card should NOT be in the DB (was ignored)
        fronts = [c.front for c in db.cards]
        assert "Orphan X" not in fronts

    def test_bootstrap_auto_create_missing(self, tmp_path):
        """Missing cards (in markdown but not in collection) get TODO backs."""
        coll_file = self._make_collection_file(tmp_path, "collection_0_K1.json", [])
        md_content = self._make_ssot_markdown(["Was fehlt hier?"])
        md_file = self._make_markdown_file(tmp_path, md_content)

        db = make_db(tmp_path)
        result = db.bootstrap_from_legacy(
            collection_files=[coll_file],
            markdown_file=md_file,
            auto_create_missing=True,
        )
        assert result is True
        backs = [c.back for c in db.cards]
        assert any("TODO" in b for b in backs)


# ─────────────────────────────────────────────────────────────────────────────
# distribute_to_derived_files
# ─────────────────────────────────────────────────────────────────────────────

class TestDistributeToDerivedFiles:
    def test_creates_collection_json_files(self, tmp_path, sample_config):
        db = make_db(tmp_path, config=sample_config)
        db.cards = [
            make_card(front="Q1", back="A1", collection="collection_0_Kapitel1", sort_field="001"),
            make_card(front="Q2", back="A2", collection="collection_1_Kapitel2", sort_field="001"),
        ]
        result = db.distribute_to_derived_files(str(tmp_path))
        assert result is True
        assert (tmp_path / "collection_0_Kapitel1.json").exists()
        assert (tmp_path / "collection_1_Kapitel2.json").exists()

    def test_collection_json_content(self, tmp_path, sample_config):
        db = make_db(tmp_path, config=sample_config)
        db.cards = [make_card(front="Q", back="A", collection="collection_0_Kapitel1", sort_field="001")]
        db.distribute_to_derived_files(str(tmp_path))
        with open(tmp_path / "collection_0_Kapitel1.json", encoding="utf-8") as f:
            data = json.load(f)
        assert any(card["front"] == "Q" for card in data)
