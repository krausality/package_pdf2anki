"""
This software is licensed under the terms specified in LICENSE,
authored by Martin Krause.

Usage is limited to:
- Students enrolled at accredited institutions
- Individuals with an annual income below 15,000€
- Personal desktop PC automation tasks

For commercial usage, including server deployments, please contact:
martinkrausemedia@gmail.com

Refer to the NOTICE file for dependencies and third-party libraries used.
"""

from .core import cli_invoke

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

import genanki

def convert_text_to_anki(text_file, anki_file):
    # Read text from file
    with open(text_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    # Split text into notes (this can be customized)
    notes = text.strip().split('\n\n')

    # Create Anki deck
    deck = genanki.Deck(
        deck_id=1234567890,
        name='PDF to Anki Deck'
    )

    # Add notes to deck
    for note_text in notes:
        fields = note_text.strip().split('\n', 1)
        if len(fields) == 2:
            front, back = fields
        else:
            front = fields[0]
            back = ''
        note = genanki.Note(
            model=genanki.BASIC_MODEL,
            fields=[front, back]
        )
        deck.add_note(note)

    # Save deck to file
    genanki.Package(deck).write_to_file(anki_file)
    print(f"Saved Anki deck to {anki_file}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python text2anki.py [text_file] [anki_file]")
        sys.exit(1)
    text_file = sys.argv[1]
    anki_file = sys.argv[2]
    convert_text_to_anki(text_file, anki_file)


# if __name__ == "__main__":
#     cli_invoke()