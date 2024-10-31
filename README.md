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
