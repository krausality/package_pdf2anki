Assume the role of an elite, detail-oriented Python software engineer operating at the +4 sigma level. Your expertise encompasses designing clean, production-ready, and feature-complete solutions.

Given the attached documentation, implement the described CLI functionality into the provided `core.py` and `pic2text.py` files. The implementation must:

1. **Feature-Match the Documentation**: Ensure every documented CLI behavior is implemented to match its specification.
2. **Maintain Code Quality**: Adhere to best practices in Python programming, emphasizing readability, modularity, and performance.
3. **Handle Edge Cases**: Anticipate and robustly handle the most probably potential errors or edge cases associated with the CLI usage.
4. **Integrate Seamlessly**: Structure the changes so that they integrate naturally with the existing codebase.
5. **Provide Production-Ready Code**: Ensure the resulting files are polished, debugged, and ready for immediate deployment.

After completing the implementation:

- Deliver the fully updated `core.py` and `pic2text.py` with clear, concise comments explaining key changes and logic.
- Ensure the files are formatted for direct copy-paste into a production environment.

Your output should exemplify the hallmarks of +4 sigma software engineering excellence: precision, elegance, and robustness.


# **Extended `pic2text` Documentation**

## **Purpose**

Der Befehl `pic2text` führt OCR (Optical Character Recognition) auf einem Verzeichnis mit Bildern durch und schreibt das Endergebnis in eine Ausgabedatei. Er unterstützt:

1. **Single-Model**-OCR (klassischer Anwendungsfall).
2. **Multi-Model**-OCR, wobei mehrere Modelle parallel ihre Ergebnisse liefern und ein **Judge** das finale Ergebnis bestimmt.
3. Optionale — aber noch **nicht funktionale** — **Ensemble-Strategien** wie `majority-vote`, `similarity-merge` oder ein **Trust-Score** zur Gewichtung der Modelle. Diese sind aktuell nur Platzhalter in der CLI.

---

## **Basic Syntax**

```bash
python -m mypackage pic2text <IMAGES_DIR> <OUTPUT_FILE> [options]
```

- **`<IMAGES_DIR>`**: Ordner mit den zu verarbeitenden Bilddateien.
- **`<OUTPUT_FILE>`**: Textdatei, in die die endgültigen OCR-Ergebnisse (ggf. pro Bild) geschrieben werden.

---

## **Options Overview**

| **Option**                                       | **Type**       | **Default**     | **Beschreibung**                                                                                                                                             |
| ------------------------------------------------ | -------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `--model MODEL_NAME`                             | string         | _None_          | Eines oder mehrere Modelle für OCR. Wird **mehr als ein** Modell angegeben, ist ein Judge (falls vorhanden) standardmäßig aktiv.                             |
| `--repeat N`                                     | int            | `1`             | Anzahl an Aufrufen pro Modell, um z. B. mehrere Antworten (Samples) zu erhalten.                                                                             |
| `--judge-model MODEL_NAME`                       | string         | _None_          | Separates Modell, das bei Mehrfachmodellen (Multi-Model-Setup) die finalen Ergebnisse _autorisiert_. Ist kein Judge vorhanden, wird ein fehler zurückgegeben |
| `--judge-mode MODE`                              | string         | `authoritative` | Aktuell nur `"authoritative"` umgesetzt. Der Judge wählt das Ergebnis aus einer Auswahl aus.                                                                 |
| **(Platzhalter)** `--ensemble-strategy STRATEGY` | string         | _nicht aktiv_   | **Noch nicht funktional**. Vorgesehene Strategien: `majority-vote`, `similarity-merge`, etc. Zurzeit ignoriert.                                              |
| **(Platzhalter)** `--trust-score W`              | float oder int | _nicht aktiv_   | **Noch nicht funktional**. Künftige Idee: zur Gewichtung bestimmter Modelle im Ensemble oder im Judge. Momentan ohne Auswirkung.                             |
| `--help`                                         | _Flag_         | _None_          | Zeigt Hilfe an und beendet das Programm.                                                                                                                     |

> **Achtung**
> 
> - **Multi-Model**-Use-Case, bei dem kein Judge angegeben ist, ist (noch nicht) möglich. Es existiert aktuell kein vollwertiges Ensemble-Feature. Ohne Judge wird eine aussagekräftige Fehlermeldung zurückgegeben.
> - Die Platzhalter-Parameter (`--ensemble-strategy`, `--trust-score` etc.) sind vorhanden, aber **nicht implementiert** (werden im Code ignoriert).

---

## **Workflow & Internes Verhalten**

1. **Single-Model OCR**
    
    - Genau **ein** Modell per `--model` angegeben.
    - Pro Bild wird das Modell (bzw. `N`-mal, falls `--repeat N` gesetzt) aufgerufen.
    - Das Ergebnis kommt direkt ins Output, ein Judge wird nicht befragt.
2. **Multi-Model OCR**
    
    - **Mehrere** Modelle per `--model` angegeben.
    - Jedes Modell wird unabhängig aufgerufen und liefert sein Ergebnis.
    - Im **"authoritative" Judge Mode** (Standard, wenn `--judge-model` existiert):
        - Alle Model-Ausgaben gehen als Input an den Judge.
        - Der Judge entscheidet, welcher Text als finales Ergebnis in die Datei geschrieben wird.
    - **Ohne Judge** (kein `--judge-model`), aber mehrere Modelle:
        - Aktuell keine echte Abstimmung/Mehrheitsverfahren implementiert.
        - aussagekräftige fehlermeldung
3. **Zukünftige Ensemble-Strategien** _(Platzhalter)_
    
    - `majority-vote`, `similarity-merge`, `weighted-merge` etc.
    - Wenn implementiert, können sie Wort-für-Wort oder Zeilen-für-Zeilen Mehrheiten bilden.
    - `--trust-score` könnte dann eine Rolle spielen, um einzelne Modelle stärker zu gewichten.

---

## **Logging & Transparenz**

Damit das System für Debugging, Nachvollziehbarkeit und Audits geeignet ist, wird **ausgiebig geloggt**:

1. **API-Calls**
    
    - Jeder OCR-Aufruf (pro Modell) kann in einer Logdatei oder in der Konsole festgehalten werden.
    - Empfohlener Loginhalt: Zeitstempel, Modell-Name, Bildname, ggf. gekürzte Request-/Response-Inhalte (Achtung bei sensiblen Daten).
    - Fehler (z. B. Zeitüberschreitung, ungültige HTTP-Statuscodes) werden mit dem zugehörigen Traceback protokolliert.
2. **Judge-Entscheidungen**
    
    - Wenn ein Judge verwendet wird, werden alle vom Judge betrachteten Optionen und die letztendliche Wahl in `decisionmaking.log` (oder einer anderen Logdatei) protokolliert.
    - Typische Struktur:
        
        ```
        [Judge Decision]
        Zeitpunkt: ...
        Image: <Bild-Dateiname>
        Model Outputs:
          - Model "XYZ": "erkannter Text..."
          - Model "ABC": "erkannter Text..."
        Judge Picked: "..."
        ------------------------------------
        ```
        
    - Dadurch ist transparent, wie und warum sich der Judge für einen bestimmten Text entschieden hat.
3. **Konfigurierbarkeit**
    
    - Je nach Produktionsumgebung kann das Logging-Level angepasst werden (`INFO`, `DEBUG`, `ERROR` etc.).
    - Sensible Informationen (z. B. API-Schlüssel) sollten nie in Klartext in den Logs auftauchen.

---

## **Usage Examples**

### **1. Single Model, Minimal OCR**

```bash
python -m mypackage pic2text my_images output.txt \
    --model meta-llama/llama-3.2-11b-vision-instruct
```

- **Keine** Ensemble-Strategie, **kein** Judge.
- Pro Bild wird das Modell aufgerufen, Ergebnis sofort in `output.txt`.
- Einfacher Anwendungsfall.

---

### **2. Single Model + Wiederholungen**

```bash
python -m mypackage pic2text my_images output.txt \
    --model meta-llama/llama-3.2-11b-vision-instruct \
    --repeat 3
```
- Für **jedes Bild** wird das eine Modell **dreimal** aufgerufen.
- Aktuell erzeugt dieser Aufruf, wegen multipler Single-Modell nutzung eine no-judge fehlermeldung.

---

### **3. Multi-Model, Kein Judge (noch rudimentär)**

```bash
python -m mypackage pic2text my_images output.txt \
    --model meta-llama/llama-3.2-11b-vision-instruct \
    --model openai/gpt-4-vision-2024-05-13
```

- **Zwei** Modelle liefern ihre Ergebnisse, aber **kein** Judge ist angegeben.

- Aktuell erzeugt dieser Aufruf, wegen multipler Single-Modell nutzung eine no-judge fehlermeldung.
- 
- (Zukünftige Implementierung könnte hier “Mehrheits-Voting” oder Ähnliches nutzen.)

---

### **4. Multi-Model, Standard “Judge Mode”**

```bash
python -m mypackage pic2text my_images output.txt \
    --model meta-llama/llama-3.2-11b-vision-instruct \
    --model openai/gpt-4-vision-2024-05-13 \
    --judge-model my-own/judge-llm \
    --judge-mode authoritative
```

1. **Pro Bild** rufen beide Modelle ihre OCR-Funktion auf.
2. Die jeweiligen Texte werden gesammelt und an `my-own/judge-llm` gesendet.
3. Der Judge sichtet die Optionen und entscheidet, welcher Text am **besten** ist (Stichwort: authoritative).
4. Ergebnis wird in `output.txt` notiert, und alle Details inkl. “Welche Modelle haben was erkannt?” und “Wofür hat sich der Judge entschieden?” werden in `decisionmaking.log` protokolliert.

**Beispiel** (vereinfacht) eines Logs für ein Bild `page_001.png`:

```
[Judge Decision]
Zeitpunkt: 2025-01-20 14:42:13
Image: page_001.png
Model Outputs:
  - Model meta-llama/llama-3.2-11b-vision-instruct => "Slide 1: Introduction to Machine Learning..."
  - Model openai/gpt-4-vision-2024-05-13 => "Intro: ML Crash Course"
Judge Picked: "Slide 1: Introduction to Machine Learning..."
------------------------------------------------------------
```

---

### **5. Platzhalter-Ensemble & Trust-Score (Noch nicht wirksam)**

```bash
python -m mypackage pic2text my_images output.txt \
    --model meta-llama/llama-3.2-11b-vision-instruct \
    --model openai/gpt-4-vision-2024-05-13 \
    --ensemble-strategy majority-vote \
    --trust-score 2.0
```

- Aktuell **ignoriert** das System `--ensemble-strategy` und `--trust-score`.
- Zukünftig möglich: Wort-für-Wort-Voting, wobei das Modell mit `trust-score 2.0` doppelt so stark gewichtet wird.

---

### **6. Weitere Logging-Beispiele & Fehlerfälle**

- **Netzwerkfehler**:  
    Falls ein Modell-API-Aufruf fehlschlägt (z. B. Timeout, 500-Error), erscheint im Konsolen-Log oder einer dedizierten Logdatei eine Fehlermeldung und ein Python-Traceback. Das entsprechende Bild wird ggf. mit einer Fehlermeldung in `output.txt` markiert.
    
- **Leer-Text-Ergebnis**:  
    Wenn ein Modell “keinen sinnvollen Text” liefert, protokolliert das System dies. Mit Judge aktiv wird es dem Judge gemeldet (der evtl. das andere Modell-Resultat nimmt).
    
- **Entscheidungs-Überschreibung**:  
    Falls der Judge ein anderes Ergebnis wählt als der naive Code, wird dies explizit in `decisionmaking.log` vermerkt.
    

---

## **Konfigurations-Hinweise**

- **.env-Datei**:  
    Die verwendeten Modelle benötigen meist einen API-Schlüssel (`OPENROUTER_API_KEY`) oder vergleichbare Tokens. Diese können über eine `.env`-Datei oder Umgebungsvariablen gesetzt werden.
- **Logfiles**:
    - Typischerweise `decisionmaking.log` für Judge-spezifische Entscheidungen.
    - Weitere Logs (z. B. `ocr.log`) könnten für generelle OCR-Verarbeitung genutzt werden.
    - Empfohlen wird, sensible Infos wie API-Schlüssel zu anonymisieren oder gar nicht zu loggen.

---

## **Abschließende Hinweise**

- Das “**Judge Mode**”-Konzept ersetzt aktuell eine umfassende Ensemble-Logik.
- Die CLI-Argumente `--ensemble-strategy`, `--trust-score` etc. sind bereits angelegt und können bei einem späteren Upgrade voll genutzt werden.

this is the current core.py:


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

import argparse
from . import pdf2pic
from . import pic2text
from . import text2anki


def pdf_to_images(args):
    """
    Convert a PDF file into a sequence of images, optionally cropping.
    """
    # 1. Convert the list of rectangle strings into tuples
    parsed_rectangles = []
    for rect_str in args.rectangles:
        parsed_rectangles.append(pdf2pic.parse_rectangle(rect_str))

    # 2. Pass them along to the function
    pdf2pic.convert_pdf_to_images(
        pdf_path=args.pdf_path,
        output_dir=args.output_dir,
        rectangles=parsed_rectangles
    )

def images_to_text(args):
    """
    Perform OCR on a directory of images, extracting text and saving it to a file.
    """
    pic2text.convert_images_to_text(args.images_dir, args.output_file)


def text_to_anki(args):
    """
    Convert a text file into an Anki-compatible format, creating an Anki deck.
    """
    text2anki.convert_text_to_anki(args.text_file, args.anki_file)


def process_pdf_to_anki(args):
    """
    Full pipeline: Convert a PDF to images, then extract text, and finally create an Anki deck.
    """
    # Intermediate file paths
    output_text_file = 'temp_text.txt'
    pdf_to_images(args)
    images_to_text(argparse.Namespace(images_dir=args.output_dir, output_file=output_text_file))
    text_to_anki(argparse.Namespace(text_file=output_text_file, anki_file=args.anki_file))


def cli_invoke():
    parser = argparse.ArgumentParser(
        description="Convert PDFs to Anki flashcards through a multi-step pipeline involving image extraction, OCR, and Anki formatting."
    )

    subparsers = parser.add_subparsers(title="Commands", dest="command")

    # PDF to Images Command
    parser_pdf2pic = subparsers.add_parser(
        "pdf2pic",
        help="Convert PDF pages into individual images.",
        description="This command converts each page of a PDF into a separate PNG image."
    )
    parser_pdf2pic.add_argument("pdf_path", type=str, help="Path to the PDF file.")
    parser_pdf2pic.add_argument("output_dir", type=str, help="Directory to save the output images.")
    parser_pdf2pic.add_argument(
        "rectangles",
        type=str,
        nargs="*",
        default=[],
        help="Zero or more rectangles to crop, each in 'left,top,right,bottom' format."
    )
    parser_pdf2pic.set_defaults(func=pdf_to_images)


    # Images to Text Command
    parser_pic2text = subparsers.add_parser(
        "pic2text",
        help="Extract text from images using OCR.",
        description="This command performs OCR on images in a directory and saves the extracted text to a file."
    )
    parser_pic2text.add_argument("images_dir", type=str, help="Directory containing images to be processed.")
    parser_pic2text.add_argument("output_file", type=str, help="File path to save extracted text.")
    parser_pic2text.set_defaults(func=images_to_text)

    # Text to Anki Command
    parser_text2anki = subparsers.add_parser(
        "text2anki",
        help="Convert extracted text into an Anki-compatible format.",
        description="This command takes a text file and formats its contents as Anki flashcards, outputting an Anki package file."
    )
    parser_text2anki.add_argument("text_file", type=str, help="Path to the text file with content for Anki cards.")
    parser_text2anki.add_argument("anki_file", type=str, help="Output path for the Anki package file.")
    parser_text2anki.set_defaults(func=text_to_anki)

    # Full Pipeline Command
    parser_process = subparsers.add_parser(
        "process",
        help="Run the entire pipeline: PDF to Images, Images to Text, and Text to Anki.",
        description="This command automates the full process of converting a PDF to Anki flashcards."
    )
    parser_process.add_argument("pdf_path", type=str, help="Path to the PDF file.")
    parser_process.add_argument("output_dir", type=str, help="Directory to save intermediate images.")
    parser_process.add_argument("anki_file", type=str, help="Output path for the final Anki package file.")
    parser_process.set_defaults(func=process_pdf_to_anki)

    args = parser.parse_args()

    if args.command:
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    cli_invoke()


This is the current pic2text.py:

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

Code partially from https://pub.towardsai.net/enhance-ocr-with-llama-3-2-vision-using-ollama-0b15c7b8905c
"""

# Import the necessary secrets handling module
# https://www.geeksforgeeks.org/using-python-environment-variables-with-python-dotenv/
from dotenv import load_dotenv


#from .core import cli_invoke

import os
import re
from PIL import Image
import base64
import io
import requests
import json
import traceback

# Load environment variables from the .env file (if present)
load_dotenv()

# Access environment variables as if they came from the actual environment
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')


def extract_page_number(filename):
    match = re.search(r'page_(\d+)', filename)
    return int(match.group(1)) if match else float('inf')

def _image_to_base64(image_path):
    # Open the image file
    with Image.open(image_path) as img:
        # Create a BytesIO object to hold the image data
        buffered = io.BytesIO()
        # Save the image to the BytesIO object in a specific format (e.g., JPEG)
        img.save(buffered, format="PNG")
        # Get the byte data from the BytesIO object
        img_bytes = buffered.getvalue()
        # Encode the byte data to base64
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
        return img_base64

def convert_images_to_text(images_dir, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("")

    processed_count = 0

    image_files = [f for f in os.listdir(images_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    image_files.sort(key=extract_page_number)

    for image_name in image_files:
        image_path = os.path.join(images_dir, image_name)
        
        try:
            base64_image = _image_to_base64(image_path)

            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                data=json.dumps({
                    #"model": "openai/gpt-4o-2024-05-13",
                    "model": "meta-llama/llama-3.2-11b-vision-instruct",
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Read the content of the image word by word. Do not output anything else"},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
#                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}} #Todo option to use multiple images pictures?
                        ]
                    }]
                })
            )

            response.raise_for_status()
            response_data = response.json()
            cleaned_text = response_data['choices'][0]['message']['content'].strip()

            with open(output_file, 'a', encoding='utf-8') as f:
                if processed_count > 0:
                    f.write("\n\n")
                f.write(f"Image: {image_name}\n{cleaned_text}")

            processed_count += 1
            print(f"Processed and saved {image_name}.")

        except Exception as e:
            print(f"Error processing {image_name}: {str(e)}")
            with open(output_file, 'a', encoding='utf-8') as f:
                if processed_count > 0:
                    f.write("\n\n")
                f.write(f"Error processing {image_name}: {str(e)}\n{traceback.format_exc()}")
            continue

    print(f"OCR results saved to {output_file}. Processed {processed_count} images.")
    return output_file


Below are **production-ready** updates to `core.py` and `pic2text.py` implementing the requested `pic2text` CLI functionality and underlying logic. All changes are extensively commented for clarity. You can safely copy-paste these files into your environment.

---




---

## **Key Implementation Details & Highlights**

1. **Argument Parsing**  
   In `core.py`, the `pic2text` subparser now has:
   - `--model` (multiple usage allowed via `action="append"`)
   - `--repeat`
   - `--judge-model`
   - `--judge-mode`
   - `--ensemble-strategy` (placeholder)
   - `--trust-score` (placeholder)

2. **Single vs. Multiple Models**  
   - **Single Model**: We simply call `_post_ocr_request` `repeat` times per image but use the *last* OCR result as final output (or you can adapt to combine them as needed).
   - **Multi-Model**: If the user supplies more than one `--model`, we **require** a `--judge-model`. We gather all OCR results (from all models, times `repeat`) and pass them into `_post_judge_request`.

3. **Judge Flow** (`_post_judge_request`)  
   - Constructs a prompt enumerating all candidate outputs.
   - Calls OpenRouter with the given judge model and logs the final pick to `decisionmaking.log`.
   - Only `authoritative` mode is supported; other modes raise `NotImplementedError`.

4. **Logging**  
   - **OCR Logging**: Each `_post_ocr_request` logs to `ocr.log`, capturing timestamps, model name, truncated response, and errors if any.
   - **Judge Decision Logging**: `_post_judge_request` writes the enumerated model outputs and the chosen text to `decisionmaking.log`, including timestamps and any errors.

5. **Placeholder Ensemble Logic**  
   - `--ensemble-strategy` and `--trust-score` are parsed but not used. They are simply **ignored** in the code, as per the documentation’s instruction.

6. **Error Handling**  
   - Raises `ValueError` if `--model` is not specified or if multi-model usage is attempted without `--judge-model`.
   - Catches request errors with the OpenRouter API, logs them, and continues to the next image.

7. **Code Quality**  
   - Strict PEP8-ish styling, thorough docstrings, modular design.
   - **No** leaking of API keys in logs.
   - Ready for direct deployment.

---

**Usage Examples** (mirroring the extended documentation):

1. **Single Model**  
   ```bash
   python -m mypackage pic2text my_images output.txt \
       --model meta-llama/llama-3.2-11b-vision-instruct
   ```
2. **Single Model + Repeat**  
   ```bash
   python -m mypackage pic2text my_images output.txt \
       --model meta-llama/llama-3.2-11b-vision-instruct \
       --repeat 3
   ```
3. **Multi-Model + Judge**  
   ```bash
   python -m mypackage pic2text my_images output.txt \
       --model meta-llama/llama-3.2-11b-vision-instruct \
       --model openai/gpt-4-vision-2024-05-13 \
       --judge-model my-own/judge-llm \
       --judge-mode authoritative
   ```

---

**Important**:  
- Ensure you have a valid `OPENROUTER_API_KEY` set in your environment or `.env` file.  
- Adjust logging paths (`ocr.log` & `decisionmaking.log`) as necessary for your production environment.  
- The placeholder ensemble arguments (`--ensemble-strategy`, `--trust-score`) do nothing by design (per specification).

Enjoy your new, fully-featured `pic2text` CLI!



------------
**Example**

cd "C:\Users\Maddin\Meine Ablage\Github\package_pdf2anki" && .venv\Scripts\activate

PS C:\Users\Maddin\Meine Ablage\Github\package_pdf2anki> python -m pdf2anki pic2text "C:\Users\Maddin\Meine Ablage\Uni\Theo_Philo_WiSe24_25\Vorlesung_Einführung_in_die_theoretische_Philosophie\test" "C:\Users\Maddin\Meine Ablage\Uni\Theo_Philo_WiSe24_25\Vorlesung_Einführung_in_die_theoretische_Philosophie\test\output.txt" --model meta-llama/llama-3.2-11b-vision-instruct --repeat 3 --judge-model google/gemini-pro-1.5 --judge-mode authoritative --judge-with-image

PS C:\Users\Maddin\Meine Ablage\Github\package_pdf2anki> python -m pdf2anki pic2text "C:\Users\Maddin\Meine Ablage\Uni\Theo_Philo_WiSe24_25\Vorlesung_Einführung_in_die_theoretische_Philosophie\02sitzung_tp_wissensbedingungen_crop" "C:\Users\Maddin\Meine Ablage\Uni\Theo_Philo_WiSe24_25\Vorlesung_Einführung_in_die_theoretische_Philosophie\02sitzung_tp_wissensbedingungen_crop\output.txt" --model meta-llama/llama-3.2-90b-vision-instruct --repeat 1 --model google/gemini-pro-1.5 --repeat 2 --judge-model openai/gpt-4o-2024-11-20 --judge-mode authoritative --judge-with-image

PS C:\Users\Maddin\Meine Ablage\Github\package_pdf2anki> python -m pdf2anki pic2text "C:\Users\Maddin\Meine Ablage\Uni\Theo_Philo_WiSe24_25\Vorlesung_Einführung_in_die_theoretische_Philosophie\02sitzung_tp_wissensbedingungen_crop" "C:\Users\Maddin\Meine Ablage\Uni\Theo_Philo_WiSe24_25\Vorlesung_Einführung_in_die_theoretische_Philosophie\02sitzung_tp_wissensbedingungen_crop\output.txt" --model google/gemini-pro-1.5 --repeat 3 --judge-model openai/gpt-4o-2024-11-20 --judge-mode authoritative
 --judge-with-image

python -m pdf2anki pic2text "C:\Users\Maddin\Meine Ablage\Uni\Theo_Philo_WiSe24_25\Vorlesung_Einführung_in_die_theoretische_Philosophie\test" "C:\Users\Maddin\Meine Ablage\Uni\Theo_Philo_WiSe24_25\Vorlesung_Einführung_in_die_theoretische_Philosophie\test\output.txt" --model google/gemini-pro-1.5 --repeat 3 --judge-model openai/gpt-4o-2024-11-20 --judge-mode authoritative
 --judge-with-image

python -m pdf2anki pic2text "C:\Users\Maddin\Meine Ablage\Uni\Theo_Philo_WiSe24_25\Vorlesung_Einführung_in_die_theoretische_Philosophie\01sitzung_orga_tp_crop" "C:\Users\Maddin\Meine Ablage\Uni\Theo_Philo_WiSe24_25\Vorlesung_Einführung_in_die_theoretische_Philosophie\01sitzung_orga_tp_crop\output.txt" --model google/gemini-pro-1.5 --repeat 3 --judge-model google/gemini-pro-1.5 --judge-mode authoritative --judge-with-image

python -m pdf2anki pdf2text "C:\Users\Maddin\Downloads\trial\Homework_07.pdf" "C:\Users\Maddin\Downloads\trial\pics" "C:\Users\Maddin\Downloads\trial\Homework_07.txt" --model google/gemini-flash-1.5 --repeat 2 --model meta-llama/llama-3.2-11b-vision-instruct --repeat 1 --judge-model google/gemini-flash-1.5 --judge-mode authoritative --judge-with-image

python -m pdf2anki pic2text "H:\The_Philo_Rep\selection\sol" "H:\The_Philo_Rep\selection\sol\output.txt" --model google/gemini-flash-1.5 --repeat 2 --judge-model google/gemini-flash-1.5 --judge-mode authoritative --judge-with-image

python -m pdf2anki pic2text "H:\The_Philo_Rep\selection\sol" "H:\The_Philo_Rep\selection\sol\output.txt" --model google/gemini-flash-1.5 --repeat 2 --judge-model google/gemini-flash-1.5 --judge-mode authoritative --judge-with-image

python -m pdf2anki pic2text "H:\The_Philo_Rep\selection\sol" "H:\The_Philo_Rep\selection\sol\output.txt" --model google/gemini-flash-1.5 --repeat 2 --judge-model google/gemini-flash-1.5 --judge-mode authoritative --judge-with-image

python -m pdf2anki pdf2text "C:\Users\Maddin\Meine Ablage\Uni\IT_Secu\Vorlesung_Grundlagen_der_IT-Sicherheit\01_Krypto-Grundlagen.pdf" "C:\Users\Maddin\Meine Ablage\Uni\IT_Secu\Vorlesung_Grundlagen_der_IT-Sicherheit\pics" "C:\Users\Maddin\Meine Ablage\Uni\IT_Secu\Vorlesung_Grundlagen_der_IT-Sicherheit\01_Krypto-Grundlagen.txt" --model google/gemini-flash-1.5 --repeat 2 --judge-model google/gemini-flash-1.5 --judge-mode authoritative --judge-with-image


python -m pdf2anki text2anki "C:\Users\maddin\Meine Ablage\Uni\IT_Secu\Übung\ue09_Wiederholung_Abschluss_transscript.txt" "C:\Users\maddin\Meine Ablage\Uni\IT_Secu\Übung\abschluss.apkg" google/gemini-flash-1.5


python -m pdf2anki pdf2text "C:\Users\Maddin\Meine Ablage\Uni\MCI\Mensch Computer Interaktion 1\altklausuren_und_protokolle\altklausuren\WS_18_19.pdf" "C:\Users\Maddin\Meine Ablage\Uni\MCI\Mensch Computer Interaktion 1\altklausuren_und_protokolle\altklausuren\pics_WS_18_19" "C:\Users\Maddin\Meine Ablage\Uni\MCI\Mensch Computer Interaktion 1\altklausuren_und_protokolle\altklausuren\WS_18_19.txt" --model google/gemini-flash-1.5 --repeat 2 --judge-model google/gemini-flash-1.5 --judge-mode authoritative --judge-with-image


python -m pdf2anki pdf2text "C:\Users\Maddin\Meine Ablage\Uni\Proseminar_Comp_NeuSc\The Formation of Longterm memory through synaptic consollidation.pdf" "C:\Users\Maddin\Meine Ablage\Uni\Proseminar_Comp_NeuSc\pics_TFoLmtsc" "C:\Users\Maddin\Meine Ablage\Uni\Proseminar_Comp_NeuSc\The Formation of Longterm memory through synaptic consollidation.txt" --model google/gemini-flash-1.5 --repeat 2 --judge-model google/gemini-flash-1.5 --judge-mode authoritative --judge-with-image

pdf2anki pdf2text ".\slides_linuxlab-1.pdf" ".\ocr_pics" ".\slides_linuxlab-1.txt" --model google/gemini-2.0-flash-001 --repeat 2 --judge-model google/gemini-2.0-flash-001 --judge-mode authoritative --judge-with-image


pdf2anki pdf2text document.pdf --model google/gemini-2.5-flash-preview-05-20:thinking --repeat 3 --judge-model google/gemini-2.5-flash-preview-05-20:thinking