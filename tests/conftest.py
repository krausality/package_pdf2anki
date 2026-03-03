"""Shared fixtures for pdf2anki test suite."""
import json
import os
import pytest
from datetime import datetime
from unittest.mock import MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# Minimal valid project.json data
# ─────────────────────────────────────────────────────────────────────────────

MINIMAL_PROJECT_DATA = {
    "project_name": "TestProjekt",
    "tag_prefix": "TEST",
    "language": "de",
    "domain": "Testwissen",
    "orphan_collection_name": "Unsortierte_Karten",
    "files": {
        "db_path": "card_database.json",
        "markdown_file": "All_fronts.md",
        "new_cards_file": "new_cards_output.json",
        "material_file": "course_material.txt",
    },
    "collections": {
        "collection_0_Kapitel1": {
            "display_name": "Kapitel 1: Grundlagen",
            "filename": "collection_0_Kapitel1.json",
            "description": "Grundlagen",
        },
        "collection_1_Kapitel2": {
            "display_name": "Kapitel 2: Vertiefung",
            "filename": "collection_1_Kapitel2.json",
            "description": "Vertiefung",
        },
    },
    "llm": {"model": "google/gemini-2.5-flash", "temperature": 0.1},
}


@pytest.fixture
def tmp_project_dir(tmp_path):
    """Creates a temp dir with a valid project.json and returns its path."""
    project_json = tmp_path / "project.json"
    project_json.write_text(json.dumps(MINIMAL_PROJECT_DATA), encoding="utf-8")
    return tmp_path


@pytest.fixture
def sample_config(tmp_project_dir):
    """Returns a ProjectConfig loaded from the tmp project dir."""
    from pdf2anki.text2anki.project_config import ProjectConfig
    return ProjectConfig.from_file(str(tmp_project_dir))


@pytest.fixture
def sample_cards():
    """Returns a list of 3 AnkiCard objects."""
    from pdf2anki.text2anki.card import AnkiCard
    return [
        AnkiCard(
            front="Was ist Python?",
            back="Python ist eine Programmiersprache.",
            collection="collection_0_Kapitel1",
            category="a_grundlagen",
            tags=["TEST::Kapitel1"],
        ),
        AnkiCard(
            front="Was ist eine Liste?",
            back="Eine geordnete Sammlung von Elementen.",
            collection="collection_0_Kapitel1",
            category="b_datenstrukturen",
            tags=["TEST::Kapitel1"],
        ),
        AnkiCard(
            front="Was ist Vererbung?",
            back="Ein OOP-Konzept zur Wiederverwendung von Code.",
            collection="collection_1_Kapitel2",
            category="a_oop",
            tags=["TEST::Kapitel2"],
        ),
    ]


def make_mock_api_response(content: str, status_code: int = 200):
    """Returns a MagicMock simulating a successful requests.Response with OCR/LLM content."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    return mock_resp


def make_mock_llm_cards_response(cards):
    """Returns JSON string that mimics a real LLM response for card generation."""
    payload = {"new_cards": cards}
    return json.dumps(payload)
