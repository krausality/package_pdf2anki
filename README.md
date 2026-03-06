# pdf2anki

**Convert PDFs to Anki Flashcards with Advanced OCR and Configuration**

`pdf2anki` is a powerful command-line interface (CLI) tool designed to streamline the conversion of PDF documents into Anki flashcards. It offers a multi-step, configurable pipeline involving PDF-to-image conversion (with optional cropping), advanced OCR using multiple models and a "judge" model, and automated Anki card generation.

```
PDF  ──pdf2pic──►  Images  ──pic2text──►  Text  ──text2anki──►  Anki Deck (.apkg)
```

## Quick Start

```bash
# 1. Install (editable, inside a virtual environment)
pip install --editable .

# 2. Set a default OCR model and a default Anki-generation model
pdf2anki config set default_model      google/gemini-2.0-flash-001
pdf2anki config set default_anki_model google/gemini-2.0-flash-001

# 3a. Full pipeline for a single PDF
pdf2anki process lecture.pdf ./images/ lecture.apkg

# 3b. Or step by step
pdf2anki pdf2pic   lecture.pdf ./images/
pdf2anki pic2text  ./images/   lecture.txt
pdf2anki text2anki lecture.txt lecture.apkg

# 3c. Already have cards as JSON? Convert offline, no API key needed
pdf2anki json2anki cards.json
```

---

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
  The script is invoked through a single entry-point (e.g., `pdf2anki` or `python -m pdf2anki`), followed by a **command**. Each command has its own set of parameters and optional flags. A global `-v` or `--verbose` flag can be added before the command to enable detailed debug logging.

  The main commands are:
  1.  **`pdf2pic`**: Convert PDF pages to images, with optional advanced cropping.
  2.  **`pic2text`**: Perform OCR on images using one or more models, with an optional judge model to select the best result.
  3.  **`pdf2text`**: A comprehensive pipeline to convert a PDF (or a directory of PDFs) directly to text, utilizing `pdf2pic` and `pic2text` functionalities internally. Supports batch processing with parallel execution.
  4.  **`text2anki`**: Convert a pre-existing text file into an Anki deck (simple, one-shot).
  5.  **`json2anki`**: Convert a JSON file (or all JSON files in a directory) containing flashcards to an Anki deck (no LLM). Supports optional fields for advanced organization: tags, guid, sort_field, due. The output file is optional and defaults to the same name as the input with `.apkg` extension. Supports bulk processing for directories. Includes `--show-format` to display expected JSON structure with examples.
  6.  **`process`**: The full end-to-end pipeline: PDF → images → text → Anki deck for a single PDF.
  7.  **`workflow`**: **Project-based SSOT card management** — ingest text via LLM, integrate into a structured card database, sync derived files, export `.apkg`. This is the recommended entry point for semester-long learning projects. See [Section 7](#7-advanced-ssot-text2anki-workflow).
  8.  **`config`**: View or set persistent configuration options, such as default models and OCR presets.

---

## 🛠 Development Mode (Editable Installs)

If you plan to **develop or modify this project locally**, it's recommended to use an **editable install**. This allows Python to load the package **directly from your source directory**, so any code changes are reflected immediately — no need to reinstall after every edit.

### Setup

```bash
# cd to the project's root directory (where pyproject.toml is)
# python -m venv .venv # Create a virtual environment
# source .venv/bin/activate  # On Linux/macOS
# .venv\Scripts\activate    # On Windows
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

  - A **console script entry point** is automatically created during install (defined in `pyproject.toml` or `setup.py`).
  - On Windows: creates `pdf2anki.exe` in `.venv\Scripts\`
  - On macOS/Linux: creates `pdf2anki` in `.venv/bin/`

💡 **Pro tip**: Check where the executable lives with:

```bash
where pdf2anki      # on Windows
which pdf2anki      # on macOS/Linux
```

If the command isn’t found, make sure your virtual environment is activated and its `Scripts` (Windows) or `bin` (Linux/macOS) directory is in your PATH.

---

## API Key Configuration

To utilize features that interact with external language models (like the OCR capabilities in `pic2text`, `pdf2text`, and `process`, or card generation in `text2anki`), you need to provide an API key. The project is configured to work with models available via **OpenRouter.ai**.

The required API key is expected to be set as an environment variable named `OPENROUTER_API_KEY`.

There are two primary ways to make this key available to the script:

1.  **Using a `.env` file (Recommended):**
    *   Create a file named `.env` in the root directory of the project (where this `README.md` is).
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

Using the `.env` file is generally more convenient for repeated use.

---

## OCR Resume and Pause Behavior

OCR commands now support resilient continuation by default:

1.  **Automatic Resume (Default)**
    *   `pic2text`, `pdf2text`, and the OCR step of `process` will try to resume from existing OCR output.
    *   For `pdf2text` and `process`, image generation is also resume-aware: existing valid page images/crops are reused, and only missing/invalid ones are regenerated.
    *   A sidecar checkpoint file is written during processing next to the output text file:
        *   `<output_file>.ocr_state.json`
    *   After successful completion, this state file is archived into:
        *   `log_archive/`
    *   On later restarts, archived state snapshots are automatically consulted to avoid unnecessary re-OCR work.
    *   Legacy `.txt` files (without sidecar state) are still supported. Successful sections are reused, failed/incomplete sections are retried.

2.  **Per-Page Attempt Limit**
    *   Each page is retried up to `--max-page-attempts` full OCR cycles (default: `40`).
    *   If the limit is reached, processing is marked as **paused** and exits with an error so you can fix external issues (e.g., expired API key) and rerun.

3.  **Disable Resume Explicitly**
    *   Use `--no-resume` to start OCR from scratch for that run.

4.  **Runtime Metrics**
    *   OCR now prints resume-source diagnostics and live progress metrics (done/total, resumed pages, attempts, current page, status, elapsed time).

---

## Configuration (`config` command)

The `pdf2anki config` command allows you to manage persistent settings stored in `~/.pdf2anki/config.json`. This is useful for setting default models or defining presets for OCR options, which can simplify command-line invocations.

### `config view`

Displays the current configuration.

```bash
pdf2anki config view
```

If the configuration is empty, it will report that. Otherwise, it prints the JSON content.

### `config set`

Sets configuration values. There are three main top-level keys you can manage:

1.  **`default_model`**: The default OCR model used by `pic2text`, `pdf2text`, and `process` if no `--model` is specified for the OCR step and no preset is configured.
2.  **`default_anki_model`**: The default model used by `text2anki` and `process` for generating Anki cards if the `anki_model` argument is not provided.
3.  **`defaults`**: A preset object containing OCR settings (`model`, `repeat`, `judge_model`, `judge_mode`, `judge_with_image`) that are **applied automatically** to the `pdf2text`, `pic2text`, and `process` commands. Any settings provided directly on the command line will override these presets.

**Configuration Resolution Priority**  
Settings are resolved in this strict order:
1. **CLI Arguments** (highest priority) - e.g., `--model <name>`
2. **Preset Defaults** - from `defaults` in config.json
3. **Global Defaults** - `default_model` or `default_anki_model` in config.json
4. **Interactive Prompt** (lowest priority) - only if running interactively and no other source available

This hierarchy ensures that explicit command-line options always take precedence over configured defaults.

**Usage:**

*   **Set default models:**
    ```bash
    pdf2anki config set default_model <model_name>
    pdf2anki config set default_anki_model <model_name>
    ```
*   **Set up the preset defaults individually:**
    ```bash
    # These settings will be used by default for `pdf2text`, `pic2text`, and `process`
    pdf2anki config set defaults model "google/gemini-2.0-flash-001"
    pdf2anki config set defaults repeat 2
    pdf2anki config set defaults judge_model "openai/chatgpt-4o-latest"
    ```
*   **Set all preset defaults using a single JSON string (Advanced - careful with shell quoting!):**
    ```bash
    pdf2anki config set defaults '<json_object_string>'
    ```
    Example JSON: `'{"model": ["google/gemini-2.0-flash-001", "openai/chatgpt-4o-latest"], "repeat": [2, 1], "judge_model": "google/gemini-2.0-flash-001", "judge_with_image": true}'`

**Examples:**

1.  **Set the default OCR model:**
    ```bash
    pdf2anki config set default_model google/gemini-2.0-flash-001
    ```
2.  **Set the default Anki generation model:**
    ```bash
    pdf2anki config set default_anki_model openai/chatgpt-4o-latest
    ```
3.  **Set up the preset defaults individually:**
    ```bash
    # These settings will now be the default for OCR tasks
    pdf2anki config set defaults model "google/gemini-2.0-flash-001"
    pdf2anki config set defaults repeat 2
    pdf2anki config set defaults judge_model "openai/chatgpt-4o-latest"
    ```
4.  **View the configuration after setting defaults:**
    ```bash
    pdf2anki config view
    ```
    *(This might show something like):*
    ```json
    {
      "default_model": "google/gemini-2.0-flash-001",
      "default_anki_model": "openai/chatgpt-4o-latest",
      "defaults": {
        "model": [
          "google/gemini-2.0-flash-001",
          "openai/chatgpt-4o-latest"
        ],
        "repeat": [
          2,
          1
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
Converts pages of a PDF into separate image files. It can save full-page images or specified cropped regions. If cropping, it uses a high-DPI rendering for quality and can generate a `*_recrop.pdf` containing all cropped images.

**Syntax**
```bash
pdf2anki pdf2pic <pdf_path> <output_dir> [rectangle1 rectangle2 ...] [--resume-existing]
```

**Positional Arguments**
1.  `pdf_path`: Path to the input PDF file.
2.  `output_dir`: Directory where resulting images will be stored.
3.  `rectangles` (Optional, zero or more): Crop rectangle specifications, each as a string `"left,top,right,bottom"` (pixel coordinates, typically based on a 300 DPI rendering).

**Behavior**
*   If no `rectangles` are provided, each PDF page is saved as a full image (e.g., `page_1.png`). The DPI is chosen dynamically to aim for an optimal file size.
*   If `rectangles` are provided:
    *   No full-page images are saved by default.
    *   For each PDF page, each specified rectangle is cropped.
    *   Cropping is performed on a high-resolution render of the page for maximum detail.
    *   Cropped images are saved (e.g., `page_1_crop_1.jpg`, `page_1_crop_2.jpg`).
    *   A `*_recrop.pdf` file is generated in `output_dir`, containing all cropped images, each on a separate page, auto-oriented (portrait/landscape).
*   With `--resume-existing`, already existing valid page files are reused and only missing/invalid files are regenerated.

**Examples**

1.  **Convert PDF to full-page images (no cropping)**
    ```bash
    pdf2anki pdf2pic mydocument.pdf output_images/
    ```
    - Converts `mydocument.pdf` pages to `output_images/page_1.png`, `output_images/page_2.png`, etc.

2.  **Convert PDF with a single crop rectangle per page**
    ```bash
    pdf2anki pdf2pic mydocument.pdf cropped_images/ "100,150,500,600"
    ```
    - For each page, creates one cropped image based on the coordinates.
    - Generates `cropped_images/mydocument_recrop.pdf`.

3.  **Convert PDF with multiple crop rectangles per page**
    ```bash
    pdf2anki pdf2pic report.pdf report_parts/ "50,50,400,300" "50,350,400,600"
    ```
    - For each page, creates two cropped images.
    - Generates `report_parts/report_recrop.pdf`.

---

## 2. `pic2text` Command

**Purpose**
Performs Optical Character Recognition (OCR) on a directory of images. Supports using one or multiple OCR models, repeating OCR calls, and using a "judge" model to select the best text output per image.

**Syntax**
```bash
pdf2anki pic2text <images_dir> [output_file] [OPTIONS...]
```

**Positional Arguments**
1.  `images_dir`: Directory containing image files (e.g., PNG, JPG) to process.
2.  `output_file` (Optional): Path to the text file where final OCR results will be written. If omitted, it defaults to a `.txt` file with the same name as the `images_dir` in the current working directory (e.g., `my_images` -> `my_images.txt`).

**Optional Arguments**

| Parameter                 | Description                                                                                                                                                             |
|---------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `--model <MODEL_NAME>`    | Name of an OCR model. Can be used multiple times to specify several models. If omitted, uses `default_model` from config. If no default, an error occurs.                 |
| `--repeat <N>`            | Number of times to call the corresponding OCR model (by order) per image. Defaults to 1. E.g., `--model M1 --model M2 --repeat 2 --repeat 3` runs M1 twice, M2 thrice. |
| `--judge-model <MODEL_NAME>` | Model to select the best text if multiple OCR outputs are generated (due to multiple models or repeats > 1). **Required in such cases.**                               |
| `--judge-mode <MODE>`     | Strategy for the judge model. Default: `authoritative`. Currently, only `authoritative` is implemented.                                                                  |
| `--judge-with-image`      | Flag. If set, the judge model also receives the base64-encoded image along with text candidates to aid its decision.                                                      |
| `--ensemble-strategy <S>` | (Placeholder) Intended for future ensemble methods. Currently ignored.                                                                                                  |
| `--trust-score <W>`       | (Placeholder) Intended for future model weighting. Currently ignored.                                                                                                   |
| `--no-resume`             | Disable OCR resume for this run. Starts from scratch instead of reusing previous progress.                                                                             |
| `--max-page-attempts <N>` | Maximum full OCR attempts per page before pausing the run. Default: `40`.                                                                                               |

**Behavior**
*   Processes images sorted by page number (if `page_X` in filename).
*   For each image:
    *   Calls specified OCR models, respecting repeat counts.
    *   If multiple text candidates result:
        *   If `--judge-model` is provided, the judge selects the best text.
        *   Otherwise (multiple candidates but no judge), an error occurs.
    *   If only one text candidate results, it's used directly.
    *   Failed pages are retried up to `--max-page-attempts`. When the limit is reached, the run pauses with a non-zero exit.
*   Logs OCR calls to `ocr_*.log` and judge decisions to `decisionmaking_*.log`. These logs are archived after processing.

**Examples**

1.  **Minimal usage (using preset/default OCR model and inferred output path)**
    ```bash
    # Processes images in `my_images/`, saves to `./my_images.txt`
    pdf2anki pic2text my_images/
    ```

2.  **Specify a single OCR model explicitly and define output**
    ```bash
    pdf2anki pic2text my_images/ ocr_results.txt --model "google/gemini-2.0-flash-001"
    ```

3.  **Single model, repeated calls (requires a judge)**
    ```bash
    pdf2anki pic2text noisy_scans/ best_text.txt \
        --model google/gemini-2.0-flash-001 --repeat 3 \
        --judge-model openai/chatgpt-4o-latest
    ```
    - `google/gemini-2.0-flash-001` runs 3 times per image. `openai/chatgpt-4o-latest` picks the best of the 3.

4.  **Multiple models (requires a judge)**
    ```bash
    pdf2anki pic2text slides_images/ combined_ocr.txt \
        --model openai/chatgpt-4o-latest --model google/gemini-2.0-flash-001 \
        --judge-model google/gemini-2.0-flash-001
    ```

5.  **Multiple models, varied repeats, with judge and image context for judge**
    ```bash
    pdf2anki pic2text complex_layout_imgs/ final_text.txt \
        --model google/gemini-2.0-flash-001 --model openai/chatgpt-4o-latest \
        --repeat 2 --repeat 1 \
        --judge-model google/gemini-2.0-flash-001 \
        --judge-with-image
    ```
    - `google/gemini-2.0-flash-001` runs twice, `openai/chatgpt-4o-latest` runs once. `google/gemini-2.0-flash-001` judges, also seeing the image.

---

## 3. `pdf2text` Command

**Purpose**
A comprehensive command to convert PDF documents to text. It can process a single PDF file or all PDF files within a specified directory (performing OCR in parallel for directory inputs). It combines `pdf2pic` and `pic2text` functionalities.

**Syntax**
```bash
pdf2anki pdf2text <pdf_path_or_dir> [images_output_dir] [rectangle1 ...] [text_output_path] [OPTIONS...]
```

**Positional Arguments**
1.  `pdf_path_or_dir`: Path to a single input PDF file or a directory containing PDF files.
2.  `images_output_dir` (Optional):
    *   If `pdf_path_or_dir` is a single file: The specific directory to save its images.
        Default: `./pdf2pic/<pdf_name_without_extension>/`
    *   If `pdf_path_or_dir` is a directory: The base directory where subfolders for each PDF's images will be created (e.g., `<images_output_dir>/<pdf_name>/`).
        Default: `./pdf2pic/`
3.  `rectangles` (Optional, zero or more): Crop rectangle strings (e.g., `"l,t,r,b"`), applied to all processed PDFs.
4.  `text_output_path` (Optional):
    *   If `pdf_path_or_dir` is a single file: The full path for the final output `.txt` file.
        Default: `./<pdf_name_without_extension>.txt` (in the current working directory).
    *   If `pdf_path_or_dir` is a directory: The base directory where individual `.txt` files (one per PDF) will be saved.
        Default: Current working directory.

**Optional OCR Arguments (Options)**
*   `--model <MODEL_NAME>`, `--repeat <N>`, `--judge-model <MODEL_NAME>`, `--judge-mode <MODE>`, `--judge-with-image`, `--ensemble-strategy <S>`, `--trust-score <W>`, `--no-resume`, `--max-page-attempts <N>`: Same as for the `pic2text` command. These settings will override any presets in `config.json`. If no model is specified via these options or in presets, the `default_model` from config is used.

**Behavior**
*   **Single PDF:** Converts to images (with cropping if `rectangles` provided), then performs OCR on these images.
*   **Directory of PDFs:** Processes each PDF found in the directory. Image conversion and OCR for different PDFs are run in parallel using multiple CPU cores for efficiency.
*   When OCR resume is enabled (default), image generation is resume-aware: existing valid page files are reused and only missing/invalid pages are regenerated.
*   If any page reaches `--max-page-attempts`, OCR is paused and `pdf2text` exits with an error so the run can be resumed later.
*   Default paths are intelligently determined if optional path arguments are omitted.
*   Uses the same logging and archiving mechanism as `pic2text` for each PDF processed.

**Examples**

1.  **Process a directory of PDFs using preset defaults and inferred output paths**
    ```bash
    # OCR uses settings from `config.json` `defaults`.
    # If no presets are configured, it will use the global `default_model`.
    pdf2anki pdf2text "path/to/my/pdfs/"
    ```

2.  **Process a single PDF with specified output paths and OCR models (overriding presets)**
    ```bash
    pdf2anki pdf2text "mydoc.pdf" "images_out/" "doc_text.txt" --model "google/gemini-2.0-flash-001"
    ```
    - Images: `images_out/`
    - Text: `doc_text.txt`

3.  **Process a directory, specify output base directories, and crop**
    ```bash
    pdf2anki pdf2text ./research_papers/ /mnt/data/paper_images/ "50,50,800,1000" /mnt/data/paper_texts/ \
        --model openai/chatgpt-4o-latest
    ```
    - Images for `research_papers/paper1.pdf`: `/mnt/data/paper_images/paper1/`
    - Text for `research_papers/paper1.pdf`: `/mnt/data/paper_texts/paper1.txt`
    - All pages cropped to "50,50,800,1000".

4.  **Process a single PDF using only default OCR model and inferred paths**
    ```bash
    # Assumes 'default_model' (e.g. google/gemini-2.0-flash-001) is configured
    pdf2anki pdf2text "My Important Article.pdf"
    ```
    - Images: `./pdf2pic/My Important Article/`
    - Text: `./My Important Article.txt`

---

## 4. `text2anki` Command

**Purpose**
Converts a pre-existing text file (presumably containing content suitable for flashcards) into an Anki-compatible package file (`.apkg`).

**Syntax**
```bash
pdf2anki text2anki <text_file> <anki_file> [anki_model_name]
```

**Positional Arguments**
1.  `text_file`: Path to the input text file.
2.  `anki_file`: Path for the output Anki package file (e.g., `my_deck.apkg`).
3.  `anki_model_name` (Optional): The name of the OpenRouter model to use for generating Anki card content (front/back) from the text. If omitted, uses `default_anki_model` from `config.json`. If no default is set, an error occurs.

**Behavior**
*   Reads the content of `text_file`.
*   Sends the text to the specified (or default) `anki_model_name` via OpenRouter to generate card structures (front/back pairs).
*   The raw JSON response from the model is saved next to the `.apkg` file (e.g., `my_deck.json`).
*   Creates an Anki deck with these cards.
*   Logs generation activity to `anki_generation_*.log`.

**Examples**

1.  **Convert text to Anki using the default Anki model**
    ```bash
    # Assumes 'default_anki_model' (e.g. openai/chatgpt-4o-latest) is configured
    pdf2anki text2anki study_notes.txt history_deck.apkg
    ```

2.  **Specify the Anki generation model explicitly**
    ```bash
    pdf2anki text2anki chapter_summary.txt physics_cards.apkg google/gemini-2.0-flash-001
    ```

---

## 5. `json2anki` Command

**Purpose**  
Convert a JSON file containing flashcards into an Anki package without invoking an LLM. Each card must have `front` and `back` keys, with optional fields for advanced organization. Also supports bulk processing of all JSON files in a directory.

**Supported JSON Format**
Each flashcard is a JSON object with the following fields:
- **Required**: `front` (string), `back` (string)
- **Optional**: 
  - `tags` (array of strings): Categorization tags for the card
  - `guid` (string): Unique identifier to prevent duplicates on reimport
  - `sort_field` (string): Custom sort value for organizing cards in Anki browser
  - `due` (integer): Days from today when card should first appear (default: 0)

**Syntax**  
```bash
pdf2anki json2anki json_file_or_directory [anki_file] [OPTIONS...]
```

**Positional Arguments**
1.  `json_file_or_directory`: Path to the input JSON file containing flashcards, or a directory containing multiple JSON files for bulk processing.
2.  `anki_file` (Optional): Path for the output Anki package file (e.g., `my_deck.apkg`). If not provided, the output file will be automatically generated with the same name as the input file but with a `.apkg` extension. This parameter is ignored when processing a directory (bulk mode).

**Optional Arguments**

| Parameter | Description |
|-----------|-------------|
| `--show-format` | Print the expected JSON format structure and exit. Useful for understanding the required input format. |

**Behavior**
*   **Single File Mode**: Reads a JSON file containing an array of flashcard objects, each with `front` and `back` properties.
*   **Bulk Processing Mode**: When a directory is provided, processes all `.json` files in that directory, creating corresponding `.apkg` files with the same base names.
*   Creates an Anki deck with the specified name (derived from the output filename).
*   No LLM is invoked - this is a direct, offline conversion.
*   With `--show-format`, displays the expected JSON structure and exits without requiring input files.
*   If no output file is specified (single file mode), automatically creates an `.apkg` file in the same directory as the input file.

**Examples**  

1.  **Show the expected JSON format:**
    ```bash
    pdf2anki json2anki --show-format
    ```
    **Output:**
    ```
    Example input format for flashcards in JSON:

    [
      { 
        "front": "Was ist ein Neuron?", 
        "back": "Eine Einheit in einem neuronalen Netz.",
        "tags": ["neuroscience", "basics"]
      },
      { 
        "front": "Gradientenabstieg?", 
        "back": "Ein Optimierungsalgorithmus.",
        "tags": ["machine-learning", "optimization"],
        "guid": "ml-gradient-descent-001",
        "sort_field": "02_Advanced",
        "due": 3
      },
      {
        "front": "Simple card without optional fields",
        "back": "All optional fields are optional - backward compatibility maintained"
      }
    ]
    ```

2.  **Convert a single JSON list of cards into an Anki deck with explicit output file:**
    ```bash
    pdf2anki json2anki cards.json my_deck.apkg
    ```

3.  **Convert a single JSON list of cards with automatic output file naming:**
    ```bash
    pdf2anki json2anki cards.json
    ```
    *This will automatically create `cards.apkg` in the same directory as `cards.json`.*

4.  **Convert with relative path (automatic naming):**
    ```bash
    pdf2anki json2anki ./collection_1_Metaethik.json
    ```
    *This will automatically create `./collection_1_Metaethik.apkg`.*

5.  **Bulk processing - convert all JSON files in a directory:**
    ```bash
    pdf2anki json2anki .
    ```
    *This will convert all `.json` files in the current directory to corresponding `.apkg` files.*

6.  **Bulk processing - convert all JSON files in a specific directory:**
    ```bash
    pdf2anki json2anki /path/to/json/files/
    ```
    *This will convert all `.json` files in the specified directory to corresponding `.apkg` files in the same directory.*

---

## 6. `process` Command (Full Pipeline)

**Purpose**
Automates the entire workflow for a **single PDF**:
1.  PDF to images.
2.  Images to text (OCR).
3.  Text to Anki deck.

**Syntax**
```bash
pdf2anki process <pdf_path> <images_output_dir> <anki_file> [anki_model_name] [OCR_OPTIONS...]
```

**Positional Arguments**
1.  `pdf_path`: Path to the input PDF file.
2.  `images_output_dir`: Directory to store intermediate images generated from the PDF.
3.  `anki_file`: Path for the final output Anki package file.
4.  `anki_model_name` (Optional): Model for the Anki card generation step (step 3). Resolved similarly to `text2anki` (uses `default_anki_model` if omitted).

**Optional OCR Arguments (OCR_OPTIONS...)**
These options apply to the images-to-text (OCR) step (step 2) of the pipeline:
*   `-d`, `--default`: Use preset OCR settings from `config.json` (`defaults` key).
*   `--model <MODEL_NAME>`, `--repeat <N>`, `--judge-model <MODEL_NAME>`, `--judge-mode <MODE>`, `--judge-with-image`, `--no-resume`, `--max-page-attempts <N>`, etc.: Same as for `pic2text`. If no OCR model is specified via these options or `-d`, `default_model` from config is used.

**Important Note on Cropping**
The `process` command **does not** support explicit cropping arguments. If you need to crop the PDF pages, you must perform the steps manually:
1.  `pdf2anki pdf2pic ... [rectangles...]` (to get cropped images)
2.  `pdf2anki pic2text ...` (on the directory of cropped images)
3.  `pdf2anki text2anki ...`

**Behavior**
*   The three main steps are executed sequentially for the single input PDF.
*   A temporary text file is created for the intermediate OCR output.

**Examples**

1.  **Full pipeline using default OCR and Anki models**
    ```bash
    # Assumes 'default_model' (e.g. google/gemini-2.0-flash-001) and 'default_anki_model' (e.g. openai/chatgpt-4o-latest) are configured
    pdf2anki process textbook_chapter.pdf temp/chapter_images/ chapter_deck.apkg
    ```

2.  **Using preset OCR defaults (`-d`) and a specific Anki model**
    ```bash
    # Assumes 'defaults' (for OCR) is configured
    pdf2anki process lecture.pdf intermediate_pics/ lecture.apkg google/gemini-2.0-flash-001 -d
    ```

3.  **Specify OCR models and Anki model explicitly**
    ```bash
    pdf2anki process research.pdf ./img_cache/ research.apkg openai/chatgpt-4o-latest \
        --model google/gemini-2.0-flash-001 --model openai/chatgpt-4o-latest \
        --judge-model google/gemini-2.0-flash-001 \
        --judge-with-image
    ```
    - OCR uses `google/gemini-2.0-flash-001` and `openai/chatgpt-4o-latest` with `google/gemini-2.0-flash-001` as judge.
    - Anki generation uses `openai/chatgpt-4o-latest` (the positional `anki_model_name`).

---

---

## 7. Advanced: SSOT text2anki Workflow

For larger learning projects with multiple card collections, `pdf2anki` includes a structured **Single-Source-of-Truth (SSOT)** workflow. All cards live in one `card_database.json`; derived files (per-collection JSON, Markdown index, `.apkg`) are generated from it.

This workflow is designed for semester-long use: ingest lecture notes chapter by chapter, exercise sheets week by week, and your own annotations — the database grows incrementally while always producing a clean, exportable Anki deck.

### Project structure

```
my_project/
  project.json                      ← project configuration (edit once)
  card_database.json                ← SSOT: all cards live here (do not edit manually)
  collection_0_Kapitel1.json        ← derived, regenerated from SSOT
  collection_1_Kapitel2.json
  All_collections_only_fronts.md    ← human-readable card index
  new_cards_output.json             ← LLM-generated candidates (pending integration)
  new_cards_output.json.processed_* ← archived after successful integration
```

### Setup

```bash
# Initialize a new project (creates project.json template)
pdf2anki workflow --init "MeinKurs" --project ./my_project/

# Then edit project.json to define collections, language, domain, LLM model
```

**`project.json` minimal example:**
```json
{
  "project_name": "MeinKurs",
  "tag_prefix": "MEINKURS",
  "language": "de",
  "domain": "Organische Chemie",
  "orphan_collection_name": "Unsortierte_Karten",
  "files": {
    "db_path": "card_database.json",
    "markdown_file": "All_collections_only_fronts.md",
    "new_cards_file": "new_cards_output.json"
  },
  "collections": {
    "collection_0_Grundlagen": {
      "display_name": "Kapitel 1: Grundlagen",
      "description": "Einführende Konzepte"
    },
    "collection_1_Vertiefung": {
      "display_name": "Kapitel 2: Vertiefung"
    }
  },
  "llm": { "model": "google/gemini-2.5-flash", "temperature": 0.1 }
}
```

### Workflow commands

All commands use `pdf2anki workflow --project ./my_project/` (or the equivalent `python -m pdf2anki workflow`):

```bash
# --- First time: bootstrap from legacy files (if you have existing collection JSON + markdown) ---
pdf2anki workflow --project ./my_project/ --extract --auto-all

# --- Regular semester workflow ---

# 1. Ingest new text → LLM generates card candidates → new_cards_output.json
pdf2anki workflow --project ./my_project/ --ingest chapter3_notes.txt

# 2. Integrate candidates into the SSOT database
pdf2anki workflow --project ./my_project/ --integrate

# 3. Export to Anki (.apkg files, one per collection)
pdf2anki workflow --project ./my_project/ --export

# --- Optional: force sync derived files without touching the database ---
pdf2anki workflow --project ./my_project/ --sync
```

**Typical semester rhythm:**
```
Week 1:  --ingest kapitel1.txt  →  --integrate  →  --export
Week 2:  --ingest uebungsblatt1.txt  →  --integrate  →  --export
Week 3:  --ingest kapitel2.txt uebungsblatt2.txt  →  --integrate  →  --export
...
Exam:    --export  (re-export the accumulated deck at any time)
```

💡 **Tip:** You can pass multiple files to `--ingest` in one call. The LLM sees all of them and assigns cards to the appropriate collection based on the project context defined in `project.json`.

**Bootstrap flags** (avoid interactive prompts during `--extract`):

| Flag | Effect |
|------|--------|
| `--auto-rescue-orphans` | Save orphaned cards (only in collection, not in markdown) to a new collection |
| `--auto-skip-conflicts` | Use first back when multiple backs exist for the same front |
| `--auto-create-missing` | Create TODO cards for fronts without backs |
| `--auto-ignore-orphans` | Drop orphaned cards silently |
| `--auto-all` | Enable rescue + skip-conflicts + create-missing |
| `--force` | Skip the "overwrite DB?" confirmation prompt |
| `--skip-export` | Don't write `.apkg` files after extract/integrate |

**LLM-assist flags** (for `--extract`/`--bootstrap`):

| Flag | Effect |
|------|--------|
| `--llm-resolve-conflicts` | Ask LLM to choose the best back for conflicting answers |
| `--llm-complete-backs` | Ask LLM to generate missing backs |
| `--llm-categorize-orphans` | Ask LLM to assign orphaned cards to the right collection |
| `--llm-all` | Enable all LLM-assist features |

### Duplicate detection

The workflow includes two layers of duplicate detection during `--integrate`:

1. **Text normalization** (always active): Exact string matches on normalized front text (whitespace- and case-insensitive) are rejected as duplicates.

2. **LLM semantic dedup** (active by default): Before inserting candidates, the LLM is asked to identify conceptually identical cards that differ in wording. For example, cards about the same theorem written with different LaTeX notation or phrasing are caught here.

**Known limitation — multi-source semantic overlap:** When you ingest material from multiple sources covering the same topic (e.g., a lecture chapter, then the corresponding exercise sheet, then tutorial notes), the LLM dedup catches most but not all conceptually redundant cards. Cards with low surface-text overlap but the same underlying concept — e.g., "What is an alphabet?" (from the lecture) vs. "Is ℤ an alphabet? Why not?" (from the exercises) — may both be accepted because they frame the same concept as different question types.

This is by design: exercise-style application cards complement definition cards and have value even when they test the same underlying knowledge. If you want stricter dedup, review `new_cards_output.json` before running `--integrate` and remove candidates manually.

---

## Testing

The test suite covers all modules with mocked external dependencies — no network, no real PDFs required.

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
python -m pytest tests/ -v

# Run a specific module
python -m pytest tests/test_database_manager.py -v
```

> **Note:** A small number of integration tests in `test_regression_e2e.py` make real LLM API calls and require `OPENROUTER_API_KEY` to be set. All other tests are fully offline.

| Test file | What it covers |
|-----------|----------------|
| `test_card.py` | `AnkiCard` serialization, defaults, roundtrip |
| `test_project_config.py` | `ProjectConfig` loading, validation, path helpers |
| `test_database_manager.py` | SSOT load/save/find/integrate/bootstrap/distribute |
| `test_text_ingester.py` | LLM prompt building, response parsing, file ingestion |
| `test_apkg_exporter.py` | `.apkg` generation, stable IDs, collection grouping |
| `test_text2anki_init.py` | `convert_text_to_anki`, `convert_json_to_anki` |
| `test_pdf2pic.py` | DPI finding, full-page and crop-mode conversion |
| `test_pic2text.py` | OCR state machine, resume/pause, API mocking |
| `test_core_config.py` | `load_config`, `save_config`, `get_default_model` |
| `test_regression_e2e.py` | End-to-end workflow regression tests |
| `test_real_data_and_sync.py` | SSOT sync, integrity verification |
| `test_specification.py` | Behavioral specification tests |

---

## Project Layout

```
pdf2anki/
  core.py               ← CLI entry point (pdf2anki / python -m pdf2anki)
  pdf2pic.py            ← PDF → image conversion (pymupdf)
  pic2text.py           ← OCR via OpenRouter (multi-model, resume/pause)
  text2anki/
    __init__.py         ← convert_text_to_anki, convert_json_to_anki
    card.py             ← AnkiCard dataclass (SSOT data model)
    project_config.py   ← ProjectConfig (loads project.json)
    database_manager.py ← SSOT operations (bootstrap, integrate, distribute, dedup)
    text_ingester.py    ← TextFileIngestor (text → card candidates via LLM)
    apkg_exporter.py    ← ApkgExporter (cards → .apkg via genanki)
    workflow_manager.py ← WorkflowManager (orchestrates SSOT workflows; entry point for `pdf2anki workflow`)
    llm_helper.py       ← get_llm_decision() via OpenRouter (auto-loads .env)
    material_manager.py ← Course material loading (workflow_config.json)
    prompt_updater.py   ← LLM prompt template management
tests/
  conftest.py + test_*.py   ← 364 tests; most fully offline, a few require OPENROUTER_API_KEY
```

---

## Conclusion

`pdf2anki` provides a flexible and powerful suite of tools for converting PDF documents into Anki flashcards.

Remember to configure your `OPENROUTER_API_KEY`. For any commercial or server-based usage, please contact **martinkrausemediaATgmail.com** for licensing inquiries.
