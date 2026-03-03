"""Tests for pdf2anki.text2anki.card.AnkiCard (pure dataclass, no mocks needed)."""
import uuid
from datetime import datetime

import pytest

from pdf2anki.text2anki.card import AnkiCard


class TestAnkiCardDefaults:
    def test_guid_is_valid_uuid(self):
        card = AnkiCard(front="Q", back="A")
        uuid.UUID(card.guid)  # raises if invalid

    def test_two_cards_have_different_guids(self):
        c1 = AnkiCard(front="Q1", back="A1")
        c2 = AnkiCard(front="Q2", back="A2")
        assert c1.guid != c2.guid

    def test_default_tags_empty_list(self):
        card = AnkiCard(front="Q", back="A")
        assert card.tags == []

    def test_default_collection_is_none(self):
        card = AnkiCard(front="Q", back="A")
        assert card.collection is None

    def test_timestamps_set_on_creation(self):
        before = datetime.now()
        card = AnkiCard(front="Q", back="A")
        after = datetime.now()
        assert before <= card.created_at <= after
        assert before <= card.updated_at <= after


class TestAnkiCardSerialization:
    def test_to_dict_contains_all_fields(self):
        card = AnkiCard(
            front="Was ist X?",
            back="X ist Y.",
            collection="collection_0_test",
            category="a_basics",
            sort_field="001",
            tags=["TAG1", "TAG2"],
        )
        d = card.to_dict()
        assert d["front"] == "Was ist X?"
        assert d["back"] == "X ist Y."
        assert d["collection"] == "collection_0_test"
        assert d["category"] == "a_basics"
        assert d["sort_field"] == "001"
        assert d["tags"] == ["TAG1", "TAG2"]
        assert "guid" in d
        assert "created_at" in d
        assert "updated_at" in d

    def test_to_dict_datetimes_are_iso_strings(self):
        card = AnkiCard(front="Q", back="A")
        d = card.to_dict()
        # Should not raise
        datetime.fromisoformat(d["created_at"])
        datetime.fromisoformat(d["updated_at"])

    def test_from_dict_roundtrip(self):
        original = AnkiCard(
            front="Test front",
            back="Test back",
            collection="collection_0_k1",
            category="a_cat",
            sort_field="099",
            tags=["X::Y"],
        )
        d = original.to_dict()
        restored = AnkiCard.from_dict(d)

        assert restored.front == original.front
        assert restored.back == original.back
        assert restored.guid == original.guid
        assert restored.collection == original.collection
        assert restored.category == original.category
        assert restored.sort_field == original.sort_field
        assert restored.tags == original.tags

    def test_from_dict_datetime_conversion(self):
        card = AnkiCard(front="Q", back="A")
        d = card.to_dict()
        restored = AnkiCard.from_dict(d)
        assert isinstance(restored.created_at, datetime)
        assert isinstance(restored.updated_at, datetime)

    def test_from_dict_minimal_fields(self):
        """from_dict with only front and back (rest defaults)."""
        data = {
            "front": "Q",
            "back": "A",
            "guid": str(uuid.uuid4()),
            "collection": None,
            "category": None,
            "sort_field": None,
            "tags": [],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        card = AnkiCard.from_dict(data)
        assert card.front == "Q"
        assert card.back == "A"
        assert card.collection is None
