# BUILD.md

This `BUILD.md` provides instructions for building the `pdf2anki` project. You can choose between two build techniques:

1. **Technique 1 (Online)**: Using `python -m build --wheel`
2. **Technique 2 (Offline)**: Using `python setup.py bdist_wheel`

## Table of Contents

1. [Introduction](#introduction)
2. [Prerequisites](#prerequisites)
3. [Build Techniques](#build-techniques)
   - [Technique 1 (Online)](#technique-1-online-python--m-build---wheel)
   - [Technique 2 (Offline)](#technique-2-offline-python-setup.py-bdist_wheel)
4. [Conclusion](#conclusion)

## Introduction

`pdf2anki` is a CLI tool that converts PDF documents into Anki flashcards. It automates the process of creating study materials by extracting text from PDFs and formatting it for Anki.

## Prerequisites

- **Python 3.11** installed.
- Required packages as defined in `setup.py`.
- A virtual environment is recommended for dependency management.

## Build Techniques

### Technique 1 (Online): `python -m build --wheel`

This method requires an internet connection to fetch dependencies.

#### Step-by-Step Guide

1. **Ensure `pyproject.toml` is Present**:

   ```toml
   [build-system]
   requires = ["setuptools>=42", "wheel"]
   build-backend = "setuptools.build_meta"
   ```

2. **Install Required Packages**:

   ```sh
   pip install setuptools wheel build
   ```

3. **Build the Wheel**:

   ```sh
   python -m build --wheel
   ```

4. **Result**:

   The built wheel file will be located in the `dist` directory.

### Technique 2 (Offline): `python setup.py bdist_wheel`

This method can be executed offline if all dependencies are pre-installed.

#### Step-by-Step Guide

1. **Ensure `setup.py` is Present**:

   Confirm you have a valid `setup.py` file.

2. **Set Up Virtual Environment (Optional)**:

   ```sh
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Install Required Packages**:

   ```sh
   pip install setuptools wheel
   ```

4. **Build the Wheel**:

   ```sh
   python setup.py bdist_wheel
   ```

5. **Result**:

   The built wheel file will be placed in the `dist` directory.

## Conclusion

Choose the build technique that best suits your needs. For development purposes, you might frequently rebuild the package:

```sh
pip uninstall pdf2anki
python setup.py bdist_wheel
pip install .\dist\pdf2anki-{version}-py3-none-any.whl
```

By following this `BUILD.md`, you can effectively build the `pdf2anki` project using either method, ensuring flexibility for both online and offline scenarios.
```
