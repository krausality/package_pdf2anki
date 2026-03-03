"""Tests for pdf2anki.text2anki.apkg_exporter.ApkgExporter."""
import os
import pytest
from unittest.mock import patch, MagicMock

from pdf2anki.text2anki.card import AnkiCard
from pdf2anki.text2anki.apkg_exporter import ApkgExporter, export_to_apkg


def make_card(front, back, collection, **kwargs):
    return AnkiCard(front=front, back=back, collection=collection, **kwargs)


class TestApkgExporterExport:
    def test_creates_one_apkg_per_collection(self, tmp_path, sample_config, sample_cards):
        """export() calls genanki.Package.write_to_file once per collection."""
        exporter = ApkgExporter()
        with patch("pdf2anki.text2anki.apkg_exporter.genanki") as mock_genanki:
            mock_package = MagicMock()
            mock_genanki.Package.return_value = mock_package
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Model.return_value = MagicMock()

            generated = exporter.export(sample_cards, sample_config, str(tmp_path))

        # 2 collections → 2 files
        assert len(generated) == 2
        assert mock_package.write_to_file.call_count == 2

    def test_returns_correct_file_paths(self, tmp_path, sample_config, sample_cards):
        exporter = ApkgExporter()
        with patch("pdf2anki.text2anki.apkg_exporter.genanki") as mock_genanki:
            mock_package = MagicMock()
            mock_genanki.Package.return_value = mock_package
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Model.return_value = MagicMock()

            generated = exporter.export(sample_cards, sample_config, str(tmp_path))

        for path in generated:
            assert path.endswith(".apkg")
            assert str(tmp_path) in path

    def test_empty_cards_returns_empty_list(self, tmp_path, sample_config):
        exporter = ApkgExporter()
        with patch("pdf2anki.text2anki.apkg_exporter.genanki"):
            generated = exporter.export([], sample_config, str(tmp_path))
        assert generated == []

    def test_cards_without_collection_grouped_as_unsorted(self, tmp_path, sample_config):
        """Cards with collection=None go into a fallback group."""
        cards = [make_card(front="Q", back="A", collection=None)]
        exporter = ApkgExporter()
        with patch("pdf2anki.text2anki.apkg_exporter.genanki") as mock_genanki:
            mock_genanki.Package.return_value = MagicMock()
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Model.return_value = MagicMock()
            generated = exporter.export(cards, sample_config, str(tmp_path))
        # Should produce exactly 1 file for the unsorted group
        assert len(generated) == 1


class TestStableId:
    def test_deterministic(self):
        exporter = ApkgExporter()
        id1 = exporter._stable_id("deck_test", "MyProject")
        id2 = exporter._stable_id("deck_test", "MyProject")
        assert id1 == id2

    def test_different_keys_give_different_ids(self):
        exporter = ApkgExporter()
        id1 = exporter._stable_id("deck_a", "MyProject")
        id2 = exporter._stable_id("deck_b", "MyProject")
        assert id1 != id2

    def test_different_projects_give_different_ids(self):
        exporter = ApkgExporter()
        id1 = exporter._stable_id("deck_test", "ProjectA")
        id2 = exporter._stable_id("deck_test", "ProjectB")
        assert id1 != id2

    def test_result_is_positive_int(self):
        exporter = ApkgExporter()
        result = exporter._stable_id("deck_test", "Proj")
        assert isinstance(result, int)
        assert result >= 0


class TestCreateModel:
    def test_returns_genanki_model(self, sample_config):
        import genanki
        exporter = ApkgExporter()
        model = exporter._create_model(sample_config.project_name, "collection_0_K1")
        assert isinstance(model, genanki.Model)

    def test_model_has_correct_fields(self, sample_config):
        exporter = ApkgExporter()
        model = exporter._create_model(sample_config.project_name, "collection_0_K1")
        field_names = [f["name"] for f in model.fields]
        assert "Front" in field_names
        assert "Back" in field_names
        assert "SortField" in field_names


class TestGroupByCollection:
    def test_groups_correctly(self):
        exporter = ApkgExporter()
        cards = [
            make_card("Q1", "A1", "col_A"),
            make_card("Q2", "A2", "col_A"),
            make_card("Q3", "A3", "col_B"),
        ]
        groups = exporter._group_by_collection(cards)
        assert len(groups["col_A"]) == 2
        assert len(groups["col_B"]) == 1

    def test_none_collection_uses_fallback_key(self):
        exporter = ApkgExporter()
        cards = [make_card("Q", "A", None)]
        groups = exporter._group_by_collection(cards)
        assert len(groups) == 1
        key = list(groups.keys())[0]
        assert "unsorted" in key.lower() or key.startswith("collection_")


class TestExportToApkgWrapper:
    def test_delegates_to_exporter(self, tmp_path, sample_config, sample_cards):
        mock_db = MagicMock()
        mock_db.cards = sample_cards

        with patch("pdf2anki.text2anki.apkg_exporter.genanki") as mock_genanki:
            mock_genanki.Package.return_value = MagicMock()
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Model.return_value = MagicMock()

            generated = export_to_apkg(mock_db, sample_config, str(tmp_path))

        assert isinstance(generated, list)
        assert len(generated) == 2
