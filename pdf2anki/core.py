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
import sys
import traceback
import concurrent.futures # For parallel processing
from pathlib import Path # Ensure Path is imported here as it's used widely
from typing import List, Tuple, Optional, Dict, Any
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

def get_default_model(config: Dict[str, Any], interactive: bool = True) -> Optional[str]:
    """
    Gets the default model from config.
    Prompts only if in interactive mode and no default is set.
    """
    if "default_model" in config and config["default_model"]:
        return config["default_model"]
    
    # Only prompt if interactive is True (typically main thread)
    if interactive:
        # Check if running in an interactive terminal
        if not sys.stdin.isatty():
            # Non-interactive session (e.g., script piped or a worker process if called directly)
            # This part is more of a safeguard; model resolution should happen before workers.
            print(f"[{os.getpid() if hasattr(os, 'getpid') else 'main'}] INFO: get_default_model called in non-interactive mode and no default_model is set in config.")
            return None

        print("No default OCR model set in configuration.")
        try:
            model_name = input("Please enter the name of the default model to use (e.g., google/gemini-flash-1.5): ").strip()
            if model_name:
                config["default_model"] = model_name
                save_config(config) # Save the newly set default
                print(f"Default model set to: {model_name}")
                return model_name
            else:
                print("No model name entered.")
                return None
        except KeyboardInterrupt:
            print("\nModel input cancelled by user.")
            return None
        except EOFError: # Happens if stdin is closed, e.g. in some non-interactive contexts
            print("\nModel input stream closed. Cannot prompt for default model.")
            return None
    else:
        # Non-interactive call and no default_model in config
        return None


def get_default_anki_model(config: Dict[str, Any], interactive: bool = True) -> Optional[str]:
    """Gets the default anki model from config, with optional interactive prompt."""
    if "default_anki_model" in config and config["default_anki_model"]:
        return config["default_anki_model"]
    if interactive:
        if not sys.stdin.isatty():
            print(f"[{os.getpid() if hasattr(os, 'getpid') else 'main'}] INFO: get_default_anki_model called in non-interactive mode and no default_anki_model is set.")
            return None
        print("No default Anki generation model set in configuration.")
        try:
            model_name = input("Please enter the default Anki model (e.g., google/gemini-flash-1.5): ").strip()
            if model_name:
                config["default_anki_model"] = model_name
                save_config(config)
                print(f"Default Anki model set to: {model_name}")
                return model_name
            else:
                print("No Anki model name entered.")
                return None
        except KeyboardInterrupt:
            print("\nAnki model input cancelled.")
            return None
        except EOFError:
            print("\nAnki model input stream closed.")
            return None
    return None


def get_preset_defaults(config: Dict[str, Any]) -> Dict[str, Any]:
    """Gets the preset default settings from config."""
    return config.get("defaults", {})

# --- End Configuration Management ---


def pdf_to_images(args: argparse.Namespace) -> None:
    """
    Convert a PDF file into a sequence of images, optionally cropping.
    Passes verbose flag down.
    """
    pid_str = f"[{os.getpid() if hasattr(os, 'getpid') else 'main'}]"
    if getattr(args, 'verbose', False):
        print(f"{pid_str} pdf_to_images called for: {args.pdf_path}")

    parsed_rectangles = []
    for rect_str in args.rectangles:
        parsed_rectangles.append(pdf2pic.parse_rectangle(rect_str))

    pdf2pic.convert_pdf_to_images(
        pdf_path=args.pdf_path,
        output_dir=args.output_dir,
        rectangles=parsed_rectangles,
        verbose=getattr(args, 'verbose', False)
    )
    if getattr(args, 'verbose', False):
        print(f"{pid_str} pdf_to_images completed for: {args.pdf_path}")


def images_to_text(args: argparse.Namespace) -> None:
    """
    Perform OCR on a directory of images, extracting text and saving it to a file.
    This is a wrapper for pic2text.convert_images_to_text.
    It expects args.model to be already populated by the caller.
    """
    pid_str = f"[{os.getpid() if hasattr(os, 'getpid') else 'main'}]"
    if getattr(args, 'verbose', False):
        print(f"{pid_str} images_to_text (core wrapper) called for dir: {args.images_dir}")

    if not args.model: # args.model should be resolved by the caller (e.g., pdf_to_text or _process_pdf_worker)
        raise ValueError(f"{pid_str} images_to_text (core wrapper): No OCR model specified in args.model. This should be resolved by the calling function.")

    remaining_model_repeats = []
    for idx, model_name in enumerate(args.model): # Use the already resolved args.model
        rp = 1
        if args.repeat and idx < len(args.repeat):
            rp = args.repeat[idx]
        remaining_model_repeats.append((model_name, rp))
    
    if not remaining_model_repeats: # Should not happen if args.model was populated
        raise ValueError(f"{pid_str} images_to_text (core wrapper): No models and repeats configured after processing args.")

    pic2text.convert_images_to_text(
        images_dir=args.images_dir,
        output_file=args.output_file,
        model_repeats=remaining_model_repeats,
        judge_model=args.judge_model,
        judge_mode=args.judge_mode,
        ensemble_strategy=args.ensemble_strategy,
        trust_score=args.trust_score,
        judge_with_image=args.judge_with_image,
        verbose=getattr(args, 'verbose', False) # Pass verbose down
    )
    if getattr(args, 'verbose', False):
        print(f"{pid_str} images_to_text (core wrapper) completed for dir: {args.images_dir}")


def _process_pdf_worker(pdf_file_path_str: str, common_args_dict: dict) -> str:
    """
    Worker function to process a single PDF file.
    This function is executed in a separate process.
    `common_args_dict` should have `model` already resolved.
    """
    worker_args = argparse.Namespace(**common_args_dict)
    pdf_path = Path(pdf_file_path_str)
    pid = os.getpid()

    try:
        print(f"[{pid}] Starting processing for: {pdf_path.name}")

        pdf_name_stem = pdf_path.stem
        is_batch_mode = common_args_dict.get('_is_batch_mode', False)
        
        # Image output directory
        if is_batch_mode:
            base_image_dir = Path(worker_args.output_dir) if worker_args.output_dir else Path.cwd() / "pdf2pic"
            current_image_output_dir = base_image_dir / pdf_name_stem
        else:
            current_image_output_dir = Path(worker_args.output_dir) if worker_args.output_dir else Path.cwd() / "pdf2pic" / pdf_name_stem
        current_image_output_dir.mkdir(parents=True, exist_ok=True)

        # Text output file
        if is_batch_mode:
            base_text_dir = Path(worker_args.output_file) if worker_args.output_file else Path.cwd()
            if base_text_dir.suffix and base_text_dir.parent != Path('.'):
                base_text_dir = base_text_dir.parent
            current_text_output_file = base_text_dir / f"{pdf_name_stem}.txt"
        else:
            current_text_output_file = Path(worker_args.output_file) if worker_args.output_file else Path.cwd() / f"{pdf_name_stem}.txt"
        current_text_output_file.parent.mkdir(parents=True, exist_ok=True)

        pdf_to_images_args = argparse.Namespace(
            pdf_path=str(pdf_path),
            output_dir=str(current_image_output_dir),
            rectangles=worker_args.rectangles,
            verbose=getattr(worker_args, 'verbose', False)
        )
        
        # `worker_args.model` is passed here, which was resolved in the main thread
        images_to_text_args = argparse.Namespace(
            images_dir=str(current_image_output_dir),
            output_file=str(current_text_output_file),
            model=worker_args.model, # This is crucial - model is pre-resolved
            repeat=worker_args.repeat,
            judge_model=worker_args.judge_model,
            judge_mode=worker_args.judge_mode,
            ensemble_strategy=worker_args.ensemble_strategy,
            trust_score=worker_args.trust_score,
            judge_with_image=worker_args.judge_with_image,
            verbose=getattr(worker_args, 'verbose', False)
        )

        pdf_to_images(pdf_to_images_args)
        images_to_text(images_to_text_args) # Call the core.py wrapper

        success_msg = f"Successfully processed {pdf_path.name}"
        print(f"[{pid}] {success_msg}")
        return f"SUCCESS: {pdf_path.name}"

    except Exception as e:
        error_msg = f"ERROR processing {pdf_path.name} in process {pid}: {e}"
        detailed_error = f"{error_msg}\n{traceback.format_exc()}"
        print(f"[{pid}] {detailed_error}")
        return f"FAILURE: {pdf_path.name} - {e}"


def pdf_to_text(args: argparse.Namespace) -> None:
    """
    Converts a single PDF file or all PDF files in a directory to text.
    Uses parallel processing if multiple files are found in a directory.
    Model resolution happens here, in the main process.
    """
    input_path = Path(args.pdf_path)
    pdf_files_to_process: List[Path] = []
    is_batch_mode = False

    if input_path.is_dir():
        is_batch_mode = True
        pdf_files_to_process = sorted(list(input_path.glob("*.pdf")))
        if not pdf_files_to_process:
            print(f"[INFO] No PDF files found in directory: {args.pdf_path}")
            return
        print(f"[INFO] Batch mode activated. Found {len(pdf_files_to_process)} PDF(s) in '{args.pdf_path}'.")
    elif input_path.is_file():
        if input_path.suffix.lower() != '.pdf':
            raise ValueError(f"Input file is not a PDF: {args.pdf_path}")
        pdf_files_to_process.append(input_path)
        print(f"[INFO] Single file mode: Processing '{args.pdf_path}'.")
    else:
        raise FileNotFoundError(f"Input path is not a valid file or directory: {args.pdf_path}")

    config = load_config()
    # --- Model Resolution (Main Thread Only) ---
    if args.use_defaults:
        preset_defaults = get_preset_defaults(config)
        if preset_defaults:
            print("[INFO] Applying preset default OCR settings (-d flag used).")
            parser_ocr_defaults = {
                'model': [], 'repeat': [], 'judge_model': None,
                'judge_mode': 'authoritative', 'judge_with_image': False
            }
            for key, default_val_in_parser in parser_ocr_defaults.items():
                # Apply preset default only if the arg was not explicitly set by the user via CLI for this command
                if getattr(args, key) == default_val_in_parser and key in preset_defaults:
                    setattr(args, key, preset_defaults[key])
                    print(f"[INFO] Using preset for --{key.replace('_', '-')}: {preset_defaults[key]}")
        else: # -d used, but no 'defaults' in config
            print("[ERROR] -d flag used, but no 'defaults' found in config. Use 'pdf2anki config set defaults ...' to define them.")
            sys.exit(1)

    # If models are still not set (neither by CLI's --model nor by -d presets), try global default_model
    if not args.model:
        # Pass interactive=True because this is the main thread.
        # get_default_model will check sys.stdin.isatty() internally if it needs to prompt.
        default_model_from_config = get_default_model(config, interactive=True)
        if default_model_from_config:
            args.model = [default_model_from_config] # Set it for the args Namespace
            print(f"[INFO] Using 'default_model' from config (or user prompt): {args.model}")
        else:
            # If still no model (no config, and user provided no input when prompted or non-interactive)
            print("[ERROR] No OCR model specified or configured. Required for 'pdf2text'.")
            print("  Use --model <model_name>, or use -d with configured 'defaults',")
            print("  or configure 'default_model' via 'pdf2anki config set default_model <name>'.")
            sys.exit(1)
    # --- End Model Resolution ---

    common_args_dict = vars(args).copy()
    common_args_dict['_is_batch_mode'] = is_batch_mode

    if is_batch_mode and len(pdf_files_to_process) > 1:
        cpu_cores = os.cpu_count() or 1
        num_workers = min(len(pdf_files_to_process), max(1, int(cpu_cores * 0.6)))
        print(f"[INFO] Detected {cpu_cores} CPU cores. Using up to {num_workers} parallel worker processes.")

        success_count = 0
        failure_count = 0
        results_summary = []

        with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
            future_to_pdf = {
                executor.submit(_process_pdf_worker, str(pdf_path), common_args_dict): pdf_path
                for pdf_path in pdf_files_to_process
            }
            for future in concurrent.futures.as_completed(future_to_pdf):
                pdf_path_completed = future_to_pdf[future]
                try:
                    result_msg = future.result()
                    results_summary.append(result_msg)
                    if result_msg.startswith("SUCCESS"):
                        success_count +=1
                    else:
                        failure_count +=1
                except Exception as exc:
                    failure_count +=1
                    err_msg = f"FAILURE: {pdf_path_completed.name} - Worker unhandled exception: {exc}"
                    print(f"[ERROR] {err_msg}") # Also print here for main thread visibility
                    results_summary.append(err_msg)
        
        print("\n--- Batch Processing Summary ---")
        for res_msg in results_summary:
             print(f"  - {res_msg}")
        print(f"Total successfully processed: {success_count}")
        print(f"Total failed: {failure_count}")
    else:
        print("[INFO] Processing sequentially (single file or only one PDF in directory).")
        result_msg = _process_pdf_worker(str(pdf_files_to_process[0]), common_args_dict)
        print(f"\n--- Processing Summary ---\n  - {result_msg}")
    print("All 'pdf2text' tasks complete.")


def text_to_anki(args: argparse.Namespace) -> None:
    """
    Convert a text file into an Anki-compatible format, creating an Anki deck.
    """
    config = load_config()
    anki_model_to_use = args.anki_model
    if not anki_model_to_use:
        # Pass interactive=True as this is called from main thread context for text2anki
        default_anki_model = get_default_anki_model(config, interactive=True)
        if default_anki_model:
            anki_model_to_use = default_anki_model
            print(f"[INFO] Using default Anki model (from config/prompt): {default_anki_model}")
        else:
            print("[ERROR] No Anki model specified and no default configured/provided for 'text2anki'.")
            print("  Use the anki_model argument or set 'default_anki_model' via 'pdf2anki config set default_anki_model <name>'.")
            sys.exit(1)
    text2anki.convert_text_to_anki(args.text_file, args.anki_file, anki_model_to_use)


def process_pdf_to_anki(args: argparse.Namespace) -> None:
    """
    Full pipeline: Convert a PDF to images, then extract text, and finally create an Anki deck.
    This command currently runs sequentially for a single PDF.
    """
    print("[INFO] The 'process' command runs its steps sequentially for a single PDF.")
    print("[INFO] For parallel processing of multiple PDFs to text, please use the 'pdf2text' command with a directory, then 'text2anki'.")

    config = load_config() # Load config once

    # --- Resolve OCR Model for Step 2 ---
    ocr_models_for_step2 = list(args.model) # Start with CLI args for OCR for this command
    if args.use_defaults and not ocr_models_for_step2: # if -d is used and no --model for this 'process' call
        preset_defaults = get_preset_defaults(config)
        if preset_defaults:
            print("[INFO] Applying preset OCR settings for 'process' from -d flag.")
            if 'model' in preset_defaults: ocr_models_for_step2 = preset_defaults['model']
            # Apply other relevant preset OCR flags if not overridden by specific 'process' flags
            if not args.repeat and 'repeat' in preset_defaults: args.repeat = preset_defaults['repeat']
            if not args.judge_model and 'judge_model' in preset_defaults: args.judge_model = preset_defaults['judge_model']
            if not args.judge_mode and 'judge_mode' in preset_defaults: args.judge_mode = preset_defaults['judge_mode']
            if not args.judge_with_image and 'judge_with_image' in preset_defaults: args.judge_with_image = preset_defaults['judge_with_image']
        else:
            print("[ERROR] -d flag used with 'process', but no 'defaults' found in config.")
            sys.exit(1)

    if not ocr_models_for_step2: # If still no models (no --model for 'process', -d didn't help)
        # interactive=True as this is main thread for 'process'
        default_ocr_model = get_default_model(config, interactive=True)
        if default_ocr_model:
            ocr_models_for_step2 = [default_ocr_model]
            print(f"[INFO] Using 'default_model' (from config/prompt) for OCR in 'process': {ocr_models_for_step2}")
        else:
            print("[ERROR] No OCR model specified or configured for the 'process' command's text extraction step.")
            sys.exit(1)
    # --- End OCR Model Resolution ---

    # --- Resolve Anki Model for Step 3 ---
    anki_model_to_use = args.anki_model # From 'process' command's anki_model arg
    if not anki_model_to_use:
        # interactive=True as this is main thread for 'process'
        default_anki_model = get_default_anki_model(config, interactive=True)
        if default_anki_model:
            anki_model_to_use = default_anki_model
            print(f"[INFO] Using 'default_anki_model' (from config/prompt) for 'process': {anki_model_to_use}")
        else:
            print("[ERROR] No Anki model specified for 'process' command and no 'default_anki_model' configured/provided.")
            sys.exit(1)
    # --- End Anki Model Resolution ---

    anki_path = Path(args.anki_file)
    pid_suffix = f"_{os.getpid()}" if hasattr(os, 'getpid') else ""
    output_text_file_path = anki_path.with_name(f"{anki_path.stem}_temp_ocr{pid_suffix}.txt")

    # Step 1: PDF to Images
    pdf_to_images_args = argparse.Namespace(
        pdf_path=args.pdf_path, output_dir=args.output_dir, rectangles=[],
        verbose=getattr(args, 'verbose', False)
    )
    print(f"[INFO] Step 1 (process): Converting PDF '{args.pdf_path}' to images in '{args.output_dir}'...")
    pdf_to_images(pdf_to_images_args)

    # Step 2: Images to Text
    images_to_text_args_for_process = argparse.Namespace(
        images_dir=args.output_dir, output_file=str(output_text_file_path),
        model=ocr_models_for_step2, # Use resolved OCR models
        repeat=args.repeat, judge_model=args.judge_model, judge_mode=args.judge_mode,
        ensemble_strategy=args.ensemble_strategy, trust_score=args.trust_score,
        judge_with_image=args.judge_with_image, verbose=getattr(args, 'verbose', False)
    )
    print(f"[INFO] Step 2 (process): Extracting text to '{output_text_file_path}'...")
    images_to_text(images_to_text_args_for_process)

    # Step 3: Text to Anki
    text_to_anki_args_for_process = argparse.Namespace(
        text_file=str(output_text_file_path), anki_file=args.anki_file,
        anki_model=anki_model_to_use, # Use resolved Anki model
        verbose=getattr(args, 'verbose', False)
    )
    print(f"[INFO] Step 3 (process): Converting text to Anki deck '{args.anki_file}'...")
    text_to_anki(text_to_anki_args_for_process)

    # Optional: Cleanup temp text file
    # try: Path(output_text_file_path).unlink() except OSError: pass
    print(f"[INFO] 'process' command completed for '{args.pdf_path}'. Temp text file: {output_text_file_path}")


def view_config(args: argparse.Namespace) -> None:
    config = load_config()
    if config:
        print(json.dumps(config, indent=2))
    else:
        print("Configuration is empty.")

def set_config_value(args: argparse.Namespace) -> None:
    config = load_config()
    key = args.key
    values = args.values

    if not values:
        print(f"[ERROR] No value provided for key '{key}'.")
        # ... (help text as before)
        return

    if key == "defaults":
        if len(values) == 1: 
            json_str = values[0]
            try:
                defaults_obj = json.loads(json_str)
                # ... (validation as before) ...
                config["defaults"] = defaults_obj
                save_config(config)
                print(f"Set 'defaults' using JSON object: {json.dumps(defaults_obj, indent=2)}")
            except json.JSONDecodeError:
                print(f"[ERROR] Invalid JSON for 'defaults': '{json_str}'.")
            except ValueError as e:
                print(f"[ERROR] Invalid JSON structure for 'defaults': {e}")
            return
        elif len(values) >= 2:
            subkey = values[0]
            value_str = " ".join(values[1:])
            defaults = config.get("defaults", {})
            try:
                if subkey == "model": defaults[subkey] = [m.strip() for m in value_str.split(',') if m.strip()]
                elif subkey == "repeat": defaults[subkey] = [int(r.strip()) for r in value_str.split(',') if r.strip()]
                elif subkey == "judge_model": defaults[subkey] = value_str.strip() if value_str.strip() else None
                elif subkey == "judge_mode": defaults[subkey] = value_str.strip()
                elif subkey == "judge_with_image":
                    lower_val = value_str.strip().lower()
                    if lower_val in ["true", "1", "yes", "on"]: defaults[subkey] = True
                    elif lower_val in ["false", "0", "no", "off"]: defaults[subkey] = False
                    else: raise ValueError(f"Invalid boolean: '{value_str}'. Use true/false.")
                else:
                    print(f"[ERROR] Unknown 'defaults' subkey: '{subkey}'.")
                    return
                config["defaults"] = defaults
                save_config(config)
                print(f"Set 'defaults.{subkey}' to: {defaults[subkey]}")
            except ValueError as e: print(f"[ERROR] Invalid value for 'defaults.{subkey}': {e}")
            except Exception as e: print(f"[ERROR] Failed to set 'defaults.{subkey}': {e}")
        else: print(f"[ERROR] Invalid arguments for 'defaults'.")
    elif key in ["default_model", "default_anki_model"]:
        if len(values) == 1:
            value_str = values[0].strip()
            if value_str: config[key] = value_str; save_config(config); print(f"Set '{key}' to '{config[key]}'.")
            else: print(f"[ERROR] Value for '{key}' cannot be empty.")
        else: print(f"[ERROR] Usage: pdf2anki config set {key} <model_name>")
    else: print(f"[ERROR] Unknown config key: '{key}'.")


def cli_invoke() -> None:
    parser = argparse.ArgumentParser(
        description="Convert PDFs to Anki flashcards."
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose output."
    )
    subparsers = parser.add_subparsers(title="Commands", dest="command", required=True)

    # --- PDF to Images Command ---
    parser_pdf2pic = subparsers.add_parser("pdf2pic", help="Convert PDF pages to images.")
    parser_pdf2pic.add_argument("pdf_path", type=str, help="Path to PDF.")
    parser_pdf2pic.add_argument("output_dir", type=str, help="Directory for images.")
    parser_pdf2pic.add_argument("rectangles", type=str, nargs="*", default=[], help="Crop rectangles 'l,t,r,b'.")
    parser_pdf2pic.set_defaults(func=pdf_to_images)

    # --- Images to Text Command ---
    parser_pic2text = subparsers.add_parser("pic2text", help="Extract text from images using OCR.")
    parser_pic2text.add_argument("images_dir", type=str, help="Directory with images.")
    parser_pic2text.add_argument("output_file", type=str, help="File to save text.")
    parser_pic2text.add_argument("--model", action="append", default=[], help="OCR model(s).")
    parser_pic2text.add_argument("--repeat", action="append", type=int, default=[], help="Repeats per model.")
    parser_pic2text.add_argument("--judge-model", type=str, default=None, help="Judge model.")
    parser_pic2text.add_argument("--judge-mode", type=str, default="authoritative", choices=["authoritative"], help="Judge mode.")
    parser_pic2text.add_argument("--ensemble-strategy", type=str, default=None, help="(Placeholder).")
    parser_pic2text.add_argument("--trust-score", type=float, default=None, help="(Placeholder).")
    parser_pic2text.add_argument("--judge-with-image", action="store_true", default=False, help="Judge sees image.")
    parser_pic2text.set_defaults(func=images_to_text)

    # --- PDF to Text Command ---
    parser_pdf2text = subparsers.add_parser("pdf2text", help="PDF or directory of PDFs to text (parallel for dirs).")
    parser_pdf2text.add_argument("pdf_path", type=str, help="PDF file or directory of PDFs.")
    parser_pdf2text.add_argument("output_dir", type=str, nargs='?', default=None, help="Optional: Image dir base / specific dir.")
    parser_pdf2text.add_argument("rectangles", type=str, nargs="*", default=[], help="Optional: Crop rectangles.")
    parser_pdf2text.add_argument("output_file", type=str, nargs='?', default=None, help="Optional: Text output dir / file.")
    parser_pdf2text.add_argument("-d", "--default", dest="use_defaults", action="store_true", help="Use preset OCR defaults.")
    parser_pdf2text.add_argument("--model", action="append", default=[], help="OCR model(s).")
    parser_pdf2text.add_argument("--repeat", action="append", type=int, default=[], help="Repeats per model.")
    parser_pdf2text.add_argument("--judge-model", type=str, default=None, help="Judge model.")
    parser_pdf2text.add_argument("--judge-mode", type=str, default="authoritative", choices=["authoritative"], help="Judge mode.")
    parser_pdf2text.add_argument("--ensemble-strategy", type=str, default=None, help="(Placeholder).")
    parser_pdf2text.add_argument("--trust-score", type=float, default=None, help="(Placeholder).")
    parser_pdf2text.add_argument("--judge-with-image", action="store_true", default=False, help="Judge sees image.")
    parser_pdf2text.set_defaults(func=pdf_to_text)
    
    # --- Text to Anki Command ---
    parser_text2anki = subparsers.add_parser("text2anki", help="Convert text to Anki package.")
    parser_text2anki.add_argument("text_file", type=str, help="Input text file.")
    parser_text2anki.add_argument("anki_file", type=str, help="Output Anki .apkg file.")
    parser_text2anki.add_argument("anki_model", type=str, nargs='?', default=None, help="Model for Anki generation.")
    parser_text2anki.set_defaults(func=text_to_anki)

    # --- Full Pipeline Command ('process') ---
    parser_process = subparsers.add_parser("process", help="Run entire pipeline sequentially for one PDF.")
    parser_process.add_argument("pdf_path", type=str, help="Input PDF file.")
    parser_process.add_argument("output_dir", type=str, help="Directory for intermediate images.")
    parser_process.add_argument("anki_file", type=str, help="Output Anki .apkg file.")
    parser_process.add_argument("anki_model", type=str, nargs='?', default=None, help="Model for Anki generation.")
    parser_process.add_argument("-d", "--default", dest="use_defaults", action="store_true", help="Use preset OCR defaults for text extraction step.")
    parser_process.add_argument("--model", action="append", default=[], help="OCR model for text extraction.")
    parser_process.add_argument("--repeat", action="append", type=int, default=[], help="Repeats for OCR model.")
    parser_process.add_argument("--judge-model", type=str, default=None, help="Judge model for OCR.")
    parser_process.add_argument("--judge-mode", type=str, default="authoritative", choices=["authoritative"], help="Judge mode for OCR.")
    parser_process.add_argument("--ensemble-strategy", type=str, default=None, help="(Placeholder).")
    parser_process.add_argument("--trust-score", type=float, default=None, help="(Placeholder).")
    parser_process.add_argument("--judge-with-image", action="store_true", default=False, help="Judge sees image in OCR step.")
    parser_process.set_defaults(func=process_pdf_to_anki)

    # --- Configuration Command ---
    parser_config = subparsers.add_parser("config", help="View or modify configuration.")
    config_subparsers = parser_config.add_subparsers(title="Config Actions", dest="config_action", required=True)
    parser_config_view = config_subparsers.add_parser("view", help="Show current config.")
    parser_config_view.set_defaults(func=view_config)
    parser_config_set = config_subparsers.add_parser("set", help="Set a config value.", formatter_class=argparse.RawTextHelpFormatter,
        description=(
            "Sets a configuration value. Key can be 'default_model', 'default_anki_model', or 'defaults'.\n"
            "For 'defaults', either set a sub-setting like 'defaults model model_name' or a full JSON object.\n"
            "Examples:\n"
            "  pdf2anki config set default_model google/gemini-pro\n"
            "  pdf2anki config set defaults model google/gemini-pro,another/model\n"
            "  pdf2anki config set defaults repeat 2,1\n"
            "  pdf2anki config set defaults '{\"model\": [\"m1\"], \"repeat\": [1]}'"
        ))
    parser_config_set.add_argument("key", type=str, help="Config key.")
    parser_config_set.add_argument("values", nargs='*', help="Value(s) to set.")
    parser_config_set.set_defaults(func=set_config_value)

    try:
        args = parser.parse_args()
        if hasattr(args, 'func'):
            # Check if it's the main process before potentially prompting in get_default_model
            # This is now handled more robustly within get_default_model and pdf_to_text's main thread logic.
            args.func(args)
        else:
            parser.print_help()
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1) # Exit with error code 1 for known errors
    except KeyboardInterrupt:
        print("\n[INFO] Operation cancelled by user (KeyboardInterrupt).", file=sys.stderr)
        sys.exit(130) # Standard exit code for Ctrl+C
    except Exception as e:
        print(f"[UNEXPECTED ERROR] An unexpected error occurred: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(2) # Exit with a different error code for unexpected errors

if __name__ == "__main__":
    if sys.platform.startswith('win'):
        # Required for multiprocessing freeze support on Windows
        # concurrent.futures.ProcessPoolExecutor might not always need this explicitly,
        # but it's good practice if creating executables or having entry point issues.
        # multiprocessing.freeze_support() # Not strictly needed for ProcessPoolExecutor usually.
        pass
    cli_invoke()



