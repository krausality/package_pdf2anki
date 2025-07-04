"""
This software is licensed under the terms specified in LICENSE.txt,
authored by Martin Krause.

Usage is limited to:
- Students enrolled at accredited institutions
- Individuals with an annual income below 15,000€
- Personal desktop PC automation tasks

For commercial usage, including server deployments, please contact:
martinkrausemedia@gmail.com

Refer to the NOTICE.txt file for dependencies and third-party libraries used.
"""

import os
import sys
import json
import requests
import traceback
import shutil
from datetime import datetime
import genanki
import argparse
from dotenv import load_dotenv
import re

# Load environment variables (e.g., OPENROUTER_API_KEY) from .env if present
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# --- Helpers for unique log filenames and sanitization ---
LOG_EXTENSION = ".log"
DEFAULT_ANKI_LOG_BASENAME = "anki_generation"

def sanitize_filename(filename: str) -> str:
    """
    Replace any character that is not alphanumeric or underscore with an underscore.
    """
    return re.sub(r'\W+', '_', filename)

def get_unique_log_file(output_file: str, base: str = DEFAULT_ANKI_LOG_BASENAME) -> str:
    """
    Create a unique log filename based on the output file's basename,
    the current timestamp, and the process ID.
    """
    output_dir = os.path.dirname(os.path.abspath(output_file))
    file_name = sanitize_filename(os.path.basename(output_file).split(".")[0])
    instance_id = file_name + "_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(os.getpid())
    return os.path.join(output_dir, f"{base}_{instance_id}{LOG_EXTENSION}")

# --- End helper section ---

def _post_openrouter_for_anki(model_name: str, text_content: str, anki_log_file: str) -> str:
    """
    Posts a request to OpenRouter to generate context-aware Anki card templates.
    Expected response is a JSON string representing a list of cards (each a dict with 'front' and 'back' keys).

    This function logs request and response details to the provided log file.
    After retrieving the response, it cleans the text by:
      - Removing any text before the first "{" and after the last "}".
      - Wrapping the result in [ ... ] if it does not already begin with a square bracket.
    """
    start_time = datetime.now()
    
    # Prepare the prompt in two content blocks.
    request_payload = {
        "model": model_name,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "You are an expert education content generator. Analyze the following text and generate a list of Anki cards "
                        "that best help a learner understand the content. Depending on the context, produce cards that either explain key concepts, "
                        "give step-by-step guidance for algorithms, provide mathematical formulas with explanations. "
                        "Be sure to include cover information. "
                        "If you have the choice between more detailed card or multiple cards, prefer the one overview card and multiple detailed cards. "
                        "Rather make too many cards than too few. "
                        "Use the original language e.g. german. Avoid unnecessary translation to english. Always keep technical terms in their provided language. "
                        "Output the result as a JSON list, e.g.: "
                        '[{"front": "Card front text", "back": "Card back text"}, ...]. '
                        "Optionally, you can add the following fields: "
                        "- 'tags': List of categorization tags (e.g., ['category1', 'advanced']) "
                        "- 'guid': Unique identifier for the card (e.g., 'topic-concept-001') "
                        "- 'sort_field': Sort value for organization (e.g., '01_Basics') "
                        "- 'due': Days from today when card should first appear (default: 0) "
                        "All optional fields should be used to enhance organization and learning efficiency. "
                        "Do not include any additional commentary."
                    )
                },
                {
                    "type": "text",
                    "text": f"Content:\n{text_content}"
                }
            ]
        }]
    }
    
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            data=json.dumps(request_payload),
            timeout=60  # 1-minute timeout, adjustable as needed
        )
        response.raise_for_status()
        response_data = response.json()
        result_text = response_data["choices"][0]["message"]["content"].strip()
        
        # Remove any extraneous text before the first "{" and after the last "}"
        first_brace = result_text.find("{")
        last_brace = result_text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            result_text = result_text[first_brace:last_brace+1]
        
        # If the result does not start with '[' then assume it's a list of JSON objects separated by commas.
        # Wrap the result in square brackets so that json.loads() succeeds.
        if not result_text.startswith('['):
            result_text = "[" + result_text + "]"
        
    except Exception as exc:
        with open(anki_log_file, "a", encoding="utf-8") as lf:
            lf.write(
                f"\n[ERROR ANKI GENERATION] {datetime.now().isoformat()}\n"
                f"Model: {model_name}\n"
                f"Exception: {str(exc)}\n"
                f"Traceback:\n{traceback.format_exc()}\n"
                "-----------------------------------------\n"
            )
        raise

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    with open(anki_log_file, "a", encoding="utf-8") as lf:
        lf.write(
            f"\n[ANKI GENERATION] {start_time.isoformat()} => {end_time.isoformat()} ({duration:.2f}s)\n"
            f"Model: {model_name}\n"
            f"Request: (prompt omitted for brevity)\n"
            f"Response (not truncated): {result_text}\n"
            "-----------------------------------------\n"
        )
    
    return result_text


def _archive_old_logs(output_file: str, log_files: list) -> None:
    """
    Archive old log files into a 'log_archive' folder next to the output file.
    Works correctly with unique log filenames.
    """
    archive_folder = os.path.join(os.path.dirname(os.path.abspath(output_file)), "log_archive")
    os.makedirs(archive_folder, exist_ok=True)
    for log_file in log_files:
        if os.path.exists(log_file):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base = os.path.splitext(os.path.basename(log_file))[0]
            archived_name = f"{base}_{timestamp}{LOG_EXTENSION}"
            shutil.move(log_file, os.path.join(archive_folder, archived_name))


def convert_text_to_anki(text_file: str, anki_file: str, model: str) -> None:
    """
    Convert an input text file to a set of context-aware Anki cards using OpenRouter.
    The `model` parameter specifies which OpenRouter model to use.
    
    The generated cards can optionally include tags for categorization.
    The LLM will automatically determine appropriate tags based on the content.
    """
    if not model:
        print("No OpenRouter model specified. Exiting.")
        return
    
    with open(text_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    # Create a unique log file for this instance.
    anki_log_file = get_unique_log_file(anki_file)
    
    try:
        # Call OpenRouter to generate card templates.
        response_cards = _post_openrouter_for_anki(model, text, anki_log_file)
        # Expecting a JSON list of cards.
        cards = json.loads(response_cards)
        # Save pre-Anki card data as human-readable JSON next to the .apkg file.
        json_output_file = os.path.splitext(anki_file)[0] + ".json"
        with open(json_output_file, 'w', encoding="utf-8") as jf:
            json.dump(cards, jf, indent=2, ensure_ascii=False)
        print(f"Saved raw card data to {json_output_file}")

    except Exception as e:
        print("Error generating cards:", e)
        cards = []
    
    if not cards:
        print("No cards generated. Exiting.")
        return

    # Get the base file name without the extension.
    anki_file_name = os.path.splitext(os.path.basename(anki_file))[0]

    # Create an Anki deck (deck_id can be customized or randomized).
    deck = genanki.Deck(
        deck_id=1234567890,
        name=anki_file_name
    )

    for card in cards:
        try:
            # Extract optional fields
            card_tags = card.get('tags', [])
            card_guid = card.get('guid')
            card_sort_field = card.get('sort_field')
            card_due = card.get('due', 0)
            
            note = genanki.Note(
                model=genanki.BASIC_MODEL,
                fields=[card['front'], card['back']],
                tags=card_tags,
                guid=card_guid,
                sort_field=card_sort_field,
                due=card_due
            )
            deck.add_note(note)
        except Exception as e:
            print("Error creating note for card:", card, e)
    
    genanki.Package(deck).write_to_file(anki_file)
    print(f"Saved Anki deck to {anki_file}")

    # Archive the unique log file.
    _archive_old_logs(anki_file, [anki_log_file])

# New: JSON→Anki conversion mode (no LLM)
def convert_json_to_anki(json_file: str, anki_file: str) -> None:
    """
    Convert a JSON file containing flashcards to an Anki deck.
    Each card must be a dict with 'front' and 'back' keys.
    
    Optional fields supported:
    - 'tags': List of tag strings for categorization
    - 'guid': Unique identifier for the note (prevents duplicates on reimport)
    - 'sort_field': Custom sort value for organizing cards in Anki browser
    - 'due': Days from today when card should first appear (default: 0)
    
    Example JSON format:
    [
        {
            "front": "Question", 
            "back": "Answer"
        },
        {
            "front": "Advanced Question",
            "back": "Complex Answer", 
            "tags": ["category1", "advanced"],
            "guid": "unique-id-001",
            "sort_field": "01_Priority",
            "due": 7
        }
    ]
    """
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
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
            # Extract optional fields
            card_tags = card.get('tags', [])
            card_guid = card.get('guid')
            card_sort_field = card.get('sort_field')
            card_due = card.get('due', 0)
            
            note = genanki.Note(
                model=genanki.BASIC_MODEL,
                fields=[card['front'], card['back']],
                tags=card_tags,
                guid=card_guid,
                sort_field=card_sort_field,
                due=card_due
            )
            deck.add_note(note)
        except Exception as e:
            print("Error creating note for card:", card, e)

    genanki.Package(deck).write_to_file(anki_file)
    print(f"Saved Anki deck to {anki_file}")


