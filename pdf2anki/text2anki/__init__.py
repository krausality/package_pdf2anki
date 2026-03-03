"""
pdf2anki.text2anki — SSOT-based Anki card generation from text.

Public interface (backward compatible with core.py):
    convert_text_to_anki(text_file, anki_file, model)
    convert_json_to_anki(json_file, anki_file)

Full project workflow:
    from pdf2anki.text2anki.workflow_manager import WorkflowManager
    from pdf2anki.text2anki.project_config import ProjectConfig
"""

import hashlib
import json
import os
from pathlib import Path

import genanki


# ─────────────────────────────────────────────────────────────────────────────
# convert_text_to_anki — backward compat entry point for core.py
# Replaces the old monolithic text2anki.py implementation.
# ─────────────────────────────────────────────────────────────────────────────

def convert_text_to_anki(text_file: str, anki_file: str, model: str) -> None:
    """
    One-shot: reads a text file, generates Anki cards via LLM, writes .apkg.

    Args:
        text_file: Path to the input .txt file.
        anki_file: Path for the output .apkg file.
        model:     OpenRouter model name (e.g. 'google/gemini-2.5-flash').
    """
    from .text_ingester import TextFileIngestor
    from .project_config import ProjectConfig

    deck_name = Path(anki_file).stem
    tag = deck_name.upper()[:20].replace(' ', '_').replace('-', '_')
    collection_key = f"collection_0_{deck_name.lower().replace(' ', '_').replace('-', '_')[:40]}"
    out_dir = str(Path(anki_file).resolve().parent)

    # Minimal in-memory ProjectConfig — no project.json file needed
    config = ProjectConfig(out_dir, {
        "project_name": deck_name,
        "tag_prefix": tag,
        "language": "de",
        "domain": "Allgemeines Wissen",
        "orphan_collection_name": "Unsortierte_Karten",
        "files": {},
        "collections": {
            collection_key: {
                "display_name": deck_name,
                "filename": f"{collection_key}.json",
                "description": "",
            }
        },
        "llm": {"model": model, "temperature": 0.1},
    })

    ingestor = TextFileIngestor()
    result = ingestor.ingest([text_file], config)
    cards_data = result.get("new_cards", [])

    if not cards_data:
        print("[WARN] text2anki: LLM returned no cards.")
        return

    # Build stable deck/model IDs via hash
    h = hashlib.md5(deck_name.encode()).hexdigest()
    deck_id = int(h[:8], 16) % (2 ** 31)
    model_id = int(h[8:16], 16) % (2 ** 31)

    anki_model = genanki.Model(
        model_id,
        f"{deck_name} Basic",
        fields=[{"name": "Front"}, {"name": "Back"}],
        templates=[{
            "name": "Card 1",
            "qfmt": "{{Front}}",
            "afmt": "{{FrontSide}}<hr id=\"answer\">{{Back}}",
        }],
    )
    deck = genanki.Deck(deck_id, deck_name)
    for card in cards_data:
        note = genanki.Note(
            model=anki_model,
            fields=[card.get("front", ""), card.get("back", "")],
            tags=card.get("tags", []),
        )
        deck.add_note(note)

    genanki.Package(deck).write_to_file(anki_file)
    print(f"[OK] text2anki: {anki_file} ({len(cards_data)} Karten)")


# ─────────────────────────────────────────────────────────────────────────────
# convert_json_to_anki — backward compat, unchanged from original
# ─────────────────────────────────────────────────────────────────────────────

def convert_json_to_anki(json_file: str, anki_file: str) -> None:
    """
    Convert a JSON file containing flashcards to an Anki deck (no LLM).

    Each card must have 'front' and 'back'. Optional: tags, guid, sort_field, due.
    """
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            cards = json.load(f)
    except Exception as e:
        print(f"Error reading JSON file '{json_file}': {e}")
        return

    if not cards:
        print("No cards found in JSON. Exiting.")
        return

    deck_name = os.path.splitext(os.path.basename(anki_file))[0]
    deck = genanki.Deck(deck_id=1234567890, name=deck_name)

    for card in cards:
        try:
            note = genanki.Note(
                model=genanki.BASIC_MODEL,
                fields=[card["front"], card["back"]],
                tags=card.get("tags", []),
                guid=card.get("guid"),
                sort_field=card.get("sort_field"),
                due=card.get("due", 0),
            )
            deck.add_note(note)
        except Exception as e:
            print("Error creating note for card:", card, e)

    genanki.Package(deck).write_to_file(anki_file)
    print(f"Saved Anki deck to {anki_file}")
