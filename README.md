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
  The script is invoked through a single binary/entry-point (e.g., `pdf2anki`), followed by a **command**. Each command has its own set of parameters and optional flags. A global `-v` or `--verbose` flag can be added before the command to enable detailed debug logging.

  The main commands are:
  1. **`pdf2pic`** – Convert a PDF to individual images.
  2. **`pic2text`** – Perform OCR (text extraction) from a set of images.
  3. **`pdf2text`** – Single-step pipeline from PDF directly to text, with inferred output paths.
  4. **`text2anki`** – Convert a text file into an Anki deck/package.
  5. **`process`** – Full pipeline: PDF → images → text → Anki deck, in one go.
  6. **`config`** – View or set configuration options like default models and presets.

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
pdf2anki [-v] COMMAND [OPTIONS...]
```
In the examples below, we will assume `pdf2anki` is your entry-point.

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
        pdf2anki ...
        ```
    *   Example (Windows Command Prompt):
        ```cmd
        set OPENROUTER_API_KEY=YOUR_ACTUAL_API_KEY_HERE
        pdf2anki ...
        ```
    *   Example (Windows PowerShell):
        ```powershell
        $env:OPENROUTER_API_KEY="YOUR_ACTUAL_API_KEY_HERE"
        pdf2anki ...
        ```

Using the `.env` file is generally more convenient for repeated use during development.

---

## Configuration (`config` command)

The `pdf2anki config` command allows you to manage persistent settings stored in `~/.pdf2anki/config.json`. This is useful for setting default models or defining presets for OCR options.

### `config view`

Displays the current configuration.

```bash
pdf2anki config view
```
If the configuration is empty, it will report that. Otherwise, it prints the JSON content.

### `config set`

Sets configuration values. There are three main keys you can manage:

1.  **`default_model`**: The default OCR model used by `pic2text`, `pdf2text`, and `process` if `--model` is not specified.
2.  **`default_anki_model`**: The default model used by `text2anki` and `process` for generating Anki cards if the `anki_model` argument is not provided.
3.  **`defaults`**: A preset object containing OCR settings (`model`, `repeat`, `judge_model`, `judge_mode`, `judge_with_image`) that can be activated using the `-d` flag in `pdf2text` and `process`.

**Usage:**

*   **Set default models:**
    ```bash
    pdf2anki config set default_model <model_name>
    pdf2anki config set default_anki_model <model_name>
    ```
*   **Set individual preset defaults (for the `-d` flag):**
    ```bash
    pdf2anki config set defaults <setting_name> <value>
    ```
    Where `<setting_name>` is one of `model`, `repeat`, `judge_model`, `judge_mode`, `judge_with_image`.
*   **Set all preset defaults using JSON (Advanced - Careful with shell quoting!):**
    ```bash
    pdf2anki config set defaults '<json_object_string>'
    ```

**Examples:**

1.  **Set the default OCR model:**
    ```bash
    pdf2anki config set default_model google/gemini-flash-1.5
    ```
2.  **Set the default Anki generation model:**
    ```bash
    pdf2anki config set default_anki_model google/gemini-flash-1.5
    ```
3.  **Set up the preset defaults for the `-d` flag individually:**
    ```powershell
    # Set the model(s) for the preset
    pdf2anki config set defaults model google/gemini-2.0-flash-001
    # Set the repeat count(s) for the preset model(s)
    pdf2anki config set defaults repeat 2
    # Set the judge model for the preset
    pdf2anki config set defaults judge_model google/gemini-2.0-flash-001
    # Set the judge mode for the preset
    pdf2anki config set defaults judge_mode authoritative
    # Enable judge_with_image for the preset
    pdf2anki config set defaults judge_with_image true
    ```
4.  **View the configuration after setting defaults:**
    ```bash
    pdf2anki config view
    ```
    *(This might show something like):*
    ```json
    {
      "default_model": "google/gemini-flash-1.5",
      "default_anki_model": "google/gemini-flash-1.5",
      "defaults": {
        "model": [
          "google/gemini-2.0-flash-001"
        ],
        "repeat": [
          2
        ],
        "judge_model": "google/gemini-2.0-flash-001",
        "judge_mode": "authoritative",
        "judge_with_image": true
      }
    }
    ```

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
pdf2anki pdf2pic PDF_PATH OUTPUT_DIR [RECTANGLE1 RECTANGLE2 ...]
```

### Examples

1. **Minimal usage (no cropping)**

   ```bash
   pdf2anki pdf2pic mydocument.pdf output_images
   ```
   - Converts each page of `mydocument.pdf` into `output_images/page-1.png`, `output_images/page-2.png`, etc.

2. **Single rectangle**  
   ```bash
   pdf2anki pdf2pic mydocument.pdf output_images 100,150,500,600
   ```
   - Converts each page into a cropped version from `(left=100, top=150)` to `(right=500, bottom=600)`.

3. **Multiple rectangles**  
   ```bash
   pdf2anki pdf2pic mydocument.pdf output_images 50,100,300,400 320,100,600,400
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
| `--model MODEL`      | Name of an OCR model. Can be used multiple times. **If omitted, uses `default_model` from config.** If no default is set, prompts user or errors out. |
| `--repeat N`         | Number of times to call each model per image (defaults to 1). If you provide multiple `--model` entries and multiple `--repeat` entries, each repeats entry corresponds to its respective model. **Requires `--judge-model` if any N > 1.** |
| `--judge-model JM`   | If you have **multiple** OCR models or use `--repeat > 1`, you **must** specify a judge model to pick the best text. E.g., `--judge-model big-ocr-13b`. |
| `--judge-mode MODE`  | Judge strategy. Currently only `"authoritative"` is implemented. If set, the judge simply picks the best result (the logic is inside your code).                                           |
| `--ensemble-strategy STR` | **(Placeholder)** e.g., `majority-vote`, `similarity-merge`. Not active in the code yet, so setting it won't do anything.                                                              |
| `--trust-score VAL`  | **(Placeholder)** float representing model weighting factor in an ensemble or judge scenario. Not active in the code yet.                                                                  |
| `--judge-with-image` | Boolean flag; if set, the judge model also sees the base64-encoded image when deciding among multiple OCR outputs.                                                                          |

**Usage**  
```bash
pdf2anki pic2text IMAGES_DIR OUTPUT_FILE [--model MODEL...] [--repeat N...] 
      [--judge-model JM] [--judge-mode authoritative]
      [--ensemble-strategy STR] [--trust-score VAL] [--judge-with-image]
```

### Examples

1. **Minimal usage (using default OCR model from config)**  
   ```bash
   # Assumes 'default_model' is set via 'pdf2anki config set default_model ...'
   pdf2anki pic2text scanned_pages output.txt
   ```
   - OCR is done using the configured `default_model`. Saves text to `output.txt`.

2. **Specify model explicitly (overrides default)**
   ```bash
   pdf2anki pic2text scanned_pages output.txt --model google/gemini-pro
   ```

3. **Single model, repeated calls (Requires Judge)**  
   ```bash
   pdf2anki pic2text scanned_pages output.txt --model google/gemini-flash-1.5 --repeat 3 --judge-model google/gemini-pro
   ```
   - Runs `google/gemini-flash-1.5` OCR 3 times per image.
   - Requires `--judge-model` (`google/gemini-pro`) to select the best result.

4. **Multiple models (Requires Judge)**  
   ```bash
   pdf2anki pic2text scanned_pages output.txt \
       --model google/gemini-2.0-flash-001 --model openai/gpt-4.1 \
       --judge-model some-judge-model
   ```
   - For each image, runs `google/gemini-2.0-flash-001` once and `openai/gpt-4.1` once.  
   - **Requires** `--judge-model` to select the best result between the two models.

5. **Multiple models, repeated calls, with judge**  
   ```bash
   pdf2anki pic2text scanned_pages output.txt \
       --model google/gemini-2.0-flash-001 --model openai/gpt-4.1 \
       --repeat 2 --repeat 1 \
       --judge-model big-ocr-13b --judge-mode authoritative
   ```
   - Runs:
     - `google/gemini-2.0-flash-001` **2 times**  
     - `openai/gpt-4.1` **1 time**  
   - Then uses **`big-ocr-13b`** in “authoritative” mode to pick the best result per image.  
   - The final best text for each image is written to `output.txt`.

6. **Multiple models, judge with images**  
   ```bash
   pdf2anki pic2text scanned_pages output.txt \
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
   
Saves the final extracted text to a single file. This is handy if you only need text output (not an Anki deck). **Output paths can be inferred if omitted.**

**Positional Arguments**  
1. `pdf_path` – Path to the PDF file.  
2. `output_dir` – **(Optional)** Directory for intermediate images. Defaults to `./pdf2pic/<pdf_name>/`.
3. `rectangles` – **(Optional)** Crop rectangles (`left,top,right,bottom`). Must appear *before* `output_file` if both are specified.
4. `output_file` – **(Optional)** Path to save the final text. Defaults to `./<pdf_name>.txt`.

**Optional Arguments**  

| Parameter            | Description                                                                                                                                           |
|----------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| `-d`, `--default`    | **Use preset defaults.** If set, applies OCR settings (`model`, `repeat`, `judge_model`, etc.) from the `defaults` section of the config. Exits if no defaults are configured. |
| `--model MODEL`      | Name of an OCR model. Can be used multiple times. **If omitted (and `-d` not used), uses `default_model` from config.** Overrides `-d` settings if specified. |
| `--repeat N`         | Number of times to call each model per image (defaults to 1). If you provide multiple `--model` entries and multiple `--repeat` entries, each repeats entry corresponds to its respective model. **Requires `--judge-model` if any N > 1.** |
| `--judge-model JM`   | If you have **multiple** OCR models or use `--repeat > 1`, you **must** specify a judge model to pick the best text. E.g., `--judge-model big-ocr-13b`. |
| `--judge-mode MODE`  | Judge strategy. Currently only `"authoritative"` is implemented. If set, the judge simply picks the best result (the logic is inside your code).                                           |
| `--ensemble-strategy STR` | **(Placeholder)** e.g., `majority-vote`, `similarity-merge`. Not active in the code yet, so setting it won't do anything.                                                              |
| `--trust-score VAL`  | **(Placeholder)** float representing model weighting factor in an ensemble or judge scenario. Not active in the code yet.                                                                  |
| `--judge-with-image` | Boolean flag; if set, the judge model also sees the base64-encoded image when deciding among multiple OCR outputs.                                                                          |

**Usage**  
```bash
# With explicit paths
pdf2anki pdf2text PDF_PATH IMAGES_DIR [RECTANGLES...] OUTPUT_FILE [OPTIONS...]

# With inferred paths
pdf2anki pdf2text PDF_PATH [RECTANGLES...] [OPTIONS...]
```
  
Note the argument order: `pdf2text <pdf_path> [output_dir] [rectangles...] [output_file] [options...]`

### Examples

1. **Minimal usage (inferred paths, default OCR model)**  
   ```bash
   # Assumes 'default_model' is configured
   pdf2anki pdf2text notes.pdf
   ```
   - Step 1: `notes.pdf` → images in `./pdf2pic/notes/`.
   - Step 2: OCR using `default_model` → text saved to `./notes.txt`.

2. **Minimal usage with preset defaults (`-d` flag)**
   ```bash
   # Assumes 'defaults' are configured via 'pdf2anki config set defaults ...'
   pdf2anki pdf2text notes.pdf -d
   ```
   - Step 1: `notes.pdf` → images in `./pdf2pic/notes/`.
   - Step 2: OCR using settings from config `defaults` → text saved to `./notes.txt`.

3. **Specify output paths, override default model**
   ```bash
   pdf2anki pdf2text notes.pdf custom_images/ final_text.txt --model google/gemini-pro
   ```
   - Step 1: `notes.pdf` → images in `custom_images/`.
   - Step 2: OCR using `google/gemini-pro` → text saved to `final_text.txt`.

4. **Inferred paths with cropping and preset defaults**
   ```bash
   pdf2anki pdf2text notes.pdf 50,100,300,400 -d
   ```
   - Step 1: Crops `notes.pdf` → images in `./pdf2pic/notes/`.
   - Step 2: OCR using config `defaults` → text saved to `./notes.txt`.

5. **Explicit paths, multiple models (overrides defaults and `-d`)**
   ```bash
   pdf2anki pdf2text notes.pdf temp_images output.txt \
       --model google/gemini-flash-1.5 --model openai/gpt-4.1 \
       --repeat 2 --repeat 1 \
       --judge-model google/gemini-pro
   ```
   - Step 1: `notes.pdf` → images in `temp_images/`.
   - Step 2: Runs specified models/repeats, judged by `google/gemini-pro` → text saved to `output.txt`.

---

## 4. `text2anki` Command

**Purpose**  
Takes a text file (already extracted by any means) and converts it into an Anki-compatible deck/package file. (Exact format depends on your `text2anki` implementation—some scripts produce `.apkg`, some produce `.txt` or `.csv`, etc.)

**Positional Arguments**  
1. `text_file` – Path to the text file with the content for the cards.  
2. `anki_file` – Path to the final Anki deck output.
3. `anki_model` – **(Optional)** Name of the OpenRouter model for generating cards. **If omitted, uses `default_anki_model` from config.** Raises error if omitted and no default is set.

**Usage**  
```bash
pdf2anki text2anki TEXT_FILE ANKI_FILE [ANKI_MODEL]
```

### Examples

1. **Minimal (using default Anki model)**  
   ```bash
   # Assumes 'default_anki_model' is configured
   pdf2anki text2anki reading.txt flashcards.apkg
   ```
   - Converts `reading.txt` into `flashcards.apkg` using the configured `default_anki_model`.

2. **Specify Anki model explicitly**
   ```bash
   pdf2anki text2anki cleaned_text.txt my_deck.apkg google/gemini-pro
   ```
   - Converts `cleaned_text.txt` into `my_deck.apkg` using `google/gemini-pro`.

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
4. `anki_model` – **(Optional)** Name of the OpenRouter model for generating cards. **If omitted, uses `default_anki_model` from config.** Raises error if omitted and no default is set.

**Optional OCR-Related Arguments**  

| Parameter            | Description                                                                                                                                           |
|----------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| `-d`, `--default`    | **Use preset OCR defaults.** If set, applies OCR settings (`model`, `repeat`, `judge_model`, etc.) from the `defaults` section of the config for the text extraction step. Warns if no defaults are configured but continues. |
| `--model MODEL`      | Name of an OCR model. Can be used multiple times. **If omitted (and `-d` not used), uses `default_model` from config.** Overrides `-d` settings if specified. |
| `--repeat N`         | Number of times to call each model per image (defaults to 1). If you provide multiple `--model` entries and multiple `--repeat` entries, each repeats entry corresponds to its respective model. **Requires `--judge-model` if any N > 1.** |
| `--judge-model JM`   | If you have **multiple** OCR models or use `--repeat > 1`, you **must** specify a judge model to pick the best text. E.g., `--judge-model big-ocr-13b`. |
| `--judge-mode MODE`  | Judge strategy. Currently only `"authoritative"` is implemented. If set, the judge simply picks the best result (the logic is inside your code).                                           |
| `--ensemble-strategy STR` | **(Placeholder)** e.g., `majority-vote`, `similarity-merge`. Not active in the code yet, so setting it won't do anything.                                                              |
| `--trust-score VAL`  | **(Placeholder)** float representing model weighting factor in an ensemble or judge scenario. Not active in the code yet.                                                                  |
| `--judge-with-image` | Boolean flag; if set, the judge model also sees the base64-encoded image when deciding among multiple OCR outputs.                                                                          |

**Usage**  
```bash
pdf2anki process PDF_PATH OUTPUT_DIR ANKI_FILE [ANKI_MODEL] [OCR_OPTIONS...]
```

**Important Note on Cropping**  
The `process` command **does not** explicitly accept rectangles. If you need cropping, you must do it in multiple steps (e.g., call `pdf2pic` first, then `pic2text`, then `text2anki`).

### Examples

1. **Minimal usage (using default OCR and Anki models)**  
   ```bash
   # Assumes 'default_model' and 'default_anki_model' are configured
   pdf2anki process book.pdf images book.apkg
   ```
   - Step 1: `book.pdf` → images in `images/`.
   - Step 2: OCR using `default_model`.
   - Step 3: Creates `book.apkg` using `default_anki_model`.

2. **Using preset OCR defaults (`-d`) and default Anki model**
   ```bash
   # Assumes 'defaults' (for OCR) and 'default_anki_model' are configured
   pdf2anki process book.pdf images book.apkg -d
   ```
   - Step 1: `book.pdf` → images in `images/`.
   - Step 2: OCR using settings from config `defaults`.
   - Step 3: Creates `book.apkg` using `default_anki_model`.

3. **Specify Anki model, use default OCR model**
   ```bash
   # Assumes 'default_model' is configured
   pdf2anki process slides.pdf slides_images slides.apkg google/gemini-pro
   ```
   - Uses `default_model` for OCR, but `google/gemini-pro` for Anki card generation.

4. **Specify OCR models (overrides defaults), specify Anki model**
   ```bash
   pdf2anki process slides.pdf slides_images slides.apkg google/gemini-pro \
       --model google/gemini-flash-1.5 --model openai/gpt-4.1 \
       --judge-model google/gemini-pro \
       --judge-with-image
   ```
   - Uses specified OCR models/judge for text extraction.
   - Uses `google/gemini-pro` (the positional argument) for Anki card generation.

---

## Putting It All Together

Below are some additional sequences showing how you can build multi-step pipelines manually (for maximum control) or via single commands.

### A. Manual Multi-Step with Cropping

You want to crop the PDF in multiple areas and run advanced OCR:

1. **Step 1**: PDF → images with multiple crop zones
   ```bash
   pdf2anki pdf2pic mynotes.pdf temp_images 50,100,300,400 400,100,600,300
   ```
2. **Step 2**: OCR from images to text, with repeated calls and judge
   ```bash
   pdf2anki pic2text temp_images text_output.txt \
       --model google/gemini-2.0-flash-001 --model openai/gpt-4.1 \
       --repeat 3 --repeat 1 \
       --judge-model big-ocr-13b
   ```
3. **Step 3**: Convert text to Anki
   ```bash
   pdf2anki text2anki text_output.txt final_flashcards.apkg
   ```

### B. Single-Step to Text (no deck)

If all you need is text (and optionally some rectangles for cropping):

```bash
# Using inferred paths and preset defaults
pdf2anki pdf2text mynotes.pdf 100,150,400,500 -d

# Or specifying model explicitly (overrides defaults)
pdf2anki pdf2text mynotes.pdf images_dir 100,150,400,500 output.txt --model openai/gpt-4.1
```
*(Note: Added `--judge-model` as it might be required depending on the `openai/gpt-4.1` implementation or if multiple models were used)*

### C. Full Pipeline to Anki (no cropping)

If you just want the simplest route from PDF to a deck:

```bash
# Simplest case using all configured defaults
pdf2anki process mynotes.pdf images_dir mydeck.apkg

# Using preset OCR defaults (-d) and specifying Anki model
pdf2anki process mynotes.pdf images_dir mydeck.apkg google/gemini-pro -d
```

---

## Conclusion

- **Subcommands**:  
  1. **`pdf2pic`** – Convert PDF pages to images (with optional cropping).  
  2. **`pic2text`** – Run OCR on a directory of images, optionally with multiple models and a judge.  
  3. **`pdf2text`** – Combine steps 1 and 2 into a single command, outputting text.  
  4. **`text2anki`** – Convert text into an Anki deck.  
  5. **`process`** – Automate the entire pipeline (PDF → images → text → Anki).  
  6. **`config`** – Manage default models and presets.

- **Defaults & Presets**:
  - Configure `default_model`, `default_anki_model`, and `defaults` (for OCR presets) using `pdf2anki config set`.
  - Use the `-d` flag with `pdf2text` or `process` to activate the `defaults` preset for OCR. Explicit OCR options override `-d`.

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