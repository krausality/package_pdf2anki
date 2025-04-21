## General Notes & License Summary

- **License & Usage Restrictions**  
  This software is licensed under the terms specified in `LICENSE.txt`, authored by Martin Krause.  
  **Usage is limited** to:
  1. Students enrolled at accredited institutions
  2. Individuals with an annual income below 15,000€
  3. **Personal desktop PC** automation tasks only  

  For commercial usage (including any server-based deployments), please contact the author at:  
  martinkrausemediaATgmail.com

  Refer to the `NOTICE.txt` file for details on dependencies and third-party libraries.

- **CLI Overview**  
  The script is invoked through a single binary/entry-point (e.g., `python -m pdf2anki` or however you’ve packaged it), followed by a **command**. Each command has its own set of parameters and optional flags. 

  The main commands are:
  1. **pdf2pic** – Convert a PDF to individual images.
  2. **pic2text** – Perform OCR (text extraction) from a set of images.
  3. **pdf2text** – Single-step pipeline to go from PDF directly to text.
  4. **text2anki** – Convert a text file into an Anki deck/package.
  5. **process** – Full pipeline: PDF → images → text → Anki deck, in one go.

**Installation / Invocation**  

*---*

## 🛠️ Development Mode (Editable Installs)

If you plan to **develop or modify this project locally**, it's recommended to use an **editable install**. This allows Python to load the package **directly from your source directory**, so any code changes are reflected immediately — no need to reinstall after every edit.

### Setup

```bash
cd pdf2anki
python -m venv .venv
source .venv/bin/activate      # or .venv\Scripts\activate on Windows
pip install --editable .
```

Once installed, you can run the tool in either of the following ways:

### ✅ Option 1: Module Invocation
```bash
python -m pdf2anki COMMAND ...
```
- Runs the package via the Python module system.
- Always works inside an activated virtual environment.

### ✅ Option 2: Executable Invocation
```bash
pdf2anki COMMAND ...
```
- A **console script entry point** is automatically created during install.
- On Windows: creates `pdf2anki.exe` in `.venv\Scripts\`
- On macOS/Linux: creates `pdf2anki` in `.venv/bin/`

💡 **Pro tip**: Check where the executable lives with:
```bash
where pdf2anki     # on Windows
which pdf2anki     # on macOS/Linux
```

If the command isn’t found, make sure your virtual environment is activated and your PATH is correctly set.

---

### Optional: Strict Editable Mode

If you want more control over which files are actually included in the package (e.g. to detect missing modules or simulate a release install), enable **strict mode**:

```bash
pip install -e . --config-settings editable_mode=strict
```

In this mode:
- **New files won’t be exposed automatically** — you’ll need to reinstall to pick them up.
- The install behaves more like a production wheel, which is useful for debugging packaging issues.

---

### Notes
- Code edits are reflected **immediately** in both normal and strict modes.
- Any changes to **dependencies**, **entry-points**, or **project metadata** require reinstallation.
- If you encounter import issues (especially with namespace packages), consider switching to a `src/`-based layout.  
  See the Python Packaging Authority’s recommendations for [modern package structures](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/).

---

You might call this script like:
```bash
python -m pdf2anki COMMAND [OPTIONS...]
```
or if installed as an executable:
```bash
pdf2anki COMMAND [OPTIONS...]
```
In the examples below, we will assume `python -m pdf2anki` is your entry-point.

---

## API Key Configuration

To utilize features that interact with external language models (like the OCR capabilities in `pic2text` and `pdf2text`, or card generation in `text2anki`), you need to provide an API key. The project is configured to work with models available via **OpenRouter.ai**.

The required API key is expected to be set as an environment variable named `OPENROUTER_API_KEY`.

There are two primary ways to make this key available to the script:

1.  **Using a `.env` file (Recommended):**
    *   Create a file named `.env` in the root directory of the project (where `README.md` is).
    *   Add your API key to this file in the format:
        ```dotenv
        OPENROUTER_API_KEY=YOUR_ACTUAL_API_KEY_HERE
        ```
    *   Replace `YOUR_ACTUAL_API_KEY_HERE` with the key you obtained from OpenRouter.ai.
    *   Ensure `.env` is listed in your `.gitignore` file (it should be by default) to prevent accidentally committing your key.

2.  **Setting the Environment Variable directly:**
    *   Set the `OPENROUTER_API_KEY` environment variable in your terminal session *before* running the `pdf2anki` command.
    *   Example (Linux/macOS):
        ```bash
        export OPENROUTER_API_KEY=YOUR_ACTUAL_API_KEY_HERE
        python -m pdf2anki ...
        ```
    *   Example (Windows Command Prompt):
        ```cmd
        set OPENROUTER_API_KEY=YOUR_ACTUAL_API_KEY_HERE
        python -m pdf2anki ...
        ```
    *   Example (Windows PowerShell):
        ```powershell
        $env:OPENROUTER_API_KEY="YOUR_ACTUAL_API_KEY_HERE"
        python -m pdf2anki ...
        ```

Using the `.env` file is generally more convenient for repeated use during development.

---

## 1. `pdf2pic` Command

**Purpose**  
Converts all pages of a PDF into separate image files. By default, it saves each page as a PNG image in the specified output directory.

**Positional Arguments**  
1. `pdf_path` – Path to the input PDF file.  
2. `output_dir` – Directory where resulting images will be stored.  
3. `rectangles` – Zero or more crop rectangles in the format `left,top,right,bottom`.  
   - If one or more rectangles are given, **each page** of the PDF will be cropped according to those rectangles before saving to an image. Multiple rectangles can be provided to produce multiple cropped images per page.

**Usage**  
```bash
python -m pdf2anki pdf2pic PDF_PATH OUTPUT_DIR [RECTANGLE1 RECTANGLE2 ...]
```

### Examples

1. **Minimal usage (no cropping)**

   ```bash
   python -m pdf2anki pdf2pic mydocument.pdf output_images
   ```
   - Converts each page of `mydocument.pdf` into `output_images/page-1.png`, `output_images/page-2.png`, etc.

2. **Single rectangle**  
   ```bash
   python -m pdf2anki pdf2pic mydocument.pdf output_images 100,150,500,600
   ```
   - Converts each page into a cropped version from `(left=100, top=150)` to `(right=500, bottom=600)`.

3. **Multiple rectangles**  
   ```bash
   python -m pdf2anki pdf2pic mydocument.pdf output_images 50,100,300,400 320,100,600,400
   ```
   - For each PDF page, produces **two** cropped images:
     1. Cropped to `left=50, top=100, right=300, bottom=400`
     2. Cropped to `left=320, top=100, right=600, bottom=400`
   - Files will typically be named like `page-1-rect0.png`, `page-1-rect1.png`, etc.

---

## 2. `pic2text` Command

**Purpose**  
Performs OCR on a directory of images, generating extracted text. The text can be from **one or multiple** OCR models. You can optionally specify a “judge” model to pick the best output among multiple OCR results per image. Results are saved to a single text file.

**Positional Arguments**  
1. `images_dir` – Directory containing images (e.g., PNG/JPEG files).
2. `output_file` – Path to the final text file where OCR results will be written.

**Optional Arguments**  

| Parameter            | Description                                                                                                                                           |
|----------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| `--model MODEL`      | Name of an OCR model to use. Can be used **multiple times** to specify multiple models. If omitted, a default model might be assumed (depends on your code).  |
| `--repeat N`         | Number of times to call each model per image (defaults to 1). If you provide multiple `--model` entries and multiple `--repeat` entries, each repeats entry corresponds to its respective model. **Requires `--judge-model` if any N > 1.** |
| `--judge-model JM`   | If you have **multiple** OCR models or use `--repeat > 1`, you **must** specify a judge model to pick the best text. E.g., `--judge-model big-ocr-13b`. |
| `--judge-mode MODE`  | Judge strategy. Currently only `"authoritative"` is implemented. If set, the judge simply picks the best result (the logic is inside your code).                                           |
| `--ensemble-strategy STR` | **(Placeholder)** e.g., `majority-vote`, `similarity-merge`. Not active in the code yet, so setting it won't do anything.                                                              |
| `--trust-score VAL`  | **(Placeholder)** float representing model weighting factor in an ensemble or judge scenario. Not active in the code yet.                                                                  |
| `--judge-with-image` | Boolean flag; if set, the judge model also sees the base64-encoded image when deciding among multiple OCR outputs.                                                                          |

**Usage**  
```bash
python -m pdf2anki pic2text IMAGES_DIR OUTPUT_FILE [--model MODEL...] [--repeat N...] 
      [--judge-model JM] [--judge-mode authoritative]
      [--ensemble-strategy STR] [--trust-score VAL] [--judge-with-image]
```

### Examples

1. **Single model, minimal usage**  
   ```bash
   python -m pdf2anki pic2text scanned_pages output.txt
   ```
   - OCR is done on images in `scanned_pages/` with a default or built-in model, saves text to `output.txt`. (Assumes default model doesn't require a judge).

2. **Single model, repeated calls (Requires Judge)**  
   ```bash
   python -m pdf2anki pic2text scanned_pages output.txt --model google/gemini-2.0-flash-001 --repeat 3 --judge-model some-judge-model
   ```
   - For each image, runs `google/gemini-2.0-flash-001` OCR **3 times**.  
   - **Requires** `--judge-model` (here `some-judge-model`) to be specified to select the best result from the 3 attempts.

3. **Multiple models (Requires Judge)**  
   ```bash
   python -m pdf2anki pic2text scanned_pages output.txt \
       --model google/gemini-2.0-flash-001 --model openai/gpt-4.1 \
       --judge-model some-judge-model
   ```
   - For each image, runs `google/gemini-2.0-flash-001` once and `openai/gpt-4.1` once.  
   - **Requires** `--judge-model` to select the best result between the two models.

4. **Multiple models, repeated calls, with judge**  
   ```bash
   python -m pdf2anki pic2text scanned_pages output.txt \
       --model google/gemini-2.0-flash-001 --model openai/gpt-4.1 \
       --repeat 2 --repeat 1 \
       --judge-model big-ocr-13b --judge-mode authoritative
   ```
   - Runs:
     - `google/gemini-2.0-flash-001` **2 times**  
     - `openai/gpt-4.1` **1 time**  
   - Then uses **`big-ocr-13b`** in “authoritative” mode to pick the best result per image.  
   - The final best text for each image is written to `output.txt`.

5. **Multiple models, judge with images**  
   ```bash
   python -m pdf2anki pic2text scanned_pages output.txt \
       --model modelA --model modelB \
       --judge-model big-ocr-13b \
       --judge-with-image
   ```
   - The judge model also sees the **base64-encoded image**. This might produce more accurate adjudication if your code supports it.

---

## 3. `pdf2text` Command

**Purpose**  
Runs a **two-step** pipeline in a single command:
1. Converts a PDF to images (`pdf2pic`).
2. Performs OCR on those images (`pic2text`).
   
Saves the final extracted text to a single file. This is handy if you only need text output (not an Anki deck).

**Positional Arguments**  
1. `pdf_path` – Path to the PDF file.  
2. `images_dir` – Directory to store generated images (intermediate).  
3. `rectangles` – Crop rectangles (zero or more), same syntax as in `pdf2pic`. Must appear *before* `output_file`.
4. `output_file` – Path to save the final text after OCR.

**Optional Arguments**  
Identical to the optional arguments for `pic2text`:

- `--model MODEL` (repeats allowed)  
- `--repeat N` (repeats allowed, requires `--judge-model` if any N > 1)
- `--judge-model JM` (required if multiple models or repeats > 1)
- `--judge-mode MODE`  
- `--ensemble-strategy STR`  
- `--trust-score VAL`  
- `--judge-with-image`

**Usage**  
```bash
python -m pdf2anki pdf2text PDF_PATH IMAGES_DIR [RECTANGLE1 RECTANGLE2 ...] OUTPUT_FILE
      [--model MODEL...]
      [--repeat N...]
      [--judge-model JM]
      [--judge-mode authoritative]
      [--ensemble-strategy STR]
      [--trust-score VAL]
      [--judge-with-image]
```
  
Note the argument order: `pdf2text <pdf_path> <images_dir> [rectangles...] <output_file> [options...]`

### Examples

1. **Minimal usage, no cropping**  
   ```bash
   python -m pdf2anki pdf2text notes.pdf temp_images output.txt
   ```
   - Step 1: `notes.pdf` → multiple pages in `temp_images/`.  
   - Step 2: OCR results → `output.txt`. (Assumes default model/settings don't require a judge).

2. **With cropping**  
   ```bash
   python -m pdf2anki pdf2text notes.pdf temp_images 50,100,300,400 320,100,600,400 output.txt
   ```
   - Two cropped areas per PDF page → stored in `temp_images/`.  
   - Then OCR → final text in `output.txt`. (Assumes default model/settings don't require a judge).

3. **Advanced: multiple OCR models, repeated calls, judge**  
   ```bash
   python -m pdf2anki pdf2text notes.pdf temp_images 100,150,500,600 output.txt \
       --model google/gemini-2.0-flash-001 --model openai/gpt-4.1 \
       --repeat 2 --repeat 2 \
       --judge-model big-ocr-13b \
       --judge-with-image
   ```
   - Crops each PDF page according to `(100,150,500,600)`.
   - For each cropped image:
     - `google/gemini-2.0-flash-001` is called 2 times
     - `openai/gpt-4.1` is called 2 times
     - The judge model `big-ocr-13b` sees the base64-encoded image to pick the best result.
   - Final text is in `output.txt`.

---

## 4. `text2anki` Command

**Purpose**  
Takes a text file (already extracted by any means) and converts it into an Anki-compatible deck/package file. (Exact format depends on your `text2anki` implementation—some scripts produce `.apkg`, some produce `.txt` or `.csv`, etc.)

**Positional Arguments**  
1. `text_file` – Path to the text file with the content for the cards.  
2. `anki_file` – Path to the final Anki deck output.

**Usage**  
```bash
python -m pdf2anki text2anki TEXT_FILE ANKI_FILE
```

### Examples

1. **Minimal**  
   ```bash
   python -m pdf2anki text2anki reading.txt flashcards.apkg
   ```
   - Converts `reading.txt` into an Anki package `flashcards.apkg`.

2. **After manual editing**  
   If you manually cleaned up the text from OCR, you might do:
   ```bash
   python -m pdf2anki text2anki cleaned_text.txt my_deck.apkg
   ```
   - Results in `my_deck.apkg`.

---

## 5. `process` Command (Full Pipeline)

**Purpose**  
Runs the **entire** process in a single shot:

1. **PDF → images**  
2. **images → text**  
3. **text → Anki deck**  

This means you get an Anki deck from the PDF in one go, without manually calling each intermediate subcommand.

**Positional Arguments**  
1. `pdf_path` – Path to the PDF file.  
2. `output_dir` – Directory to store any intermediate images.  
3. `anki_file` – Path to the final Anki deck file.

**Optional OCR-Related Arguments**  
All the same options as `pic2text`:

- `--model MODEL` (multiple allowed)  
- `--repeat N` (multiple allowed, requires `--judge-model` if any N > 1)
- `--judge-model JM` (required if multiple models or repeats > 1)
- `--judge-mode MODE` (default `authoritative`)  
- `--ensemble-strategy STR` (placeholder)  
- `--trust-score VAL` (placeholder)  
- `--judge-with-image`  

**Usage**  
```bash
python -m pdf2anki process PDF_PATH OUTPUT_DIR ANKI_FILE
      [--model MODEL...]
      [--repeat N...]
      [--judge-model JM]
      [--judge-mode authoritative]
      [--ensemble-strategy STR]
      [--trust-score VAL]
      [--judge-with-image]
```

**Important Note on Cropping**  
The `process` command **does not** explicitly accept rectangles. If you need cropping, you must do it in multiple steps (e.g., call `pdf2pic` first, then `pic2text`, then `text2anki`).

### Examples

1. **Minimal usage**  
   ```bash
   python -m pdf2anki process book.pdf images book.apkg
   ```
   - Step 1: `book.pdf` → images in `images/`.  
   - Step 2: OCR all images → some internal text file (using default model/settings).
   - Step 3: Creates `book.apkg` from that text.

2. **Multiple models, judge**  
   ```bash
   python -m pdf2anki process slides.pdf slides_images slides.apkg \
       --model google/gemini-2.0-flash-001 --model openai/gpt-4.1 \
       --judge-model big-ocr-13b \
       --judge-with-image
   ```
   - Generates final Anki deck `slides.apkg`, with improved OCR results selected by the judge.

3. **Model repeats**  
   ```bash
   python -m pdf2anki process slides.pdf slides_images slides.apkg \
       --model google/gemini-2.0-flash-001 --model openai/gpt-4.1 \
       --repeat 2 --repeat 1 \
       --judge-model big-ocr-13b
   ```
   - Calls `google/gemini-2.0-flash-001` 2 times, `openai/gpt-4.1` 1 time per image, judge picks best.

---

## Putting It All Together

Below are some additional sequences showing how you can build multi-step pipelines manually (for maximum control) or via single commands.

### A. Manual Multi-Step with Cropping

You want to crop the PDF in multiple areas and run advanced OCR:

1. **Step 1**: PDF → images with multiple crop zones
   ```bash
   python -m pdf2anki pdf2pic mynotes.pdf temp_images 50,100,300,400 400,100,600,300
   ```
2. **Step 2**: OCR from images to text, with repeated calls and judge
   ```bash
   python -m pdf2anki pic2text temp_images text_output.txt \
       --model google/gemini-2.0-flash-001 --model openai/gpt-4.1 \
       --repeat 3 --repeat 1 \
       --judge-model big-ocr-13b
   ```
3. **Step 3**: Convert text to Anki
   ```bash
   python -m pdf2anki text2anki text_output.txt final_flashcards.apkg
   ```

### B. Single-Step to Text (no deck)

If all you need is text (and optionally some rectangles for cropping):

```bash
python -m pdf2anki pdf2text mynotes.pdf images_dir 100,150,400,500 output.txt \
    --model openai/gpt-4.1 --judge-model some-judge-model
```
*(Note: Added `--judge-model` as it might be required depending on the `openai/gpt-4.1` implementation or if multiple models were used)*

### C. Full Pipeline to Anki (no cropping)

If you just want the simplest route from PDF to a deck:

```bash
python -m pdf2anki process mynotes.pdf images_dir mydeck.apkg
```
*(Assumes default settings don't require a judge)*

---

## Conclusion

- **Subcommands**:  
  1. **`pdf2pic`** – Convert PDF pages to images (with optional cropping).  
  2. **`pic2text`** – Run OCR on a directory of images, optionally with multiple models and a judge.  
  3. **`pdf2text`** – Combine steps 1 and 2 into a single command, outputting text.  
  4. **`text2anki`** – Convert text into an Anki deck.  
  5. **`process`** – Automate the entire pipeline (PDF → images → text → Anki).

- **Cropping**:  
  Only possible through `pdf2pic` or `pdf2text`. The `process` command does not accept cropping arguments.

- **Multiple Models & Judge**:  
  - Use `--model` multiple times (`--model m1 --model m2 …`).  
  - Pair each with `--repeat N` (they line up by index).  
  - **Must** add `--judge-model` if using multiple models or if any `--repeat N` is greater than 1.
  - `--judge-with-image` passes the images themselves to the judge model.

- **Ensemble & Trust Score**:  
  These placeholders (`--ensemble-strategy`, `--trust-score`) do not currently have active logic in the script. They exist for future expansion.

**Enjoy automating your PDF → OCR → Anki workflows!** If you require commercial/server usage, please remember to contact **martinkrausemediaATgmail.com** for licensing.