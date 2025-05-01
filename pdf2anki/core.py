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
import os
import json
import sys # Import sys for sys.exit
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path
from . import pdf2pic
from . import pic2text
from . import text2anki

# --- Configuration Management ---

CONFIG_DIR = Path.home() / ".pdf2anki"
CONFIG_FILE = CONFIG_DIR / "config.json"

def load_config() -> Dict[str, Any]:
    """Loads configuration from the JSON file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            print(f"[WARN] Could not read config file at {CONFIG_FILE}. Using empty config.")
            return {}
    return {}

def save_config(config: Dict[str, Any]) -> None:
    """Saves configuration to the JSON file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    except IOError:
        print(f"[ERROR] Could not write config file to {CONFIG_FILE}.")

def get_default_model(config: Dict[str, Any]) -> Optional[str]:
    """Gets the default model from config, prompting if necessary."""
    if "default_model" in config and config["default_model"]:
        return config["default_model"]
    else:
        print("No default OCR model set.")
        model_name = input("Please enter the name of the default model to use (e.g., google/gemini-flash-1.5): ").strip()
        if model_name:
            config["default_model"] = model_name
            save_config(config)
            print(f"Default model set to: {model_name}")
            return model_name
        else:
            print("No model name entered. Cannot proceed without a model.")
            return None

def get_default_anki_model(config: Dict[str, Any]) -> Optional[str]:
    """Gets the default anki model from config."""
    return config.get("default_anki_model")

def get_preset_defaults(config: Dict[str, Any]) -> Dict[str, Any]:
    """Gets the preset default settings from config."""
    return config.get("defaults", {})

# --- End Configuration Management ---


def pdf_to_images(args: argparse.Namespace) -> None:
    """
    Convert a PDF file into a sequence of images, optionally cropping.
    Passes verbose flag down.
    
    Args:
        args: Namespace containing:
            - pdf_path (str): Path to the PDF file
            - output_dir (str): Directory to save output images
            - rectangles (List[str]): Optional list of rectangle coordinates as strings
    
    Calls:
        pdf2pic.convert_pdf_to_images(
            pdf_path: str,
            output_dir: str, 
            rectangles: List[Tuple[int, int, int, int]]
        ) -> List[str]
    """
    # 1. Convert the list of rectangle strings into tuples
    parsed_rectangles = []
    for rect_str in args.rectangles:
        parsed_rectangles.append(pdf2pic.parse_rectangle(rect_str))

    # 2. Pass them along to the function, including verbose flag
    pdf2pic.convert_pdf_to_images(
        pdf_path=args.pdf_path,
        output_dir=args.output_dir,
        rectangles=parsed_rectangles,
        verbose=getattr(args, 'verbose', False) # Pass verbose flag
    )


def images_to_text(args: argparse.Namespace) -> None:
    """
    Perform OCR on a directory of images, extracting text and saving it to a file.
    Includes logic to:
      - Handle single or multiple models.
      - Optionally invoke a judge model when multiple models are specified.
      - Respect the --repeat argument for repeated calls to each model.
      - Ignore ensemble-strategy and trust-score placeholders.
      - Optionally feed the judge the base64-encoded image (if --judge-with-image is used).
    
    Args:
        args: Namespace containing:
            - images_dir (str): Directory containing input images
            - output_file (str): Path to save extracted text
            - model (List[str]): List of OCR model names
            - repeat (List[int]): Number of calls per model
            - judge_model (Optional[str]): Model for choosing best result
            - judge_mode (str): Mode for judge decisions
            - ensemble_strategy (Optional[str]): Strategy for combining results
            - trust_score (Optional[float]): Model weighting factor
            - judge_with_image (bool): Whether to show image to judge
    
    Calls:
        pic2text.convert_images_to_text(
            images_dir: str,
            output_file: str,
            model_repeats: List[Tuple[str, int]],
            judge_model: Optional[str],
            judge_mode: str,
            ensemble_strategy: Optional[str],
            trust_score: Optional[float],
            judge_with_image: bool
        ) -> str
    """
    # Temporarily collect all remaining args
    remaining = []
    config = load_config() # Load config for potential default model

    # --- Model Handling ---
    models_to_use = args.model
    if not models_to_use:
        # If no model specified via CLI, try getting default from config
        default_model = get_default_model(config)
        if default_model:
            models_to_use = [default_model]
            print(f"[INFO] Using default model: {default_model}")
        else:
            # If still no model (user didn't provide one when prompted), raise error
            raise ValueError("No OCR model specified or configured. Use --model or set a default via 'pdf2anki config set default_model <name>'.")

    if args.model: # Use models from args if provided
        for idx, model_name in enumerate(args.model):
            rp = 1
            if args.repeat and idx < len(args.repeat):
                rp = args.repeat[idx]
            remaining.append((model_name, rp))
    elif models_to_use: # Use default model if args.model was empty but we got a default
         for idx, model_name in enumerate(models_to_use):
            rp = 1
            # Apply repeats if they were somehow passed even without explicit --model
            if args.repeat and idx < len(args.repeat):
                rp = args.repeat[idx]
            remaining.append((model_name, rp))

    # --- End Model Handling ---


    pic2text.convert_images_to_text(
        images_dir=args.images_dir,
        output_file=args.output_file,
        model_repeats=remaining,        # pass list of (model, repeat)
        judge_model=args.judge_model,
        judge_mode=args.judge_mode,
        ensemble_strategy=args.ensemble_strategy, # Ignored internally
        trust_score=args.trust_score,             # Ignored internally
        judge_with_image=args.judge_with_image
    )

def pdf_to_text(args: argparse.Namespace) -> None:
    """
    Full pipeline: Convert a PDF to images, then extract text.
    Handles default output_dir and output_file, default model, and -d flag.
    
    Args:
        args: Namespace containing combination of all arguments from:
            - pdf_to_images()
            - images_to_text() 
    """
    pdf_path = Path(args.pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {args.pdf_path}")

    # --- Determine output_dir ---
    output_dir_path: Path
    if args.output_dir:
        output_dir_path = Path(args.output_dir)
    else:
        # Default: ./pdf2pic/<pdf_name_without_ext>/
        pdf_name_stem = pdf_path.stem
        output_dir_path = Path.cwd() / "pdf2pic" / pdf_name_stem
        print(f"[INFO] Defaulting output_dir to: {output_dir_path}")
    output_dir_path.mkdir(parents=True, exist_ok=True)
    args.output_dir = str(output_dir_path) # Update args for pdf_to_images

    # --- Determine output_file ---
    output_file_path: Path
    if args.output_file:
        output_file_path = Path(args.output_file)
    else:
        # Default: ./<pdf_name_without_ext>.txt
        pdf_name_stem = pdf_path.stem
        output_file_path = Path.cwd() / f"{pdf_name_stem}.txt"
        print(f"[INFO] Defaulting output_file to: {output_file_path}")
    args.output_file = str(output_file_path) # Update args for images_to_text

    # --- Handle -d/--default flag ---
    config = load_config()
    if args.use_defaults:
        preset_defaults = get_preset_defaults(config)
        if preset_defaults:
            print("[INFO] Applying preset default settings (-d flag used).")
            # Override args with defaults ONLY if they weren't explicitly set via CLI
            # We check if the value in args is the default value set by argparse
            # Note: This requires knowing argparse's defaults. Adjust if needed.
            parser_defaults = { # Defaults defined in the parser setup below
                'model': [], 'repeat': [], 'judge_model': None,
                'judge_mode': 'authoritative', 'judge_with_image': False
            }
            for key, default_val in parser_defaults.items():
                if getattr(args, key) == default_val and key in preset_defaults:
                    setattr(args, key, preset_defaults[key])
                    print(f"[INFO] Using default for --{key.replace('_', '-')}: {preset_defaults[key]}")
        else:
            print("[WARN] -d flag used, but no defaults found in config. Use 'pdf2anki config set defaults ...' to define them.")
            sys.exit(1) # Exit if -d used and no defaults are set

    # --- Call pdf_to_images ---
    # Create a temporary namespace for pdf_to_images if needed, passing verbose
    pdf_args = argparse.Namespace(
        pdf_path=args.pdf_path,
        output_dir=args.output_dir,
        rectangles=args.rectangles,
        verbose=getattr(args, 'verbose', False) # Pass verbose flag
    )
    pdf_to_images(pdf_args)

    # --- Call images_to_text ---
    # Create proper namespace for images_to_text
    images_args = argparse.Namespace(
        images_dir=args.output_dir, # Use the determined/created output_dir
        output_file=args.output_file, # Use the determined output_file
        model=args.model,
        repeat=args.repeat,
        judge_model=args.judge_model,
        judge_mode=args.judge_mode,
        ensemble_strategy=args.ensemble_strategy, # Ignored internally
        trust_score=args.trust_score,             # Ignored internally
        judge_with_image=args.judge_with_image
    )
    images_to_text(images_args)


def text_to_anki(args: argparse.Namespace) -> None:
    """
    Convert a text file into an Anki-compatible format, creating an Anki deck.
    
    Args:
        args: Namespace containing:
            - text_file (str): Path to input text file
            - anki_file (str): Path to save Anki deck
            - model (str): Name of the OpenRouter model to use
    """
    # Load config to potentially get default anki model if needed
    config = load_config()
    anki_model_to_use = args.anki_model
    if not anki_model_to_use:
        # If no model specified via CLI, try getting default from config
        default_anki_model = get_default_anki_model(config)
        if default_anki_model:
            anki_model_to_use = default_anki_model
            print(f"[INFO] Using default Anki model: {default_anki_model}")
        else:
            # If still no model, raise error (as anki_model is required)
            raise ValueError("No Anki model specified and no default configured. Use the anki_model argument or set a default via 'pdf2anki config set default_anki_model <name>'.")

    text2anki.convert_text_to_anki(args.text_file, args.anki_file, anki_model_to_use)


def process_pdf_to_anki(args: argparse.Namespace) -> None:
    """
    Full pipeline: Convert a PDF to images, then extract text, and finally create an Anki deck.
    Passes verbose flag down.
    
    Args:
        args: Namespace containing combination of all arguments from:
            - pdf_to_images()
            - images_to_text() 
            - text_to_anki()
    """
    # Intermediate file paths - use a more robust temp file handling if needed
    # For simplicity, let's derive temp text file name from anki file name
    anki_path = Path(args.anki_file)
    output_text_file = anki_path.with_name(f"{anki_path.stem}_temp_ocr.txt")

    # --- Call pdf_to_images ---
    pdf_args = argparse.Namespace(
        pdf_path=args.pdf_path,
        output_dir=args.output_dir,
        rectangles=[], # process command doesn't take rectangles
        verbose=getattr(args, 'verbose', False) # Pass verbose flag
    )
    pdf_to_images(pdf_args)

    # --- Call images_to_text ---
    # Temporarily collect model/repeat args
    remaining = []
    config = load_config() # Load config for potential default model
    models_to_use = args.model
    if not models_to_use:
        default_model = get_default_model(config)
        if default_model:
            models_to_use = [default_model]
            print(f"[INFO] Using default model: {default_model}")
        else:
            raise ValueError("No OCR model specified or configured for 'process' command.")

    if args.model: # Use models from args if provided
        for idx, model_name in enumerate(args.model):
            rp = 1
            if args.repeat and idx < len(args.repeat):
                rp = args.repeat[idx]
            remaining.append((model_name, rp))
    elif models_to_use: # Use default model
         for idx, model_name in enumerate(models_to_use):
            rp = 1
            if args.repeat and idx < len(args.repeat):
                rp = args.repeat[idx]
            remaining.append((model_name, rp))


    images_args = argparse.Namespace(
        images_dir=args.output_dir,
        output_file=str(output_text_file), # Use temp text file
        model_repeats=remaining,
        judge_model=args.judge_model,
        judge_mode=args.judge_mode,
        ensemble_strategy=args.ensemble_strategy,
        trust_score=args.trust_score,
        judge_with_image=args.judge_with_image
    )
    images_to_text(images_args) # Call the function directly

    # --- Call text_to_anki ---
    # Load config to potentially get default anki model if needed
    anki_model_to_use = args.anki_model # Get from process args
    if not anki_model_to_use:
        default_anki_model = get_default_anki_model(config)
        if default_anki_model:
            anki_model_to_use = default_anki_model
            print(f"[INFO] Using default Anki model: {default_anki_model}")
        else:
            raise ValueError("No Anki model specified for 'process' command and no default configured.")

    text_args = argparse.Namespace(
        text_file=str(output_text_file),
        anki_file=args.anki_file,
        anki_model=anki_model_to_use # Pass the required anki model
    )
    text_to_anki(text_args)

    # --- Cleanup ---
    try:
        # Optionally remove the temporary text file
        # output_text_file.unlink()
        # print(f"[INFO] Removed temporary text file: {output_text_file}")
        pass # Keep temp file for now for debugging
    except OSError as e:
        print(f"[WARN] Could not remove temporary text file {output_text_file}: {e}")


# --- Config Command Functions ---

def view_config(args: argparse.Namespace) -> None:
    """Displays the current configuration."""
    config = load_config()
    if config:
        print(json.dumps(config, indent=2))
    else:
        print("Configuration is empty.")

def set_config_value(args: argparse.Namespace) -> None:
    """Sets a configuration value based on key and subsequent values."""
    config = load_config()
    key = args.key
    values = args.values

    if not values:
        print(f"[ERROR] No value provided for key '{key}'.")
        # Print specific usage based on key
        if key == "defaults":
             print(f"  Usage 1: pdf2anki config set defaults <setting_name> <value>")
             print(f"  Usage 2: pdf2anki config set defaults '<json_object>' (ensure shell quoting!)")
        elif key in ["default_model", "default_anki_model"]:
             print(f"  Usage: pdf2anki config set {key} <model_name>")
        else:
             print(f"  Usage: pdf2anki config set <key> <value>")
        return

    if key == "defaults":
        # Option 1: Set entire defaults object via JSON string
        if len(values) == 1:
            json_str = values[0]
            try:
                defaults_obj = json.loads(json_str)
                if not isinstance(defaults_obj, dict):
                    raise ValueError("Provided JSON is not an object (dictionary).")

                # Optional: Validate keys/types within the loaded object
                expected_defaults = {
                    "model": list, "repeat": list, "judge_model": (str, type(None)),
                    "judge_mode": str, "judge_with_image": bool
                }
                valid = True
                for k, expected_type in expected_defaults.items():
                    if k in defaults_obj and not isinstance(defaults_obj[k], expected_type):
                        print(f"[WARN] Type mismatch for '{k}' in defaults. Expected {expected_type}, got {type(defaults_obj[k])}.")
                        # Consider making this an error by setting valid = False
                # Add more validation as needed

                if valid:
                    config["defaults"] = defaults_obj
                    save_config(config)
                    print(f"Set 'defaults' using JSON object:")
                    print(json.dumps(defaults_obj, indent=2))
                else:
                     print("[ERROR] Invalid structure in provided JSON for 'defaults'. Not saved.")
                return # Processed JSON attempt

            except json.JSONDecodeError:
                # Add debug print to see what string was actually received
                print(f"[DEBUG] Received string for JSON parsing: '{json_str}'")
                print(f"[ERROR] Invalid JSON provided for 'defaults' value.")
                print("  Ensure the string is valid JSON and properly quoted/escaped for your shell.")
                print("  Example PowerShell (escape internal quotes): \"{\\\"\"model\\\"\": [\\\"\"m1\\\"\"], ...}\"")
                print("  Example Bash/Zsh (usually single quotes work): '{\\\"model\\\": [\\\"m1\\\"], ...}'")
                return
            except ValueError as e:
                 print(f"[ERROR] {e}")
                 return

        # Option 2: Set individual default setting
        elif len(values) == 2:
            subkey, value_str = values
            defaults = config.get("defaults", {}) # Get existing or empty dict

            # Process value based on subkey
            try:
                if subkey == "model":
                    defaults[subkey] = [m.strip() for m in value_str.split(',') if m.strip()]
                elif subkey == "repeat":
                    defaults[subkey] = [int(r.strip()) for r in value_str.split(',') if r.strip()]
                elif subkey == "judge_model":
                    defaults[subkey] = value_str if value_str.strip() else None
                elif subkey == "judge_mode":
                    defaults[subkey] = value_str
                elif subkey == "judge_with_image":
                    lower_val = value_str.lower()
                    if lower_val in ["true", "1", "yes", "on"]:
                        defaults[subkey] = True
                    elif lower_val in ["false", "0", "no", "off"]:
                        defaults[subkey] = False
                    else:
                        raise ValueError(f"Invalid boolean value: '{value_str}'. Use true/false.")
                else:
                    print(f"[ERROR] Unknown setting name for defaults: '{subkey}'")
                    print(f"  Valid setting names: model, repeat, judge_model, judge_mode, judge_with_image")
                    return

                config["defaults"] = defaults # Put updated dict back
                save_config(config)
                print(f"Set 'defaults.{subkey}' to: {defaults[subkey]}")

            except ValueError as e:
                print(f"[ERROR] Invalid value format for '{subkey}': {e}")
            except Exception as e:
                print(f"[ERROR] Failed to set 'defaults.{subkey}': {e}")

        # Invalid number of arguments for 'defaults'
        else:
             print(f"[ERROR] Invalid arguments for 'defaults'.")
             print(f"  Usage 1: pdf2anki config set defaults <setting_name> <value>")
             print(f"  Usage 2: pdf2anki config set defaults '<json_object>' (ensure shell quoting!)")
             return

    elif key in ["default_model", "default_anki_model"]:
        # ... (existing code for default_model/default_anki_model) ...
        if len(values) != 1:
            print(f"[ERROR] Usage: pdf2anki config set {key} <model_name>")
            return
        value_str = values[0]
        if isinstance(value_str, str) and value_str.strip():
            config[key] = value_str.strip()
            save_config(config)
            print(f"Set configuration key '{key}' to '{config[key]}'.")
        else:
            print(f"[ERROR] Invalid value for '{key}'. Must be a non-empty string.")

    else:
        print(f"[ERROR] Unknown configuration key: '{key}'. Valid keys: default_model, default_anki_model, defaults.")


# --- End Config Command Functions ---


def cli_invoke() -> None:
    """
    Command-line interface entry point. Sets up argument parsing and executes
    the appropriate function based on command. Includes global verbose flag and config command.
    """
    parser = argparse.ArgumentParser(
        description="Convert PDFs to Anki flashcards through a multi-step pipeline involving image extraction, OCR, and Anki formatting."
    )
    # Add global verbose flag
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output (e.g., debug logging)."
    )

    subparsers = parser.add_subparsers(title="Commands", dest="command", required=True)

    # --- PDF to Images Command ---
    parser_pdf2pic = subparsers.add_parser(
        "pdf2pic",
        help="Convert PDF pages into individual images.",
        description="This command converts each page of a PDF into a separate PNG image."
    )
    # ... arguments for pdf2pic ...
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

    # --- Images to Text Command ---
    parser_pic2text = subparsers.add_parser(
        "pic2text",
        help="Extract text from images using OCR.",
        description="This command performs OCR on images in a directory and saves the extracted text to a file."
    )
    # ... arguments for pic2text ...
    parser_pic2text.add_argument("images_dir", type=str, help="Directory containing images to be processed.")
    parser_pic2text.add_argument("output_file", type=str, help="File path to save extracted text.")
    parser_pic2text.add_argument(
        "--model",
        action="append",
        default=[],
        help="Name of an OCR model to use. Can be specified multiple times. If omitted, uses configured default."
    )
    parser_pic2text.add_argument(
        "--repeat",
        action="append",
        type=int,
        default=[],
        help="Number of times to call each model per image (default=1). Corresponds to --model by index."
    )
    parser_pic2text.add_argument(
        "--judge-model",
        type=str,
        default=None,
        help="Separate model to adjudicate multiple outputs. Required if using multiple models or repeat > 1."
    )
    parser_pic2text.add_argument(
        "--judge-mode",
        type=str,
        default="authoritative",
        choices=["authoritative"], # Only authoritative is implemented
        help="Judge mode ('authoritative')."
    )
    parser_pic2text.add_argument(
        "--ensemble-strategy",
        type=str,
        default=None,
        help="(Placeholder) Ensemble strategy. Not currently active."
    )
    parser_pic2text.add_argument(
        "--trust-score",
        type=float,
        default=None,
        help="(Placeholder) Per-model weighting factor. Not currently active."
    )
    parser_pic2text.add_argument(
        "--judge-with-image",
        action="store_true",
        default=False,
        help="If set, the judge model also receives the base64-encoded image."
    )
    parser_pic2text.set_defaults(func=images_to_text)


    # --- PDF to Text Command ---
    parser_pdf2text = subparsers.add_parser(
        "pdf2text",
        help="Convert a PDF directly to text (PDF -> Images -> Text). Infers output paths if omitted.",
        description="Converts PDF to images (stored in output_dir) and then extracts text to output_file. Output paths can be inferred."
    )
    # Arguments for pdf2text - output_dir and output_file are now optional
    parser_pdf2text.add_argument("pdf_path", type=str, help="Path to the PDF file.")
    parser_pdf2text.add_argument("output_dir", type=str, nargs='?', default=None, help="Directory to store intermediate images (default: ./pdf2pic/<pdf_name>/).")
    # Rectangles must come *before* the optional output_file
    parser_pdf2text.add_argument(
        "rectangles",
        type=str,
        nargs="*",
        default=[],
        help="Zero or more rectangles to crop, each in 'left,top,right,bottom' format."
    )
    parser_pdf2text.add_argument("output_file", type=str, nargs='?', default=None, help="File path to save extracted text (default: ./<pdf_name>.txt).")

    # Optional OCR flags (same as pic2text) + default flag
    parser_pdf2text.add_argument(
        "-d", "--default", dest="use_defaults",
        action="store_true",
        help="Use preset default OCR settings (model, repeat, judge) from config."
    )
    parser_pdf2text.add_argument(
        "--model", action="append", default=[],
        help="Name of an OCR model. Can be specified multiple times. Overrides default if set."
    )
    parser_pdf2text.add_argument(
        "--repeat", action="append", type=int, default=[],
        help="Number of times to call each model (default=1). Corresponds to --model by index."
    )
    parser_pdf2text.add_argument(
        "--judge-model", type=str, default=None,
        help="Separate model to adjudicate multiple outputs. Required if using multiple models or repeat > 1."
    )
    parser_pdf2text.add_argument(
        "--judge-mode", type=str, default="authoritative", choices=["authoritative"],
        help="Judge mode ('authoritative')."
    )
    parser_pdf2text.add_argument(
        "--ensemble-strategy", type=str, default=None,
        help="(Placeholder) Ensemble strategy. Not active yet."
    )
    parser_pdf2text.add_argument(
        "--trust-score", type=float, default=None,
        help="(Placeholder) Per-model weighting factor. Not currently active."
    )
    parser_pdf2text.add_argument(
        "--judge-with-image", action="store_true", default=False,
        help="If set, the judge model also receives the base64-encoded image."
    )
    parser_pdf2text.set_defaults(func=pdf_to_text)


    # --- Text to Anki Command ---
    parser_text2anki = subparsers.add_parser(
        "text2anki",
        help="Convert extracted text into an Anki-compatible format.",
        description="This command takes a text file and formats its contents as Anki flashcards, outputting an Anki package file."
    )
    parser_text2anki.add_argument("text_file", type=str, help="Path to the text file with content for Anki cards.")
    parser_text2anki.add_argument("anki_file", type=str, help="Output path for the Anki package file.")
    # Make anki_model optional here, will use default if not provided
    parser_text2anki.add_argument("anki_model", type=str, nargs='?', default=None, help="OpenRouter model for Anki cards (optional, uses default if configured).")
    parser_text2anki.set_defaults(func=text_to_anki)

    # --- Full Pipeline Command ---
    parser_process = subparsers.add_parser(
        "process",
        help="Run the entire pipeline: PDF -> Images -> Text -> Anki.",
        description="Automates the full process of converting a PDF to Anki flashcards."
    )
    # ... arguments for process ...
    parser_process.add_argument("pdf_path", type=str, help="Path to the PDF file.")
    parser_process.add_argument("output_dir", type=str, help="Directory to save intermediate images.")
    parser_process.add_argument("anki_file", type=str, help="Output path for the final Anki package file.")
    # Make anki_model optional here too
    parser_process.add_argument("anki_model", type=str, nargs='?', default=None, help="OpenRouter model for Anki cards (optional, uses default if configured).")

    # Add OCR arguments + default flag to process command
    parser_process.add_argument(
        "-d", "--default", dest="use_defaults",
        action="store_true",
        help="Use preset default OCR settings (model, repeat, judge) from config."
    )
    # ... add other OCR flags (--model, --repeat, etc.) identical to pdf2text ...
    parser_process.add_argument(
        "--model", action="append", default=[],
        help="Name of an OCR model. Can be specified multiple times. Overrides default if set."
    )
    parser_process.add_argument(
        "--repeat", action="append", type=int, default=[],
        help="Number of times to call each model (default=1). Corresponds to --model by index."
    )
    parser_process.add_argument(
        "--judge-model", type=str, default=None,
        help="Separate model to adjudicate multiple outputs. Required if using multiple models or repeat > 1."
    )
    parser_process.add_argument(
        "--judge-mode", type=str, default="authoritative", choices=["authoritative"],
        help="Judge mode ('authoritative')."
    )
    parser_process.add_argument(
        "--ensemble-strategy", type=str, default=None,
        help="(Placeholder) Ensemble strategy. Not active yet."
    )
    parser_process.add_argument(
        "--trust-score", type=float, default=None,
        help="(Placeholder) Per-model weighting factor. Not currently active."
    )
    parser_process.add_argument(
        "--judge-with-image", action="store_true", default=False,
        help="If set, the judge model also receives the base64-encoded image."
    )
    parser_process.set_defaults(func=process_pdf_to_anki)

    # --- Configuration Command ---
    parser_config = subparsers.add_parser(
        "config",
        help="View or modify configuration settings.",
        description="Manage configuration like default models and preset defaults."
    )
    config_subparsers = parser_config.add_subparsers(title="Config Actions", dest="config_action", required=True,
                                                   help='Configuration actions')

    # Config View
    parser_config_view = config_subparsers.add_parser("view", help="Show current configuration.")
    parser_config_view.set_defaults(func=view_config)

    # Config Set - Updated help text and description
    parser_config_set = config_subparsers.add_parser(
        "set",
        help="Set config: 'set <key> <value>' or 'set defaults <setting> <value>' or 'set defaults \"<json>\"'",
        description=(
            "Sets a configuration value.\n"
            "Examples:\n"
            "  pdf2anki config set default_model google/gemini-pro\n"
            "  pdf2anki config set defaults judge_model google/gemini-pro\n"
            "  pdf2anki config set defaults repeat 2\n"
            "  pdf2anki config set defaults judge_with_image true\n"
            "  pdf2anki config set defaults \"{\\\"\"model\\\"\": [\\\"\"google/gemini-pro\\\"\"], \\\"\"repeat\\\"\": [1]}\" (PowerShell example)\n"
            "  pdf2anki config set defaults '{\\\"model\\\": [\\\"google/gemini-pro\\\"], \\\"repeat\\\": [1]}' (Bash/Zsh example)"
        ),
        formatter_class=argparse.RawTextHelpFormatter # Allow newlines in description
        )
    parser_config_set.add_argument(
        "key",
        type=str,
        help="Config key ('default_model', 'default_anki_model', 'defaults')."
        )
    parser_config_set.add_argument(
        "values",
        nargs='*', # 0 or more values after the key
        help=(
            "Value(s) to set. See description for examples."
            )
        )
    parser_config_set.set_defaults(func=set_config_value)


    # --- Parse Arguments and Execute ---
    args = parser.parse_args()

    # Execute the function associated with the chosen command/subcommand
    # Check if a function was set (it should be if a command was provided)
    if hasattr(args, 'func'):
        args.func(args)
    else:
        # If no command was given (and argparse didn't exit), print help.
        parser.print_help()


if __name__ == "__main__":
    cli_invoke()