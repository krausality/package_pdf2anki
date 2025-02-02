# pdf2anki - Comprehensive User Guide

`pdf2anki` is a Python command-line tool that converts PDFs into Anki flashcards by utilizing a multi-step pipeline. This guide will provide an in-depth look at each function, offering clear examples and usage scenarios.

---

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Command-Line Interface (CLI) Usage](#command-line-interface-cli-usage)
   - [pdf2pic - Convert PDF to Images](#pdf2pic---convert-pdf-to-images)
   - [pic2text - Extract Text from Images](#pic2text---extract-text-from-images)
   - [text2anki - Convert Text to Anki Flashcards](#text2anki---convert-text-to-anki-flashcards)
   - [process - Run the Full Pipeline](#process---run-the-full-pipeline)
4. [Examples](#examples)
5. [Development and Contribution](#development-and-contribution)

---

## Overview

`pdf2anki` enables users to convert PDF files into Anki flashcards through a pipeline that includes:
1. Converting PDF pages to images,
2. Performing OCR (Optical Character Recognition) on the images,
3. Converting extracted text into Anki-compatible flashcards.

This functionality allows for efficient study material creation, particularly useful for academic and personal study purposes.

---

## Installation

To install `pdf2anki`, clone the repository and install the package in your Python environment:

```bash
git clone https://your-repo-url/pdf2anki.git
cd pdf2anki
pip install .
```

Ensure that you have `pytesseract`, `pdf2image`, `Pillow`, and `genanki` installed, as they are required dependencies.

---

## Command-Line Interface (CLI) Usage

All commands in `pdf2anki` follow the pattern:

```bash
python -m pdf2anki <command> [options]
```

### `pdf2pic` - Convert PDF to Images

This command converts each page of a PDF file into a separate image file.

**Usage:**

```bash
python -m pdf2anki pdf2pic <pdf_path> <output_dir>
```

**Arguments:**

- `pdf_path`: Path to the PDF file to be converted.
- `output_dir`: Directory where the images of each PDF page will be stored.

**Example:**

```bash
python -m pdf2anki pdf2pic sample.pdf images/
```

This example will save each page of `sample.pdf` as a PNG file in the `images` directory.

---

### `pic2text` - Extract Text from Images

This command uses OCR to extract text from images located in a directory and saves the text to a specified file.

**Usage:**

```bash
python -m pdf2anki pic2text <images_dir> <output_file>
```

**Arguments:**

- `images_dir`: Directory containing images to be processed by OCR.
- `output_file`: File path to save the OCR-extracted text.

**Example:**

```bash
python -m pdf2anki pic2text images/ extracted_text.txt
```

This example reads all images in the `images/` directory, performs OCR on them, and saves the extracted text to `extracted_text.txt`.

---

### `text2anki` - Convert Text to Anki Flashcards

This command formats text extracted from images into an Anki-compatible file, creating flashcards that can be imported into Anki.

**Usage:**

```bash
python -m pdf2anki text2anki <text_file> <anki_file>
```

**Arguments:**

- `text_file`: Path to the file containing text for Anki flashcards.
- `anki_file`: Output path for the final Anki package file (.apkg).

**Example:**

```bash
python -m pdf2anki text2anki extracted_text.txt flashcards.apkg
```

This example converts the content of `extracted_text.txt` into an Anki package `flashcards.apkg`.

---

### `process` - Run the Full Pipeline

The `process` command executes the full pipeline from PDF to Anki in a single step, managing all intermediate processes.

**Usage:**

```bash
python -m pdf2anki process <pdf_path> <output_dir> <anki_file>
```

**Arguments:**

- `pdf_path`: Path to the PDF file to be converted.
- `output_dir`: Directory for saving intermediate images.
- `anki_file`: Output path for the final Anki package file (.apkg).

**Example:**

```bash
python -m pdf2anki process sample.pdf temp_images/ flashcards.apkg
```

This example will:
1. Convert `sample.pdf` to images saved in `temp_images/`,
2. Extract text from these images,
3. Create an Anki package `flashcards.apkg` from the text.



---

## Enhanced Anki Card Generation

The Anki card generation process has been extended to use template‑driven OpenRouter calls.
Based on the input text’s context (e.g. philosophical essays, algorithm explanations, or math formulas), the system dynamically generates cards that either:
- Educate on factual key concepts and keywords.
- Provide step‑by‑step guidance on algorithms and problem-solving.
- Show mathematical formulas with explanations.

This solution emphasizes logging, archival of previous logs, and thorough error reporting to enable future enhancements and maintainability.

---

## Examples

Here are comprehensive examples covering all functions.

### Example 1: Converting PDF to Images

```bash
python -m pdf2anki pdf2pic document.pdf output_images/
```

After running this command, each page in `document.pdf` will appear as a PNG image in the `output_images/` folder.

### Example 2: Extracting Text from Images

```bash
python -m pdf2anki pic2text output_images/ text_output.txt
```

In this example, the images stored in `output_images/` are processed with OCR, and the text is saved in `text_output.txt`.

### Example 3: Converting Text to Anki Flashcards

```bash
python -m pdf2anki text2anki text_output.txt anki_deck.apkg
```

This command converts `text_output.txt` into Anki flashcards, outputting a file `anki_deck.apkg` for easy import into Anki.

### Example 4: Running the Entire Process from PDF to Anki

```bash
python -m pdf2anki process notes.pdf images_temp/ study_flashcards.apkg
```

In this command, the full pipeline is executed on `notes.pdf`, resulting in an Anki package file `study_flashcards.apkg`.

---

## Development and Contribution

To develop or modify the `pdf2anki` package, follow these steps:

1. **Clone the Repository**:

   ```bash
   git clone https://your-repo-url/pdf2anki.git
   cd pdf2anki
   ```

2. **Install in Editable Mode**:

   ```bash
   pip install -e .
   ```

3. **Run Tests and Make Changes**:
   - Implement tests to verify all functionalities before submitting changes.

4. **Submit a Pull Request**:
   - Fork the repository, make your changes, and submit a pull request.

For any questions or support requests, please contact Martin Krause at `martinkrausemedia@gmail.com`.

---

Happy studying with `pdf2anki`!



###############################


half assed CLI docu


Below is a comprehensive CLI manual for this script. We will walk through **all** available commands, **every** parameter, and provide **examples** for both typical and advanced scenarios. By the end, you should be able to utilize each subcommand independently or chain them together for a full pipeline (PDF → images → OCR text → Anki deck). 

---

## General Notes & License Summary

- **License & Usage Restrictions**  
  This software is licensed under the terms specified in `LICENSE.txt`, authored by Martin Krause.  
  **Usage is limited** to:
  1. Students enrolled at accredited institutions
  2. Individuals with an annual income below 15,000€
  3. **Personal desktop PC** automation tasks only  

  For commercial usage (including any server-based deployments), please contact the author at:  
  **[martinkrausemedia@gmail.com](mailto:martinkrausemedia@gmail.com)**  

  Refer to the `NOTICE.txt` file for details on dependencies and third-party libraries.

- **CLI Overview**  
  The script is invoked through a single binary/entry-point (e.g., `python mytool.py` or however you’ve packaged it), followed by a **command**. Each command has its own set of parameters and optional flags. 

  The main commands are:
  1. **pdf2pic** – Convert a PDF to individual images.
  2. **pic2text** – Perform OCR (text extraction) from a set of images.
  3. **pdf2text** – Single-step pipeline to go from PDF directly to text.
  4. **text2anki** – Convert a text file into an Anki deck/package.
  5. **process** – Full pipeline: PDF → images → text → Anki deck, in one go.

- **Installation / Invocation**  
  You might call this script like:
  ```bash
  python mytool.py COMMAND [OPTIONS...]
  ```
  or if installed as an executable:
  ```bash
  mytool COMMAND [OPTIONS...]
  ```
  In the examples below, we will assume `mytool` is your entry-point.

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
mytool pdf2pic PDF_PATH OUTPUT_DIR [RECTANGLE1 RECTANGLE2 ...]
```

### Examples

1. **Minimal usage (no cropping)**

   ```bash
   mytool pdf2pic mydocument.pdf output_images
   ```
   - Converts each page of `mydocument.pdf` into `output_images/page-1.png`, `output_images/page-2.png`, etc.

2. **Single rectangle**  
   ```bash
   mytool pdf2pic mydocument.pdf output_images 100,150,500,600
   ```
   - Converts each page into a cropped version from `(left=100, top=150)` to `(right=500, bottom=600)`.

3. **Multiple rectangles**  
   ```bash
   mytool pdf2pic mydocument.pdf output_images 50,100,300,400 320,100,600,400
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
| `--repeat N`         | Number of times to call each model per image (defaults to 1). If you provide multiple `--model` entries and multiple `--repeat` entries, each repeats entry corresponds to its respective model. |
| `--judge-model JM`   | If you have **multiple** OCR models, you can optionally specify a separate judge model to pick the best text. E.g., `--judge-model big-ocr-13b`. If not provided, the script may only run multiple models but not adjudicate the results (behavior may vary). |
| `--judge-mode MODE`  | Judge strategy. Currently only `"authoritative"` is implemented. If set, the judge simply picks the best result (the logic is inside your code).                                           |
| `--ensemble-strategy STR` | **(Placeholder)** e.g., `majority-vote`, `similarity-merge`. Not active in the code yet, so setting it won't do anything.                                                              |
| `--trust-score VAL`  | **(Placeholder)** float representing model weighting factor in an ensemble or judge scenario. Not active in the code yet.                                                                  |
| `--judge-with-image` | Boolean flag; if set, the judge model also sees the base64-encoded image when deciding among multiple OCR outputs.                                                                          |

**Usage**  
```bash
mytool pic2text IMAGES_DIR OUTPUT_FILE [--model MODEL...] [--repeat N...] 
      [--judge-model JM] [--judge-mode authoritative]
      [--ensemble-strategy STR] [--trust-score VAL] [--judge-with-image]
```

### Examples

1. **Single model, minimal usage**  
   ```bash
   mytool pic2text scanned_pages output.txt
   ```
   - OCR is done on images in `scanned_pages/` with a default or built-in model, saves text to `output.txt`.

2. **Single model, repeated calls**  
   ```bash
   mytool pic2text scanned_pages output.txt --model tesseract --repeat 3
   ```
   - For each image, runs `tesseract` OCR **3 times**.  
   - The script might merge or just pick the best of these repeated attempts (depending on your code logic).

3. **Multiple models, no judge**  
   ```bash
   mytool pic2text scanned_pages output.txt \
       --model tesseract --model google-vision
   ```
   - For each image, runs `tesseract` once and `google-vision` once.  
   - **No judge** specified, so your code might store or return multiple results. (Exact logic depends on your code; it might pick the first, or you might see the last overwriting, or it might fail if not supported—just be aware.)

4. **Multiple models, repeated calls, with judge**  
   ```bash
   mytool pic2text scanned_pages output.txt \
       --model tesseract --model google-vision \
       --repeat 2 --repeat 1 \
       --judge-model big-ocr-13b --judge-mode authoritative
   ```
   - Runs:
     - `tesseract` **2 times**  
     - `google-vision` **1 time**  
   - Then uses **`big-ocr-13b`** in “authoritative” mode to pick the best result per image.  
   - The final best text for each image is written to `output.txt`.

5. **Multiple models, judge with images**  
   ```bash
   mytool pic2text scanned_pages output.txt \
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
3. `rectangles` – Crop rectangles (zero or more), same syntax as in `pdf2pic`.  
4. `output_file` – Path to save the final text after OCR.

**Optional Arguments**  
Identical to the optional arguments for `pic2text`:

- `--model MODEL` (repeats allowed)  
- `--repeat N` (repeats allowed)  
- `--judge-model JM`  
- `--judge-mode MODE`  
- `--ensemble-strategy STR`  
- `--trust-score VAL`  
- `--judge-with-image`

**Usage**  
```bash
mytool pdf2text PDF_PATH IMAGES_DIR [RECT1 RECT2 ...] OUTPUT_FILE
      [--model MODEL...]
      [--repeat N...]
      [--judge-model JM]
      [--judge-mode authoritative]
      [--ensemble-strategy STR]
      [--trust-score VAL]
      [--judge-with-image]
```
  
Note that you can specify multiple rectangles at the end of the positionals before specifying the `OUTPUT_FILE`, or you can interleave them. The official argument order is:
```
pdf2text <pdf_path> <images_dir> [rectangles...] <output_file> [options...]
```

### Examples

1. **Minimal usage, no cropping**  
   ```bash
   mytool pdf2text notes.pdf temp_images output.txt
   ```
   - Step 1: `notes.pdf` → multiple pages in `temp_images/`.  
   - Step 2: OCR results → `output.txt`.

2. **With cropping**  
   ```bash
   mytool pdf2text notes.pdf temp_images 50,100,300,400 320,100,600,400 output.txt
   ```
   - Two cropped areas per PDF page → stored in `temp_images/`.  
   - Then OCR → final text in `output.txt`.

3. **Advanced: multiple OCR models, repeated calls, judge**  
   ```bash
   mytool pdf2text notes.pdf temp_images 100,150,500,600 output.txt \
       --model tesseract --model google-vision \
       --repeat 2 --repeat 2 \
       --judge-model big-ocr-13b \
       --judge-with-image
   ```
   - Crops each PDF page according to `(100,150,500,600)`.
   - For each cropped image:
     - `tesseract` is called 2 times
     - `google-vision` is called 2 times
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
mytool text2anki TEXT_FILE ANKI_FILE
```

### Examples

1. **Minimal**  
   ```bash
   mytool text2anki reading.txt flashcards.apkg
   ```
   - Converts `reading.txt` into an Anki package `flashcards.apkg`.

2. **After manual editing**  
   If you manually cleaned up the text from OCR, you might do:
   ```bash
   mytool text2anki cleaned_text.txt my_deck.apkg
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
- `--repeat N` (multiple allowed)  
- `--judge-model JM`  
- `--judge-mode MODE` (default `authoritative`)  
- `--ensemble-strategy STR` (placeholder)  
- `--trust-score VAL` (placeholder)  
- `--judge-with-image`  

**Usage**  
```bash
mytool process PDF_PATH OUTPUT_DIR ANKI_FILE
      [--model MODEL...]
      [--repeat N...]
      [--judge-model JM]
      [--judge-mode authoritative]
      [--ensemble-strategy STR]
      [--trust-score VAL]
      [--judge-with-image]
```

**Important Note on Cropping**  
The `process` command, as shown in the script, **does not** explicitly accept rectangles. If you need cropping, you must do it in multiple steps (e.g., call `pdf2pic` first, then `pic2text`, then `text2anki`). If you want to incorporate cropping, you could adapt the script or just do the pipeline in separate commands.

### Examples

1. **Minimal usage**  
   ```bash
   mytool process book.pdf images book.apkg
   ```
   - Step 1: `book.pdf` → images in `images/`.  
   - Step 2: OCR all images → some internal text file.  
   - Step 3: Creates `book.apkg` from that text.

2. **Multiple models, judge**  
   ```bash
   mytool process slides.pdf slides_images slides.apkg \
       --model tesseract --model google-vision \
       --judge-model big-ocr-13b \
       --judge-with-image
   ```
   - Generates final Anki deck `slides.apkg`, with improved OCR results.

3. **Model repeats**  
   ```bash
   mytool process slides.pdf slides_images slides.apkg \
       --model tesseract --model google-vision \
       --repeat 2 --repeat 1 \
       --judge-model big-ocr-13b
   ```
   - Calls `tesseract` 2 times, `google-vision` 1 time per image, judge picks best.

---

## Putting It All Together

Below are some additional sequences showing how you can build multi-step pipelines manually (for maximum control) or via single commands.

### A. Manual Multi-Step with Cropping

You want to crop the PDF in multiple areas and run advanced OCR:

1. **Step 1**: PDF → images with multiple crop zones
   ```bash
   mytool pdf2pic mynotes.pdf temp_images 50,100,300,400 400,100,600,300
   ```
2. **Step 2**: OCR from images to text, with repeated calls and judge
   ```bash
   mytool pic2text temp_images text_output.txt \
       --model tesseract --model google-vision \
       --repeat 3 --repeat 1 \
       --judge-model big-ocr-13b
   ```
3. **Step 3**: Convert text to Anki
   ```bash
   mytool text2anki text_output.txt final_flashcards.apkg
   ```

### B. Single-Step to Text (no deck)

If all you need is text (and optionally some rectangles for cropping):

```bash
mytool pdf2text mynotes.pdf images_dir 100,150,400,500 output.txt \
    --model google-vision
```

### C. Full Pipeline to Anki (no cropping)

If you just want the simplest route from PDF to a deck:

```bash
mytool process mynotes.pdf images_dir mydeck.apkg
```

---

## Conclusion

- **Subcommands**:  
  1. **`pdf2pic`** – Convert PDF pages to images (with optional cropping).  
  2. **`pic2text`** – Run OCR on a directory of images, optionally with multiple models and a judge.  
  3. **`pdf2text`** – Combine steps 1 and 2 into a single command, outputting text.  
  4. **`text2anki`** – Convert text into an Anki deck.  
  5. **`process`** – Automate the entire pipeline (PDF → images → text → Anki).

- **Cropping**:  
  Only possible through `pdf2pic` or `pdf2text`. The `process` command, as provided, does not accept cropping arguments.

- **Multiple Models & Judge**:  
  - Use `--model` multiple times (`--model m1 --model m2 …`).  
  - Pair each with `--repeat N` (they line up by index).  
  - Add `--judge-model` to pick the best result from all OCR attempts.  
  - `--judge-with-image` passes the images themselves to the judge model.

- **Ensemble & Trust Score**:  
  These placeholders (`--ensemble-strategy`, `--trust-score`) do not currently have active logic in the script. They exist for future expansion.

**Enjoy automating your PDF → OCR → Anki workflows!** If you require commercial/server usage, please remember to contact **[martinkrausemedia@gmail.com](mailto:martinkrausemedia@gmail.com)** for licensing.