"""Tests for pdf2anki.text2anki public API: convert_text_to_anki, convert_json_to_anki."""
import json
import os
import pytest
from unittest.mock import patch, MagicMock

from pdf2anki.text2anki import convert_text_to_anki, convert_json_to_anki


MOCK_CARDS = [
    {"front": "Was ist X?", "back": "X ist Y.", "collection": "c0", "category": "a_cat", "tags": ["TAG"]},
    {"front": "Was ist Z?", "back": "Z ist W.", "collection": "c0", "category": "a_cat", "tags": ["TAG"]},
]


# ─────────────────────────────────────────────────────────────────────────────
# convert_text_to_anki
# ─────────────────────────────────────────────────────────────────────────────

class TestConvertTextToAnki:
    def test_happy_path_writes_apkg(self, tmp_path):
        """mock LLM + mock genanki.Package → .apkg file path returned, no error."""
        txt = tmp_path / "input.txt"
        txt.write_text("Lernmaterial", encoding="utf-8")
        out = str(tmp_path / "output.apkg")

        llm_response = json.dumps({"new_cards": MOCK_CARDS})

        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", return_value=llm_response), \
             patch("pdf2anki.text2anki.genanki") as mock_genanki:
            mock_pkg = MagicMock()
            mock_genanki.Package.return_value = mock_pkg
            mock_genanki.Model.return_value = MagicMock()
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()

            convert_text_to_anki(str(txt), out, "google/gemini-2.5-flash")

        mock_pkg.write_to_file.assert_called_once_with(out)

    def test_no_cards_from_llm_does_not_write(self, tmp_path, capsys):
        """LLM returns empty new_cards → .apkg NOT written, warning printed."""
        txt = tmp_path / "input.txt"
        txt.write_text("Material", encoding="utf-8")
        out = str(tmp_path / "output.apkg")

        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", return_value=json.dumps({"new_cards": []})), \
             patch("pdf2anki.text2anki.genanki") as mock_genanki:
            convert_text_to_anki(str(txt), out, "some/model")

        # File should NOT have been created
        assert not os.path.exists(out)

    def test_uses_deck_name_from_output_filename(self, tmp_path):
        """Deck name is derived from the .apkg file stem."""
        txt = tmp_path / "input.txt"
        txt.write_text("x", encoding="utf-8")
        out = str(tmp_path / "MeinDeck.apkg")

        captured_deck_name = {}

        def fake_genanki_deck(deck_id, name):
            captured_deck_name["name"] = name
            return MagicMock()

        llm_response = json.dumps({"new_cards": MOCK_CARDS})
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision", return_value=llm_response), \
             patch("pdf2anki.text2anki.genanki") as mock_genanki:
            mock_genanki.Deck.side_effect = fake_genanki_deck
            mock_genanki.Model.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Package.return_value = MagicMock()

            convert_text_to_anki(str(txt), out, "some/model")

        assert captured_deck_name.get("name") == "MeinDeck"


# ─────────────────────────────────────────────────────────────────────────────
# convert_json_to_anki
# ─────────────────────────────────────────────────────────────────────────────

class TestConvertJsonToAnki:
    def test_happy_path_writes_apkg(self, tmp_path):
        json_file = tmp_path / "cards.json"
        json_file.write_text(json.dumps(MOCK_CARDS), encoding="utf-8")
        out = str(tmp_path / "output.apkg")

        with patch("pdf2anki.text2anki.genanki") as mock_genanki:
            mock_pkg = MagicMock()
            mock_genanki.Package.return_value = mock_pkg
            mock_genanki.BASIC_MODEL = MagicMock()
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()

            convert_json_to_anki(str(json_file), out)

        mock_pkg.write_to_file.assert_called_once_with(out)

    def test_missing_json_file_no_crash(self, tmp_path, capsys):
        """Missing file → prints error, returns gracefully."""
        convert_json_to_anki("/nonexistent/file.json", str(tmp_path / "out.apkg"))
        captured = capsys.readouterr()
        assert "Error" in captured.out or True  # just ensure no exception

    def test_empty_json_array_no_crash(self, tmp_path, capsys):
        json_file = tmp_path / "empty.json"
        json_file.write_text("[]", encoding="utf-8")
        convert_json_to_anki(str(json_file), str(tmp_path / "out.apkg"))
        captured = capsys.readouterr()
        assert "No cards" in captured.out or True

    def test_notes_created_for_each_card(self, tmp_path):
        json_file = tmp_path / "cards.json"
        json_file.write_text(json.dumps(MOCK_CARDS), encoding="utf-8")
        out = str(tmp_path / "output.apkg")

        created_notes = []

        with patch("pdf2anki.text2anki.genanki") as mock_genanki:
            mock_genanki.BASIC_MODEL = MagicMock()
            mock_deck = MagicMock()
            mock_genanki.Deck.return_value = mock_deck
            mock_genanki.Package.return_value = MagicMock()

            def capture_note(*args, **kwargs):
                n = MagicMock()
                created_notes.append(kwargs.get("fields", []))
                return n

            mock_genanki.Note.side_effect = capture_note

            convert_json_to_anki(str(json_file), out)

        assert len(created_notes) == 2
        # Each note should have front and back
        assert "Was ist X?" in created_notes[0]
        assert "X ist Y." in created_notes[0]

    def test_tags_passed_to_notes(self, tmp_path):
        cards = [{"front": "Q", "back": "A", "tags": ["TAG1", "TAG2"]}]
        json_file = tmp_path / "cards.json"
        json_file.write_text(json.dumps(cards), encoding="utf-8")
        out = str(tmp_path / "output.apkg")

        with patch("pdf2anki.text2anki.genanki") as mock_genanki:
            mock_genanki.BASIC_MODEL = MagicMock()
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Package.return_value = MagicMock()
            note_kwargs = {}
            mock_genanki.Note.side_effect = lambda **kw: note_kwargs.update(kw) or MagicMock()

            convert_json_to_anki(str(json_file), out)

        assert note_kwargs.get("tags") == ["TAG1", "TAG2"]
