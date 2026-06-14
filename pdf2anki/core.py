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
from . import perf_tuner
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


def get_default_judge_model(config: Dict[str, Any]) -> Optional[str]:
    """Gets the global default judge model from config (no interactive prompt).

    Unlike the OCR model, the judge has a runtime safety net (falls back to the
    primary OCR model with a warning in pic2text) so there is no need to prompt.
    """
    val = config.get("default_judge_model")
    return val if val else None


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
        verbose=getattr(args, 'verbose', False),
        resume_existing=getattr(args, 'resume_existing', False)
    )
    if getattr(args, 'verbose', False):
        print(f"{pid_str} pdf_to_images completed for: {args.pdf_path}")


_IMAGE_EXTS = ('.png', '.jpg', '.jpeg')
_PARSER_OCR_DEFAULTS = {
    'model': [], 'repeat': [], 'judge_model': None,
    'judge_mode': 'authoritative', 'judge_with_image': False,
    'no_resume': False, 'max_page_attempts': 40,
    'max_image_kb': pic2text.DEFAULT_MAX_IMAGE_KB,
}


def _apply_ocr_presets_and_resolve_model(args: argparse.Namespace, config: Dict[str, Any]) -> None:
    """Apply preset defaults onto args in-place, then ensure args.model is set.

    Priority: CLI args > Presets (defaults.*) > Global default_model > Prompt.
    Must run on the main thread (may prompt stdin).
    """
    preset_defaults = get_preset_defaults(config)
    temp_parser = argparse.ArgumentParser()
    for key, val in _PARSER_OCR_DEFAULTS.items():
        temp_parser.add_argument(
            f"--{key.replace('_', '-')}",
            default=val,
            action='append' if isinstance(val, list) else 'store',
        )
    parser_defaults_ns = temp_parser.parse_args([])

    print("[INFO] Applying settings. Priority: CLI > Presets > Global Default > Prompt.")
    for key, preset_val in preset_defaults.items():
        if key in _PARSER_OCR_DEFAULTS:
            cli_value = getattr(args, key, None)
            parser_default_value = getattr(parser_defaults_ns, key)
            if cli_value == parser_default_value:
                setattr(args, key, preset_val)
                print(f"[INFO] Using preset for --{key.replace('_', '-')}: {preset_val}")

    if not getattr(args, 'model', None):
        default_model_from_config = get_default_model(config, interactive=True)
        if default_model_from_config:
            args.model = [default_model_from_config]
            print(f"[INFO] Using 'default_model' from config (or user prompt): {args.model}")
        else:
            print("[ERROR] No OCR model specified or configured.")
            print("  Use --model <model_name>, set a 'defaults.model' preset, or set a 'default_model'.")
            sys.exit(1)

    # Judge model: CLI/preset already applied above. If still unset, fall back to
    # the global 'default_judge_model'. (Final safety net -- using the primary OCR
    # model when ensemble is requested but nothing is set -- lives in pic2text.)
    if not getattr(args, 'judge_model', None):
        global_judge = get_default_judge_model(config)
        if global_judge:
            args.judge_model = global_judge
            print(f"[INFO] Using 'default_judge_model' from config: {global_judge}")

    _preflight_validate_models(args)


def _preflight_validate_models(args: argparse.Namespace) -> None:
    """Fail fast on unknown OCR/judge model IDs before any processing starts.

    Catches typos like 'google/gemini-3.1-flash' (which silently 400s on every
    page) up front. Fails open: if the OpenRouter model list can't be fetched,
    validation is skipped with a warning. Disable entirely via
    PDF2ANKI_SKIP_MODEL_VALIDATION=1.
    """
    if os.getenv("PDF2ANKI_SKIP_MODEL_VALIDATION", "").strip() in ("1", "true", "True"):
        return

    candidate_ids: List[str] = []
    for m in (getattr(args, 'model', None) or []):
        if m and m not in candidate_ids:
            candidate_ids.append(m)
    judge = getattr(args, 'judge_model', None)
    if judge and judge not in candidate_ids:
        candidate_ids.append(judge)
    if not candidate_ids:
        return

    available = pic2text.fetch_available_model_ids()
    if available is None:
        print("[WARN] Could not fetch the OpenRouter model list; skipping model-ID validation.")
        return

    import difflib
    unknown = [m for m in candidate_ids if m not in available]
    if not unknown:
        return

    print("[ERROR] One or more configured model IDs do not exist on OpenRouter:")
    for m in unknown:
        suggestions = difflib.get_close_matches(m, list(available), n=3, cutoff=0.5)
        hint = f"  Did you mean: {', '.join(suggestions)}?" if suggestions else "  No close match found."
        print(f"  - '{m}'\n  {hint}")
    print("[ERROR] Aborting before processing so no API budget is wasted on guaranteed-400 calls.")
    print("        Fix the model ID(s), or set PDF2ANKI_SKIP_MODEL_VALIDATION=1 to bypass this check.")
    sys.exit(1)


def _dir_has_top_level_images(path: Path) -> bool:
    try:
        return any(f.is_file() and f.suffix.lower() in _IMAGE_EXTS for f in path.iterdir())
    except OSError:
        return False


def _find_image_subdirs(path: Path) -> List[Path]:
    try:
        candidates = sorted(d for d in path.iterdir() if d.is_dir())
    except OSError:
        return []
    return [d for d in candidates if _dir_has_top_level_images(d)]


def _run_single_dir_ocr(args: argparse.Namespace) -> None:
    """Run OCR on one flat images_dir. Expects args.model already resolved."""
    pid_str = f"[{os.getpid() if hasattr(os, 'getpid') else 'main'}]"
    remaining_model_repeats: List[Tuple[str, int]] = []
    for idx, model_name in enumerate(args.model):
        rp = 1
        if args.repeat and idx < len(args.repeat):
            rp = args.repeat[idx]
        remaining_model_repeats.append((model_name, rp))

    if not remaining_model_repeats:
        raise ValueError(f"{pid_str} _run_single_dir_ocr: No models/repeats configured.")

    explicit_concurrency = getattr(args, 'max_concurrent_pages', None)
    primary_model = remaining_model_repeats[0][0]
    resolved_concurrency = perf_tuner.resolve_concurrency(primary_model, explicit_concurrency)
    if explicit_concurrency is None and not perf_tuner.is_disabled():
        print(f"{pid_str} [TUNER] max_concurrent_pages={resolved_concurrency} for {primary_model}")

    pic2text.convert_images_to_text(
        images_dir=args.images_dir,
        output_file=args.output_file,
        model_repeats=remaining_model_repeats,
        judge_model=args.judge_model,
        judge_mode=args.judge_mode,
        ensemble_strategy=args.ensemble_strategy,
        trust_score=args.trust_score,
        judge_with_image=args.judge_with_image,
        no_resume=getattr(args, 'no_resume', False),
        max_page_attempts=getattr(args, 'max_page_attempts', 40),
        verbose=getattr(args, 'verbose', False),
        max_concurrent_pages=resolved_concurrency,
        max_image_kb=getattr(args, 'max_image_kb', pic2text.DEFAULT_MAX_IMAGE_KB),
    )


def _process_image_dir_worker(subdir_str: str, common_args_dict: dict, output_base_dir_str: str) -> str:
    """Worker that OCRs one image subdirectory into {output_base_dir}/{subdir.name}.txt."""
    worker_args = argparse.Namespace(**common_args_dict)
    subdir = Path(subdir_str)
    pid = os.getpid()

    try:
        print(f"[{pid}] Starting OCR for subdirectory: {subdir.name}")
        out_file = Path(output_base_dir_str) / f"{subdir.name}.txt"
        out_file.parent.mkdir(parents=True, exist_ok=True)

        worker_args.images_dir = str(subdir)
        worker_args.output_file = str(out_file)
        _run_single_dir_ocr(worker_args)
        return f"SUCCESS: {subdir.name}"
    except pic2text.OCRPauseException as pause_exc:
        print(f"[{pid}] PAUSED OCR for {subdir.name}: {pause_exc}")
        return f"PAUSED: {subdir.name} - {pause_exc}"
    except Exception as e:
        print(f"[{pid}] ERROR OCR for {subdir.name}: {e}\n{traceback.format_exc()}")
        return f"FAILURE: {subdir.name} - {e}"


def images_to_text(args: argparse.Namespace) -> None:
    """Perform OCR on images. Single-dir (flat images) or batch (dir of image-subdirs).

    Batch dispatch rule: if images_dir has no image files at top level but contains
    subdirectories that themselves hold images, treat each subdir as one document
    and process them in parallel (mirrors pdf2text's dir-of-PDFs batch mode).
    """
    pid_str = f"[{os.getpid() if hasattr(os, 'getpid') else 'main'}]"
    if getattr(args, 'verbose', False):
        print(f"{pid_str} images_to_text (core wrapper) called for dir: {args.images_dir}")

    input_path = Path(args.images_dir)
    if not input_path.is_dir():
        raise FileNotFoundError(f"images_dir is not a directory: {args.images_dir}")

    config = load_config()
    _apply_ocr_presets_and_resolve_model(args, config)

    is_batch_mode = False
    image_subdirs: List[Path] = []
    if not _dir_has_top_level_images(input_path):
        image_subdirs = _find_image_subdirs(input_path)
        is_batch_mode = bool(image_subdirs)

    if is_batch_mode:
        # output_file in batch mode is treated as the output directory for per-subdir txt files.
        if args.output_file:
            explicit_out = Path(args.output_file)
            if explicit_out.suffix and not explicit_out.is_dir():
                output_base_dir = explicit_out.parent or Path.cwd()
            else:
                output_base_dir = explicit_out
        else:
            output_base_dir = Path.cwd()
        output_base_dir.mkdir(parents=True, exist_ok=True)

        print(
            f"[INFO] pic2text batch mode: {len(image_subdirs)} image subdirectories in "
            f"'{args.images_dir}'. Output → '{output_base_dir}/<subdir>.txt'."
        )
        cpu_cores = os.cpu_count() or 1
        num_workers = min(len(image_subdirs), max(1, int(cpu_cores * 0.6)))
        print(f"[INFO] Using up to {num_workers} parallel worker processes.")

        common_args_dict = vars(args).copy()
        common_args_dict.pop('func', None)

        success_count = 0
        failure_count = 0
        paused_count = 0
        pause_detected = False
        results_summary: List[str] = []

        with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
            future_to_subdir = {
                executor.submit(
                    _process_image_dir_worker, str(subdir), common_args_dict, str(output_base_dir)
                ): subdir
                for subdir in image_subdirs
            }
            completed = 0
            for future in concurrent.futures.as_completed(future_to_subdir):
                subdir_done = future_to_subdir[future]
                completed += 1
                try:
                    result_msg = future.result()
                    results_summary.append(result_msg)
                    if result_msg.startswith("SUCCESS"):
                        success_count += 1
                    elif result_msg.startswith("PAUSED"):
                        paused_count += 1
                        pause_detected = True
                        for pending_future in future_to_subdir:
                            if not pending_future.done():
                                pending_future.cancel()
                    else:
                        failure_count += 1
                except Exception as exc:
                    failure_count += 1
                    err_msg = f"FAILURE: {subdir_done.name} - Worker exception: {exc}"
                    print(f"[ERROR] {err_msg}")
                    results_summary.append(err_msg)
                print(
                    f"[INFO] Batch OCR progress: {completed}/{len(image_subdirs)} subdirs finished "
                    f"(success={success_count}, paused={paused_count}, failed={failure_count})."
                )

        print("\n--- pic2text Batch Summary ---")
        for res in results_summary:
            print(f"  - {res}")
        print(f"Total success: {success_count}, paused: {paused_count}, failed: {failure_count}")
        if pause_detected:
            raise pic2text.OCRPauseException(
                "OCR paused for at least one subdirectory after reaching per-page attempt limit. "
                "Fix external issue and rerun to resume."
            )
        return

    # --- Single-dir mode ---
    if not args.output_file:
        stem_source = input_path.resolve().name
        fallback_stem = stem_source or "pic2text_output"
        args.output_file = str(Path.cwd() / f"{fallback_stem}.txt")
        print(f"[INFO] No output file specified. Defaulting to: {args.output_file}")

    _run_single_dir_ocr(args)
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
            resume_existing=not getattr(worker_args, 'no_resume', False),
            verbose=getattr(worker_args, 'verbose', False)
        )
        
        # `worker_args.model` is passed here, which was resolved in the main thread.
        # Bypass images_to_text's dispatcher since we already know the single-dir shape.
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
            no_resume=getattr(worker_args, 'no_resume', False),
            max_page_attempts=getattr(worker_args, 'max_page_attempts', 40),
            max_concurrent_pages=getattr(worker_args, 'max_concurrent_pages', None),
            max_image_kb=getattr(worker_args, 'max_image_kb', pic2text.DEFAULT_MAX_IMAGE_KB),
            verbose=getattr(worker_args, 'verbose', False)
        )

        pdf_to_images(pdf_to_images_args)
        _run_single_dir_ocr(images_to_text_args)

        success_msg = f"Successfully processed {pdf_path.name}"
        print(f"[{pid}] {success_msg}")
        return f"SUCCESS: {pdf_path.name}"

    except pic2text.OCRPauseException as pause_exc:
        pause_msg = f"PAUSED processing {pdf_path.name} in process {pid}: {pause_exc}"
        print(f"[{pid}] {pause_msg}")
        return f"PAUSED: {pdf_path.name} - {pause_exc}"
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
    _apply_ocr_presets_and_resolve_model(args, config)

    common_args_dict = vars(args).copy()
    common_args_dict['_is_batch_mode'] = is_batch_mode

    if is_batch_mode and len(pdf_files_to_process) > 1:
        cpu_cores = os.cpu_count() or 1
        num_workers = min(len(pdf_files_to_process), max(1, int(cpu_cores * 0.6)))
        print(f"[INFO] Detected {cpu_cores} CPU cores. Using up to {num_workers} parallel worker processes.")

        success_count = 0
        failure_count = 0
        paused_count = 0
        pause_detected = False
        results_summary = []

        with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
            future_to_pdf = {
                executor.submit(_process_pdf_worker, str(pdf_path), common_args_dict): pdf_path
                for pdf_path in pdf_files_to_process
            }
            completed_workers = 0
            for future in concurrent.futures.as_completed(future_to_pdf):
                pdf_path_completed = future_to_pdf[future]
                completed_workers += 1
                try:
                    result_msg = future.result()
                    results_summary.append(result_msg)
                    if result_msg.startswith("SUCCESS"):
                        success_count += 1
                    elif result_msg.startswith("PAUSED"):
                        paused_count += 1
                        pause_detected = True
                        # Stop scheduling remaining work where possible.
                        for pending_future in future_to_pdf:
                            if not pending_future.done():
                                pending_future.cancel()
                    else:
                        failure_count += 1
                except Exception as exc:
                    failure_count += 1
                    err_msg = f"FAILURE: {pdf_path_completed.name} - Worker unhandled exception: {exc}"
                    print(f"[ERROR] {err_msg}") # Also print here for main thread visibility
                    results_summary.append(err_msg)
                print(
                    f"[INFO] Batch progress: {completed_workers}/{len(pdf_files_to_process)} PDFs finished "
                    f"(success={success_count}, paused={paused_count}, failed={failure_count})."
                )
        
        print("\n--- Batch Processing Summary ---")
        for res_msg in results_summary:
            print(f"  - {res_msg}")
        print(f"Total successfully processed: {success_count}")
        print(f"Total paused: {paused_count}")
        print(f"Total failed: {failure_count}")
        if pause_detected:
            raise ValueError("OCR processing paused after reaching per-page attempt limit. Fix external issue and rerun to resume.")
    else:
        print("[INFO] Processing sequentially (single file or only one PDF in directory).")
        result_msg = _process_pdf_worker(str(pdf_files_to_process[0]), common_args_dict)
        print(f"\n--- Processing Summary ---\n  - {result_msg}")
        if result_msg.startswith("PAUSED"):
            raise ValueError("OCR processing paused after reaching per-page attempt limit. Fix external issue and rerun to resume.")
        if result_msg.startswith("FAILURE"):
            raise ValueError(f"OCR processing failed: {result_msg}")
    print("All 'pdf2text' tasks complete.")


def _run_workflow(workflow_args: list) -> None:
    """Delegate to the text2anki workflow_manager, passing remaining args."""
    from .text2anki import workflow_manager as wm_module
    original_argv = sys.argv[:]
    sys.argv = [sys.argv[0]] + list(workflow_args)
    try:
        wm_module.main()
    finally:
        sys.argv = original_argv


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


def show_json_format() -> None:
    """
    Display the expected JSON format for flashcards and exit.
    """
    format_example = """Example input format for flashcards in JSON:

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

Supported fields:
- front, back (required): Card question and answer
- tags (optional): Array of categorization tags
- guid (optional): Unique identifier to prevent duplicates
- sort_field (optional): Custom sort value for card organization  
- due (optional): Days from today when card should first appear (default: 0)"""
    print(format_example)


# New: command handler for JSON→Anki mode
def json_to_anki(args: argparse.Namespace) -> None:
    """
    Convert a JSON file (or all JSON files in a directory) of flashcards to an Anki package (no LLM).
    """
    if getattr(args, 'show_format', False):
        show_json_format()
        return
    
    if not args.json_file:
        print("Error: json_file argument is required when not using --show-format")
        sys.exit(1)
    
    input_path = Path(args.json_file)
    
    # Check if input is a directory for bulk processing
    if input_path.is_dir():
        json_files = sorted(list(input_path.glob("*.json")))
        if not json_files:
            print(f"[INFO] No JSON files found in directory: {args.json_file}")
            return
        
        print(f"[INFO] Bulk processing mode activated. Found {len(json_files)} JSON file(s) in '{args.json_file}'.")
        
        success_count = 0
        failure_count = 0
        results_summary = []
        
        for json_file in json_files:
            try:
                # Generate output filename automatically
                output_apkg = str(json_file.with_suffix('.apkg'))
                print(f"[INFO] Processing: {json_file.name} -> {Path(output_apkg).name}")
                
                text2anki.convert_json_to_anki(str(json_file), output_apkg)
                success_count += 1
                results_summary.append(f"SUCCESS: {json_file.name} -> {Path(output_apkg).name}")
                
            except Exception as e:
                failure_count += 1
                error_msg = f"FAILURE: {json_file.name} - {e}"
                print(f"[ERROR] {error_msg}")
                results_summary.append(error_msg)
        
        print("\n--- Bulk Processing Summary ---")
        for res_msg in results_summary:
            print(f"  - {res_msg}")
        print(f"Total successfully processed: {success_count}")
        print(f"Total failed: {failure_count}")
        print("All 'json2anki' tasks complete.")
        
    elif input_path.is_file():
        # Single file processing (existing behavior)
        if input_path.suffix.lower() != '.json':
            print(f"[ERROR] Input file is not a JSON file: {args.json_file}")
            sys.exit(1)
        
        # If no anki_file is provided, generate it from the json_file name
        if not args.anki_file:
            args.anki_file = str(input_path.with_suffix('.apkg'))
            print(f"[INFO] No output file specified. Using: {args.anki_file}")
        
        text2anki.convert_json_to_anki(args.json_file, args.anki_file)
        
    else:
        print(f"[ERROR] Input path is not a valid file or directory: {args.json_file}")
        sys.exit(1)


def process_pdf_to_anki(args: argparse.Namespace) -> None:
    """
    Full pipeline: Convert a PDF to images, then extract text, and finally create an Anki deck.
    This command currently runs sequentially for a single PDF.
    """
    print("[INFO] The 'process' command runs its steps sequentially for a single PDF.")
    print("[INFO] For parallel processing of multiple PDFs to text, please use the 'pdf2text' command with a directory, then 'text2anki'.")

    config = load_config() # Load config once

    # --- Resolve OCR Model for Step 2 ---
    _apply_ocr_presets_and_resolve_model(args, config)
    ocr_models_for_step2 = list(args.model)
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
        resume_existing=not getattr(args, 'no_resume', False),
        verbose=getattr(args, 'verbose', False)
    )
    print(f"[INFO] Step 1 (process): Converting PDF '{args.pdf_path}' to images in '{args.output_dir}'...")
    pdf_to_images(pdf_to_images_args)

    # Step 2: Images to Text — use single-dir path directly (we know shape).
    images_to_text_args_for_process = argparse.Namespace(
        images_dir=args.output_dir, output_file=str(output_text_file_path),
        model=ocr_models_for_step2,
        repeat=args.repeat, judge_model=args.judge_model, judge_mode=args.judge_mode,
        ensemble_strategy=args.ensemble_strategy, trust_score=args.trust_score,
        judge_with_image=args.judge_with_image,
        no_resume=getattr(args, 'no_resume', False),
        max_page_attempts=getattr(args, 'max_page_attempts', 40),
        max_concurrent_pages=getattr(args, 'max_concurrent_pages', None),
        max_image_kb=getattr(args, 'max_image_kb', pic2text.DEFAULT_MAX_IMAGE_KB),
        verbose=getattr(args, 'verbose', False)
    )
    print(f"[INFO] Step 2 (process): Extracting text to '{output_text_file_path}'...")
    _run_single_dir_ocr(images_to_text_args_for_process)

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
    if not config:
        print("Configuration is empty.")
        print("\nGet started:")
        print("  pdf2anki config set default_model <model_name>      # global fallback OCR model")
        print("  pdf2anki config set default_anki_model <model_name> # model used for Anki card generation")
        print("  pdf2anki config set defaults model <model_name>     # OCR preset (overrides default_model)")
        return

    print(json.dumps(config, indent=2))

    if getattr(args, 'raw', False):
        return

    # --- Effective settings: show what will actually be used and from where ---
    presets = config.get("defaults", {}) or {}
    effective: List[tuple] = []  # (label, value, source)

    # OCR model: preset wins over global
    if presets.get("model"):
        effective.append(("OCR model(s)", presets["model"], "defaults.model (preset)"))
    elif config.get("default_model"):
        effective.append(("OCR model(s)", [config["default_model"]], "default_model (global)"))
    else:
        effective.append(("OCR model(s)", "<not set -- will prompt>", "--"))

    # Anki LLM model (no preset equivalent)
    if config.get("default_anki_model"):
        effective.append(("Anki LLM model", config["default_anki_model"], "default_anki_model (global)"))
    else:
        effective.append(("Anki LLM model", "<not set -- will prompt>", "--"))

    if presets.get("repeat"):
        effective.append(("Repeats per model", presets["repeat"], "defaults.repeat (preset)"))

    # Judge model: preset wins over global (mirrors the OCR model tiers)
    if presets.get("judge_model"):
        effective.append(("Judge model", presets["judge_model"], "defaults.judge_model (preset)"))
    elif config.get("default_judge_model"):
        effective.append(("Judge model", config["default_judge_model"], "default_judge_model (global)"))
    else:
        # Only relevant when ensemble OCR is implied (multiple models or repeat >= 2).
        preset_models_for_judge = presets.get("model") or ([config["default_model"]] if config.get("default_model") else [])
        repeats_for_judge = presets.get("repeat") or []
        ensemble_implied = len(preset_models_for_judge) > 1 or any(r >= 2 for r in repeats_for_judge)
        if ensemble_implied:
            effective.append(("Judge model", "<not set -- ensemble falls back to primary OCR model>", "--"))

    # Preset-only fields (these have no global counterpart)
    if "judge_mode" in presets:
        effective.append(("Judge mode", presets["judge_mode"], "defaults.judge_mode (preset)"))
    if "judge_with_image" in presets:
        effective.append(("Judge with image", presets["judge_with_image"], "defaults.judge_with_image (preset)"))

    label_w = max(len(lbl) for lbl, _, _ in effective)
    val_w = max(len(str(val)) for _, val, _ in effective)
    print("\nEffective settings (what will actually be used, CLI flags can still override):")
    for lbl, val, src in effective:
        print(f"  {lbl.ljust(label_w)}  =  {str(val).ljust(val_w)}   <- {src}")

    # Conflict / shadow warning
    if presets.get("model") and config.get("default_model"):
        if presets["model"] != [config["default_model"]]:
            print("\n[NOTE] 'default_model' is shadowed by the 'defaults.model' preset (preset wins).")
    if presets.get("judge_model") and config.get("default_judge_model"):
        if presets["judge_model"] != config["default_judge_model"]:
            print("\n[NOTE] 'default_judge_model' is shadowed by the 'defaults.judge_model' preset (preset wins).")

    # --- Migration commands (OCR model): always show what's applicable in BOTH directions ---
    preset_model = presets.get("model") or []
    global_model = config.get("default_model")
    if preset_model or global_model:
        print("\nMigration commands (OCR model) -- copy-paste to migrate between preset <-> global:")
        if preset_model and global_model:
            preset_first = preset_model[0]
            print(f"  Promote preset -> global  (overwrite global with preset's first model):")
            print(f"    pdf2anki config set default_model {preset_first}")
            print(f"  Promote global -> preset  (overwrite preset with global value):")
            print(f"    pdf2anki config set defaults model {global_model}")
            print(f"  Drop preset (so global '{global_model}' takes over):")
            print(f"    pdf2anki config unset defaults model")
            print(f"  Drop global (preset still wins; only matters if you later drop the preset too):")
            print(f"    pdf2anki config unset default_model")
        elif preset_model and not global_model:
            preset_first = preset_model[0]
            print(f"  Promote preset -> global  (set the global fallback to match):")
            print(f"    pdf2anki config set default_model {preset_first}")
            print(f"  Drop preset (no global is set, so pdf2anki will prompt at runtime):")
            print(f"    pdf2anki config unset defaults model")
        elif global_model and not preset_model:
            print(f"  Promote global -> preset  (create a preset so multi-model/ensemble is possible later):")
            print(f"    pdf2anki config set defaults model {global_model}")
            print(f"  Drop global (no preset is set, so pdf2anki will prompt at runtime):")
            print(f"    pdf2anki config unset default_model")

    # --- Migration commands (judge model): preset <-> global, mirrors OCR model ---
    preset_judge = presets.get("judge_model")
    global_judge = config.get("default_judge_model")
    if preset_judge or global_judge:
        print("\nMigration commands (judge model) -- copy-paste to migrate between preset <-> global:")
        if preset_judge and global_judge:
            print(f"  Promote preset -> global  (overwrite global with preset value):")
            print(f"    pdf2anki config set default_judge_model {preset_judge}")
            print(f"  Promote global -> preset  (overwrite preset with global value):")
            print(f"    pdf2anki config set defaults judge_model {global_judge}")
            print(f"  Drop preset (so global '{global_judge}' takes over):")
            print(f"    pdf2anki config unset defaults judge_model")
            print(f"  Drop global (preset still wins; only matters if you later drop the preset too):")
            print(f"    pdf2anki config unset default_judge_model")
        elif preset_judge and not global_judge:
            print(f"  Promote preset -> global  (set the global fallback to match):")
            print(f"    pdf2anki config set default_judge_model {preset_judge}")
            print(f"  Drop preset (no global is set; ensemble would fall back to the primary OCR model):")
            print(f"    pdf2anki config unset defaults judge_model")
        elif global_judge and not preset_judge:
            print(f"  Promote global -> preset  (create a preset, e.g. for project-specific judges):")
            print(f"    pdf2anki config set defaults judge_model {global_judge}")
            print(f"  Drop global (ensemble would fall back to the primary OCR model):")
            print(f"    pdf2anki config unset default_judge_model")

    print("\nPriority order: CLI flags > Presets (defaults.*) > Global (default_*) > Interactive prompt")
    print("Tip: 'pdf2anki config view --raw' prints only the JSON (no annotations).")

_PRESET_SUBKEYS = ("model", "repeat", "judge_model", "judge_mode", "judge_with_image")


def unset_config_value(args: argparse.Namespace) -> None:
    config = load_config()
    key = args.key
    subkey = getattr(args, 'subkey', None)

    valid_top = ("default_model", "default_anki_model", "default_judge_model", "defaults")
    if key not in valid_top:
        print(f"[ERROR] Unknown config key: '{key}'.")
        print(f"        Valid keys: {', '.join(valid_top)}")
        return

    if subkey is not None and key != "defaults":
        print(f"[ERROR] Subkey is only valid with 'defaults'. Got: 'unset {key} {subkey}'.")
        print(f"        Did you mean: 'pdf2anki config unset {key}'  (no subkey)?")
        return

    if subkey is not None and subkey not in _PRESET_SUBKEYS:
        print(f"[ERROR] Unknown preset subkey: '{subkey}'.")
        print(f"        Valid subkeys: {', '.join(_PRESET_SUBKEYS)}")
        return

    if key not in config:
        print(f"[INFO] '{key}' is not set -- nothing to unset.")
        return

    if subkey is None:
        del config[key]
        save_config(config)
        print(f"Removed '{key}'.")
    else:
        defaults = config.get("defaults", {})
        if subkey not in defaults:
            print(f"[INFO] 'defaults.{subkey}' is not set -- nothing to unset.")
            return
        del defaults[subkey]
        if not defaults:
            del config["defaults"]
            print(f"Removed 'defaults.{subkey}'. (Preset block is now empty and was removed entirely.)")
        else:
            config["defaults"] = defaults
            print(f"Removed 'defaults.{subkey}'.")
        save_config(config)

    print("Tip: run 'pdf2anki config view' to see the new effective settings.")


def set_config_value(args: argparse.Namespace) -> None:
    config = load_config()
    key = args.key
    values = args.values

    if not values:
        print(f"[ERROR] No value provided for key '{key}'.")
        print("\nThere are two tiers of settings -- pick the right one:")
        print("  GLOBAL (single value, lowest priority -- pure fallback):")
        print("    pdf2anki config set default_model <model_name>        # OCR model")
        print("    pdf2anki config set default_anki_model <model_name>   # Anki-card generation model")
        print("    pdf2anki config set default_judge_model <model_name>  # ensemble-OCR judge model")
        print("  PRESET (overrides global, may hold multiple models for ensemble OCR):")
        print("    pdf2anki config set defaults model <model_name>[,model2,...]")
        print("    pdf2anki config set defaults repeat 2[,3,...]")
        print("    pdf2anki config set defaults judge_model <model_name>")
        print("    pdf2anki config set defaults judge_mode authoritative")
        print("    pdf2anki config set defaults judge_with_image true|false")
        print("\nPriority: CLI flags > Presets (defaults.*) > Global (default_*) > Interactive prompt")
        print("Run 'pdf2anki config view' to see current + effective settings.")
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
                    print(f"        Valid subkeys: model, repeat, judge_model, judge_mode, judge_with_image")
                    return
                config["defaults"] = defaults
                save_config(config)
                print(f"Set 'defaults.{subkey}' to: {defaults[subkey]}")
                # Symmetric warning: setting the preset shadows the global default_model
                if subkey == "model" and defaults[subkey] and config.get("default_model") \
                        and defaults[subkey] != [config["default_model"]]:
                    print(f"\n[NOTE] Your global 'default_model' is '{config['default_model']}', which is now")
                    print(f"       shadowed by this preset (presets win). The preset will be used.")
                    print(f"       This is usually what you want -- presets exist to allow project-specific")
                    print(f"       model lists (e.g. ensembles with multiple models). Run 'pdf2anki config view'")
                    print(f"       to see effective settings.")
            except ValueError as e: print(f"[ERROR] Invalid value for 'defaults.{subkey}': {e}")
            except Exception as e: print(f"[ERROR] Failed to set 'defaults.{subkey}': {e}")
        else: print(f"[ERROR] Invalid arguments for 'defaults'.")
    elif key in ["default_model", "default_anki_model", "default_judge_model"]:
        if len(values) == 1:
            value_str = values[0].strip()
            if value_str:
                config[key] = value_str
                save_config(config)
                print(f"Set '{key}' to '{config[key]}'.")
                # Warn if the judge preset shadows this global judge default
                if key == "default_judge_model" and config.get("defaults", {}).get("judge_model") \
                        and config["defaults"]["judge_model"] != value_str:
                    print(f"\n[WARN] 'default_judge_model' is the GLOBAL fallback, but you also have a PRESET set:")
                    print(f"         defaults.judge_model = {config['defaults']['judge_model']}")
                    print(f"       The preset overrides the global, so this change has NO effect")
                    print(f"       unless you align or clear the preset:")
                    print(f"         pdf2anki config set defaults judge_model {value_str}   # align preset")
                    print(f"         pdf2anki config unset defaults judge_model             # clear preset (then global wins)")
                # Warn if presets might override this global default
                if key == "default_model" and config.get("defaults", {}).get("model"):
                    preset_models = config["defaults"]["model"]
                    if preset_models != [value_str]:
                        print(f"\n[WARN] 'default_model' is the GLOBAL fallback, but you also have a PRESET set:")
                        print(f"         defaults.model = {preset_models}")
                        print(f"       The preset overrides the global. So this change has NO effect")
                        print(f"       unless you also update the preset (or clear it):")
                        print(f"         pdf2anki config set defaults model {value_str}     # align preset")
                        print(f"         pdf2anki config set defaults model \"\"               # clear preset (then global wins)")
                        print(f"       Why both exist: 'default_model' = single fallback. 'defaults.model' =")
                        print(f"       project preset that may hold multiple models (for ensemble OCR).")
            else: print(f"[ERROR] Value for '{key}' cannot be empty.")
        else: print(f"[ERROR] Usage: pdf2anki config set {key} <model_name>")
    else:
        print(f"[ERROR] Unknown config key: '{key}'.")
        print(f"        Valid top-level keys: default_model, default_anki_model, default_judge_model, defaults")
        # Heuristic hint: if user typed a preset-subkey at top level, point them at 'defaults'
        preset_subkeys = {"model", "repeat", "judge_model", "judge_mode", "judge_with_image"}
        if key in preset_subkeys:
            v = " ".join(values) if values else "<value>"
            print(f"\n[HINT] '{key}' is a preset subkey. Did you mean:")
            print(f"         pdf2anki config set defaults {key} {v}")
            print(f"       Or did you mean the global fallback?")
            if key == "model":
                print(f"         pdf2anki config set default_model {v}")
            elif key == "judge_model":
                print(f"         pdf2anki config set default_judge_model {v}")
        else:
            print(f"\n[HINT] Examples:")
            print(f"         pdf2anki config set default_model <model_name>       # global fallback")
            print(f"         pdf2anki config set default_anki_model <model_name>  # Anki-card generation")
            print(f"         pdf2anki config set defaults model <model_name>      # preset (overrides global)")
            print(f"         pdf2anki config set defaults judge_model <model_name>")
        print(f"\nRun 'pdf2anki config set -h' for full help, or 'pdf2anki config view' for current state.")


def cli_invoke() -> None:
    # Early intercept for '.' — lazy mode (pdf2anki .)
    if len(sys.argv) > 1 and sys.argv[1] == '.':
        import argparse as _ap
        _parser = _ap.ArgumentParser(
            prog="pdf2anki .",
            description="Lazy mode: auto-detect pipeline state and run all pending steps.",
        )
        _parser.add_argument("--turns", type=int, default=7, metavar="N",
                             help="Max LLM discovery turns (default: 7).")
        _parser.add_argument("--no-llm", action="store_true",
                             help="Use guided wizard instead of LLM discovery.")
        _parser.add_argument("--reconfig", action="store_true",
                             help="Re-run discovery even if project.json already exists.")
        _parser.add_argument("--ocr-model", type=str, default=None, metavar="MODEL",
                             help="OCR model for pending PDFs (default: google/gemini-2.5-flash).")
        _parser.add_argument("--max-concurrent-pages", type=int, default=None, metavar="N",
                             help="Pages processed in parallel within one PDF "
                                  "(default: per-model auto-tuner; 1 = sequential).")
        _parser.add_argument("--max-image-kb", type=int, default=None, metavar="KB",
                             help=f"Image payload normalization target KB "
                                  f"(default: {pic2text.DEFAULT_MAX_IMAGE_KB}; 0 = disable).")
        _parser.add_argument("-y", "--yes", action="store_true",
                             help="Skip interactive confirmation prompts (auto-accept).")
        _parser.add_argument("-v", "--verbose", action="store_true",
                             help="Enable verbose output (L1 summaries on console).")
        _args = _parser.parse_args(sys.argv[2:])
        if _args.verbose:
            from .text2anki.console_utils import set_verbose
            set_verbose(True)
        from .text2anki.lazy_runner import run_lazy_mode
        run_lazy_mode(
            base_dir=Path.cwd(),
            turns=_args.turns,
            no_llm=_args.no_llm,
            reconfig=_args.reconfig,
            ocr_model=_args.ocr_model,
            max_concurrent_pages=_args.max_concurrent_pages,
            max_image_kb=_args.max_image_kb,
            auto_confirm=_args.yes,
        )
        return

    # Early intercept for 'workflow' subcommand — delegate directly to workflow_manager
    # before argparse tries to parse workflow-specific flags (--project, --extract, etc.)
    if len(sys.argv) > 1 and sys.argv[1] == 'workflow':
        from .text2anki import workflow_manager as wm_module
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        wm_module.main()
        return

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
    parser_pdf2pic.add_argument("--resume-existing", action="store_true", default=False, help="Reuse existing valid page images/crops and only generate missing or invalid ones.")
    parser_pdf2pic.set_defaults(func=pdf_to_images)

    # --- Images to Text Command ---
    parser_pic2text = subparsers.add_parser("pic2text", help="Extract text from images using OCR.")
    parser_pic2text.add_argument("images_dir", type=str, help="Directory with images.")
    parser_pic2text.add_argument("output_file", type=str, nargs='?', default=None, help="Optional: File to save text. Defaults to a file named after the input directory.")
    parser_pic2text.add_argument("--model", action="append", default=[], help="OCR model(s) to use (overrides presets).")
    parser_pic2text.add_argument("--repeat", action="append", type=int, default=[], help="Repeats per model (overrides presets).")
    parser_pic2text.add_argument("--judge-model", type=str, default=None, help="Judge model to use (overrides presets).")
    parser_pic2text.add_argument("--judge-mode", type=str, default="authoritative", choices=["authoritative"], help="Judge mode.")
    parser_pic2text.add_argument("--ensemble-strategy", type=str, default=None, help="(Placeholder).")
    parser_pic2text.add_argument("--trust-score", type=float, default=None, help="(Placeholder).")
    parser_pic2text.add_argument("--judge-with-image", action="store_true", default=False, help="Judge sees image (overrides presets).")
    parser_pic2text.add_argument("--no-resume", action="store_true", default=False, help="Disable OCR resume and start this OCR run from scratch.")
    parser_pic2text.add_argument("--max-page-attempts", type=int, default=40, help="Maximum full OCR attempts per page before pausing the run.")
    parser_pic2text.add_argument("--max-concurrent-pages", type=int, default=None, help="Pages processed in parallel within one PDF (default: per-model auto-tuner; 1 = sequential).")
    parser_pic2text.add_argument("--max-image-kb", type=int, default=pic2text.DEFAULT_MAX_IMAGE_KB, help=f"Cap the JPEG payload sent to the OCR API (KB). 0 = disable. Default: {pic2text.DEFAULT_MAX_IMAGE_KB}.")
    parser_pic2text.set_defaults(func=images_to_text)

    # --- PDF to Text Command ---
    parser_pdf2text = subparsers.add_parser("pdf2text", help="PDF or directory of PDFs to text (parallel for dirs).")
    parser_pdf2text.add_argument("pdf_path", type=str, help="PDF file or directory of PDFs.")
    parser_pdf2text.add_argument("output_dir", type=str, nargs='?', default=None, help="Optional: Image dir base / specific dir.")
    parser_pdf2text.add_argument("rectangles", type=str, nargs="*", default=[], help="Optional: Crop rectangles.")
    parser_pdf2text.add_argument("output_file", type=str, nargs='?', default=None, help="Optional: Text output dir / file.")
    parser_pdf2text.add_argument("--model", action="append", default=[], help="OCR model(s) to use (overrides presets).")
    parser_pdf2text.add_argument("--repeat", action="append", type=int, default=[], help="Repeats per model (overrides presets).")
    parser_pdf2text.add_argument("--judge-model", type=str, default=None, help="Judge model to use (overrides presets).")
    parser_pdf2text.add_argument("--judge-mode", type=str, default="authoritative", choices=["authoritative"], help="Judge mode.")
    parser_pdf2text.add_argument("--ensemble-strategy", type=str, default=None, help="(Placeholder).")
    parser_pdf2text.add_argument("--trust-score", type=float, default=None, help="(Placeholder).")
    parser_pdf2text.add_argument("--judge-with-image", action="store_true", default=False, help="Judge sees image (overrides presets).")
    parser_pdf2text.add_argument("--no-resume", action="store_true", default=False, help="Disable OCR resume and start this OCR run from scratch.")
    parser_pdf2text.add_argument("--max-page-attempts", type=int, default=40, help="Maximum full OCR attempts per page before pausing the run.")
    parser_pdf2text.add_argument("--max-concurrent-pages", type=int, default=None, help="Pages processed in parallel within one PDF (default: per-model auto-tuner; 1 = sequential).")
    parser_pdf2text.add_argument("--max-image-kb", type=int, default=pic2text.DEFAULT_MAX_IMAGE_KB, help=f"Cap the JPEG payload sent to the OCR API (KB). 0 = disable. Default: {pic2text.DEFAULT_MAX_IMAGE_KB}.")
    parser_pdf2text.set_defaults(func=pdf_to_text)
    
    # --- Text to Anki Command ---
    parser_text2anki = subparsers.add_parser("text2anki", help="Convert text to Anki package.")
    parser_text2anki.add_argument("text_file", type=str, help="Input text file.")
    parser_text2anki.add_argument("anki_file", type=str, help="Output Anki .apkg file.")
    parser_text2anki.add_argument("anki_model", type=str, nargs='?', default=None, help="Model for Anki generation.")
    parser_text2anki.set_defaults(func=text_to_anki)

    # New: JSON→Anki subcommand
    parser_json2anki = subparsers.add_parser(
        "json2anki",
        help="Convert a pre-formatted JSON flashcard file (or all JSON files in a directory) to an Anki package (offline, no LLM)."
    )
    parser_json2anki.add_argument("json_file", type=str, nargs='?', help="Input JSON flashcards file or directory containing JSON files.")
    parser_json2anki.add_argument("anki_file", type=str, nargs='?', help="Output Anki .apkg file (optional, defaults to same name as input with .apkg extension). Ignored for directory input.")
    parser_json2anki.add_argument("--show-format", action="store_true", 
                                help="Print example card structure and exit.")
    parser_json2anki.set_defaults(func=json_to_anki)

    # --- Full Pipeline Command ('process') ---
    parser_process = subparsers.add_parser("process", help="Run entire pipeline sequentially for one PDF.")
    parser_process.add_argument("pdf_path", type=str, help="Input PDF file.")
    parser_process.add_argument("output_dir", type=str, help="Directory for intermediate images.")
    parser_process.add_argument("anki_file", type=str, help="Output Anki .apkg file.")
    parser_process.add_argument("anki_model", type=str, nargs='?', default=None, help="Model for Anki generation.")
    parser_process.add_argument("--model", action="append", default=[], help="OCR model for text extraction (overrides presets).")
    parser_process.add_argument("--repeat", action="append", type=int, default=[], help="Repeats for OCR model (overrides presets).")
    parser_process.add_argument("--judge-model", type=str, default=None, help="Judge model for OCR (overrides presets).")
    parser_process.add_argument("--judge-mode", type=str, default="authoritative", choices=["authoritative"], help="Judge mode for OCR.")
    parser_process.add_argument("--ensemble-strategy", type=str, default=None, help="(Placeholder).")
    parser_process.add_argument("--trust-score", type=float, default=None, help="(Placeholder).")
    parser_process.add_argument("--judge-with-image", action="store_true", default=False, help="Judge sees image in OCR step (overrides presets).")
    parser_process.add_argument("--no-resume", action="store_true", default=False, help="Disable OCR resume and start this OCR run from scratch.")
    parser_process.add_argument("--max-page-attempts", type=int, default=40, help="Maximum full OCR attempts per page before pausing the run.")
    parser_process.add_argument("--max-concurrent-pages", type=int, default=None, help="Pages processed in parallel within one PDF (default: per-model auto-tuner; 1 = sequential).")
    parser_process.add_argument("--max-image-kb", type=int, default=pic2text.DEFAULT_MAX_IMAGE_KB, help=f"Cap the JPEG payload sent to the OCR API (KB). 0 = disable. Default: {pic2text.DEFAULT_MAX_IMAGE_KB}.")
    parser_process.set_defaults(func=process_pdf_to_anki)

    # --- Workflow Command (project-based card generation) ---
    parser_workflow = subparsers.add_parser(
        "workflow",
        help="Project-based Anki card workflow: ingest, integrate, sync, export.",
        description=(
            "Project-based card management workflow.\n"
            "All options are passed through to the workflow manager.\n\n"
            "Common usage:\n"
            "  pdf2anki workflow --project ./my_project --extract\n"
            "  pdf2anki workflow --project ./my_project --ingest notes.txt\n"
            "  pdf2anki workflow --project ./my_project --integrate\n"
            "  pdf2anki workflow --project ./my_project --export\n"
        ),
        add_help=False,
    )
    parser_workflow.add_argument("workflow_args", nargs=argparse.REMAINDER)
    parser_workflow.set_defaults(func=lambda args: _run_workflow(args.workflow_args))

    # --- Configuration Command ---
    parser_config = subparsers.add_parser(
        "config",
        help="View or modify configuration (default models, presets, etc.).",
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            "View or modify pdf2anki configuration.\n"
            "\n"
            "There are TWO tiers of model settings -- this trips most people up, so read once:\n"
            "\n"
            "  1. GLOBAL fallback  (key: 'default_model', 'default_anki_model', 'default_judge_model')\n"
            "       A single model name. Used when nothing else is specified. Lowest priority.\n"
            "\n"
            "  2. PRESET           (key: 'defaults' -- a nested object with 'model', 'repeat',\n"
            "                       'judge_model', 'judge_mode', 'judge_with_image')\n"
            "       Project-level profile. Can hold MULTIPLE models (for ensemble OCR with\n"
            "       a judge picking the best answer) plus matching repeats and judge settings.\n"
            "       OVERRIDES the global fallback when set.\n"
            "\n"
            "Resolution order (highest priority first):\n"
            "  CLI flags  >  Presets (defaults.*)  >  Global (default_*)  >  Interactive prompt\n"
            "\n"
            "Subcommands:\n"
            "  view    Show current config + 'effective settings' (what will actually be used\n"
            "          and from which source). Run this first if anything seems unclear.\n"
            "  set     Change a config value. See 'pdf2anki config set -h' for full examples.\n"
            "  unset   Remove a config key, so the lower-priority source takes over.\n"
            "          Useful for migrating from preset back to global (or clearing entirely).\n"
            "          See 'pdf2anki config unset -h'.\n"
            "\n"
            "Quick reference:\n"
            "  pdf2anki config view                                       # current state + effective values\n"
            "  pdf2anki config set default_model google/gemini-flash-1.5  # set global OCR fallback\n"
            "  pdf2anki config set defaults model google/gemini-flash-1.5 # set preset (recommended for active use)\n"
            "  pdf2anki config unset defaults model                       # drop preset, global takes over\n"
            "  pdf2anki config unset default_model                        # drop global (will prompt at runtime)\n"
        ),
    )
    config_subparsers = parser_config.add_subparsers(title="Config Actions", dest="config_action", required=True)
    parser_config_view = config_subparsers.add_parser(
        "view",
        help="Show current config + effective settings (annotated).",
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            "Prints the raw config JSON followed by an 'Effective settings' block that shows\n"
            "which value will actually be used at runtime and where it comes from\n"
            "(preset vs. global). Also warns if a global setting is shadowed by a preset.\n"
            "\n"
            "Use --raw for JSON-only output (e.g. for scripting / jq pipelines).\n"
        ),
    )
    parser_config_view.add_argument(
        "--raw",
        action="store_true",
        help="Print only the JSON config, without the annotated 'effective settings' block.",
    )
    parser_config_view.set_defaults(func=view_config)
    parser_config_set = config_subparsers.add_parser(
        "set",
        help="Set a config value (global default or preset subkey).",
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            "Set a configuration value.\n"
            "\n"
            "MENTAL MODEL -- read this first:\n"
            "  pdf2anki has TWO model-config tiers. Names look similar but behave differently:\n"
            "\n"
            "    default_model      = ONE global fallback OCR model (string).\n"
            "                         Used only when no preset OCR model is set.\n"
            "    default_anki_model = ONE global model for Anki-card generation (string).\n"
            "                         No preset equivalent -- this is the only place to set it.\n"
            "    default_judge_model= ONE global judge model (string). Global fallback for the\n"
            "                         ensemble-OCR judge; overridden by defaults.judge_model.\n"
            "                         If neither is set, ensemble OCR falls back to the primary\n"
            "                         OCR model as judge (with a warning).\n"
            "    defaults.model     = PRESET list of OCR models (one or more, comma-separated).\n"
            "                         Overrides default_model. Use this for project-level config\n"
            "                         and especially when you want ensemble OCR (multiple models\n"
            "                         + a judge picking the best result).\n"
            "    defaults.repeat              = repeats per preset model (list, comma-separated)\n"
            "    defaults.judge_model         = judge LLM that adjudicates ensemble OCR results\n"
            "    defaults.judge_mode          = currently only 'authoritative'\n"
            "    defaults.judge_with_image    = true|false -- pass image to judge?\n"
            "\n"
            "PRIORITY (highest first):\n"
            "  CLI flags  >  defaults.* (preset)  >  default_* (global)  >  interactive prompt\n"
            "\n"
            "EXAMPLES -- global fallback (single model, lowest priority):\n"
            "  pdf2anki config set default_model google/gemini-flash-1.5\n"
            "  pdf2anki config set default_anki_model google/gemini-2.5-flash\n"
            "  pdf2anki config set default_judge_model openai/gpt-4o\n"
            "\n"
            "EXAMPLES -- preset (overrides global, supports ensembles):\n"
            "  pdf2anki config set defaults model google/gemini-flash-1.5\n"
            "  pdf2anki config set defaults model google/gemini-flash-1.5,openai/gpt-4o   # ensemble\n"
            "  pdf2anki config set defaults repeat 2,1                                    # 2x first model, 1x second\n"
            "  pdf2anki config set defaults judge_model openai/gpt-4o\n"
            "  pdf2anki config set defaults judge_mode authoritative\n"
            "  pdf2anki config set defaults judge_with_image true\n"
            "\n"
            "CLEAR a preset (so global takes over again):\n"
            "  pdf2anki config set defaults model \"\"\n"
            "\n"
            "ADVANCED -- overwrite the whole preset object at once via JSON:\n"
            "  pdf2anki config set defaults '{\"model\": [\"m1\",\"m2\"], \"repeat\": [2,1]}'\n"
            "\n"
            "After any change, run 'pdf2anki config view' to verify effective settings.\n"
        ),
    )
    parser_config_set.add_argument(
        "key",
        type=str,
        help=(
            "Top-level config key. One of:\n"
            "  default_model       (global OCR fallback -- single model string)\n"
            "  default_anki_model  (global Anki-card-generation model -- single model string)\n"
            "  default_judge_model (global ensemble-OCR judge -- single model string)\n"
            "  defaults            (preset object -- requires a subkey as next argument, e.g.\n"
            "                       'defaults model ...', 'defaults repeat ...', etc.)"
        ),
    )
    parser_config_set.add_argument(
        "values",
        nargs='*',
        help=(
            "Value(s) to set. Form depends on key:\n"
            "  default_model / default_anki_model / default_judge_model:  <model_name>  (one value)\n"
            "  defaults <subkey> <value>:           e.g. 'defaults model m1,m2'\n"
            "  defaults '<json>':                   replace entire preset object via JSON string"
        ),
    )
    parser_config_set.set_defaults(func=set_config_value)

    parser_config_unset = config_subparsers.add_parser(
        "unset",
        help="Remove a config key (so the lower-priority source takes over).",
        formatter_class=argparse.RawTextHelpFormatter,
        description=(
            "Remove a configuration key. The next-lower priority source then takes over\n"
            "(see resolution order in 'pdf2anki config -h').\n"
            "\n"
            "USE CASES:\n"
            "  - Preset overrides global, and you want the global to win again:\n"
            "      pdf2anki config unset defaults model\n"
            "  - Wipe the whole project preset block:\n"
            "      pdf2anki config unset defaults\n"
            "  - Clear a global default so pdf2anki prompts you next run:\n"
            "      pdf2anki config unset default_model\n"
            "\n"
            "EXAMPLES:\n"
            "  pdf2anki config unset default_model              # remove global OCR fallback\n"
            "  pdf2anki config unset default_anki_model         # remove global Anki LLM model\n"
            "  pdf2anki config unset default_judge_model        # remove global judge fallback\n"
            "  pdf2anki config unset defaults                   # remove WHOLE preset block\n"
            "  pdf2anki config unset defaults model             # remove just the OCR preset\n"
            "  pdf2anki config unset defaults judge_model\n"
            "  pdf2anki config unset defaults repeat\n"
            "  pdf2anki config unset defaults judge_mode\n"
            "  pdf2anki config unset defaults judge_with_image\n"
            "\n"
            "Unsetting a key that isn't set is safe (prints an info message, no error).\n"
            "After unset, run 'pdf2anki config view' to confirm effective settings.\n"
        ),
    )
    parser_config_unset.add_argument(
        "key",
        type=str,
        help=(
            "Top-level config key to remove. One of:\n"
            "  default_model       (global OCR fallback)\n"
            "  default_anki_model  (global Anki LLM model)\n"
            "  default_judge_model (global ensemble-OCR judge)\n"
            "  defaults            (the whole preset block, OR pair with a subkey to remove just one field)"
        ),
    )
    parser_config_unset.add_argument(
        "subkey",
        type=str,
        nargs='?',
        default=None,
        help=(
            "Optional subkey, valid only when key='defaults'.\n"
            "One of: model, repeat, judge_model, judge_mode, judge_with_image.\n"
            "If omitted with key='defaults', removes the entire preset block."
        ),
    )
    parser_config_unset.set_defaults(func=unset_config_value)

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
    except pic2text.OCRPauseException as e:
        print(f"[PAUSED] {e}", file=sys.stderr)
        sys.exit(3)
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



