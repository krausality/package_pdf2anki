md
# BUILD.md

Here is an exhaustive `BUILD.md` that explains the two build techniques: one using `python -m build --wheel` (which requires an internet connection for isolated builds), and the other using `python setup.py bdist_wheel` (which can be done offline).

This document details two techniques for building the `ds_autom8_cli` project.
Table of Contents

1. Introduction
2. Prerequisites
3. Build Techniques
    - Technique 1  (Online): `python -m build --wheel`
    - Technique 2 (Offline): `python setup.py bdist_wheel`
Introduction

This project handles the automation of multiple recurring tasks at the Datenstation. 
The project is licensed under the Custom Personal Use License v1.4; see LICENSE file for more information.
Prerequisites

Before building the project, ensure you have the following:

- Python 3.11 installed.
- Required packages listed in `requirements.txt` or as defined in `setup.py`.
- Virtual environment to manage dependencies (recommended).
Build Techniques
Technique 1: `python -m build --wheel`

This technique utilizes the `build` tool, which requires an internet connection for isolated builds.
Step-by-Step Guide

1. Ensure `pyproject.toml` is Present:

   ```toml
   [build-system]
   requires = ["setuptools>=42", "wheel"]
   build-backend = "setuptools.build_meta"
   ```

2. Install Required Packages:

   Ensure `build` and other build dependencies are installed:

   ```sh
   pip install setuptools wheel build
   ```

3. Build the Wheel:

   Navigate to the root directory of your project where `pyproject.toml` is located and execute:

   ```sh
   python -m build --wheel
   ```

4. Result:
   The built wheel file will be located in the `dist` directory.
Pros and Cons

- Pros:
  - Ensures a clean, isolated build environment.
  - Minimizes the impact of environment-specific issues.
- Cons:
  - Requires an internet connection to fetch dependencies.
Technique 2: `python setup.py bdist_wheel`

This technique uses the `setup.py` script, which can be executed offline if all dependencies are pre-installed.
Step-by-Step Guide

1. Ensure `setup.py` is Present:

   Ensure you have a valid `setup.py` (see repository or local folder)


2. Set Up Virtual Environment (optional):

   Create and activate a virtual environment:

   ```sh
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. Install Required Packages:

   Ensure all necessary packages are installed in the virtual environment:

   ```sh
   pip install setuptools wheel
   ```

4. Build the Wheel:

   In the project root directory, run:

   ```sh
   python setup.py bdist_wheel
   ```

5. Result:

   The built wheel file will be placed in the `dist` directory.
Pros and Cons

- Pros:
  - Can be run offline if all dependencies are pre-installed.
  - Offers control over the build environment without isolation.
- Cons:
  - Can be affected by environment-specific issues.
Conclusion

Both build techniques are viable, depending on your specific needs and constraints. Technique 1 ensures a clean, isolated environment but requires an internet connection, while Technique 2 can be run offline if dependencies are pre-installed but may be subject to environment-specific issues.

For consistency and ease of use, consider including both methods in your build pipeline, ensuring that you can build your project both online and offline as needed.


By following the steps in this `BUILD.md`, users can effectively build the project using either method, ensuring they have clear instructions for both online and offline scenarios.

For development (often rebuilding):
go to project root:

use this command:

pip uninstall ds_autom8_cli; python setup.py bdist_wheel; pip install .\dist\ds_autom8_cli-{version}-py3-none-any.whl