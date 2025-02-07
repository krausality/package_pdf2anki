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

# Load environment variables (e.g., OPENROUTER_API_KEY) from .env if present
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
ANKI_LOG_FILE = "anki_generation.log"


def _post_openrouter_for_anki(model_name: str, text_content: str) -> str:
    """
    Posts a request to OpenRouter to generate context-aware Anki card templates.
    Expected response is a JSON string representing a list of cards (each a dict with 'front' and 'back' keys).
    
    The function logs request and response details to ANKI_LOG_FILE.
    After retrieving the response, the function:
      - Removes any text before the first "{" and after the last "}".
      - Wraps the result in [ ... ] if it does not already begin with a square bracket.
    This ensures that json.loads() will successfully parse the result.
    """
    start_time = datetime.now()
    
    # Prepare the prompt in two content blocks (following the pattern from pic2text.py)
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
                        "Rather make to many cards than to few. "
                        "Use the original language e.g. german. Avoid unnecessary translation to english. Always keep technical terms in their provided language."
                        "Output the result as a JSON list, e.g.: "
                        '[{"front": "Card front text", "back": "Card back text"}, ...]. '
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
        with open(ANKI_LOG_FILE, "a", encoding="utf-8") as lf:
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
    
    with open(ANKI_LOG_FILE, "a", encoding="utf-8") as lf:
        lf.write(
            f"\n[ANKI GENERATION] {start_time.isoformat()} => {end_time.isoformat()} ({duration:.2f}s)\n"
            f"Model: {model_name}\n"
            f"Request: (prompt omitted for brevity)\n"
            f"Response (not truncated): {result_text}\n"
            "-----------------------------------------\n"
        )
    
    return result_text


def _archive_old_logs(output_file: str) -> None:
    """
    Archive old log files into a 'log_archive' folder.
    """
    archive_folder = os.path.join(os.path.dirname(output_file), "log_archive")
    os.makedirs(archive_folder, exist_ok=True)
    for log_file in (ANKI_LOG_FILE,):
        if os.path.exists(log_file):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archived_name = f"{os.path.splitext(log_file)[0]}_{timestamp}.log"
            shutil.move(log_file, os.path.join(archive_folder, archived_name))


def convert_text_to_anki(text_file: str, anki_file: str, model: str) -> None:
    """
    Convert an input text file to a set of context-aware Anki cards using OpenRouter.
    
    The `model` parameter allows you to specify which OpenRouter model to use.
    """
    if not model:
        print("No OpenRouter model specified. Exiting.")
        return
    
    with open(text_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    try:
        # Call OpenRouter to generate card templates
        response_cards = _post_openrouter_for_anki(model, text)
        # Expecting a JSON list of cards
        cards = json.loads(response_cards)
        # Save pre-anki card data as human readable JSON next to the .apkg file
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

    # Get the base file name without the extension
    anki_file_name = os.path.splitext(os.path.basename(anki_file))[0]

    # Create an Anki deck (deck_id can be customized or randomized)
    deck = genanki.Deck(
        deck_id=1234567890,
        name=anki_file_name
    )

    for card in cards:
        try:
            note = genanki.Note(
                model=genanki.BASIC_MODEL,
                fields=[card['front'], card['back']]
            )
            deck.add_note(note)
        except Exception as e:
            print("Error creating note for card:", card, e)
    
    genanki.Package(deck).write_to_file(anki_file)
    print(f"Saved Anki deck to {anki_file}")

    _archive_old_logs(anki_file)


