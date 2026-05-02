"""
This software is licensed under the terms specified in LICENSE,
authored by Martin Krause.

Usage is limited to:
- Students enrolled at accredited institutions
- Individuals with an annual income below 15,000€
- Personal desktop PC automation tasks

For commercial usage, including server deployments, please contact:
martinkrausemedia@gmail.com

Refer to the NOTICE file for dependencies and third-party libraries used.

Code partially from:
  https://pub.towardsai.net/enhance-ocr-with-llama-3-2-vision-using-ollama-0b15c7b8905c
"""

import os
import re
import requests
import json
import traceback
import base64
import io
import shutil
import hashlib
import time
from datetime import datetime
from PIL import Image
from dotenv import load_dotenv
import concurrent.futures 
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path 
import sys
import threading

from . import perf_tuner as _perf_tuner

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Per-process requests.Session cache. OpenRouter does not rate-limit paid
# models, but each call without a Session pays a fresh TLS handshake and
# urllib3's default pool would silently throttle past ~10 concurrent sockets.
# Keying by os.getpid() makes this fork-safe (Linux) and is a harmless no-op
# under spawn (Windows / ProcessPoolExecutor) where child modules re-import.
_session_lock = threading.Lock()
_session_by_pid: Dict[int, requests.Session] = {}


def _get_session() -> requests.Session:
    pid = os.getpid()
    s = _session_by_pid.get(pid)
    if s is not None:
        return s
    with _session_lock:
        s = _session_by_pid.get(pid)
        if s is not None:
            return s
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=8,
            pool_maxsize=64,
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _session_by_pid[pid] = s
        return s


def _http_post(**kwargs):
    # Single chokepoint for OpenRouter HTTP calls. Production routes through
    # the per-process Session; tests patch this name directly with side_effect.
    return _get_session().post(**kwargs)


DEFAULT_OCR_LOG_BASENAME = "ocr"
DEFAULT_JUDGE_LOG_BASENAME = "decisionmaking"
LOG_EXTENSION = ".log"
MAX_API_CALL_THREADS = 5
STATE_SCHEMA_VERSION = 1
DEFAULT_MAX_PAGE_ATTEMPTS = 40
DEFAULT_MAX_IMAGE_KB = 800
MIN_LONGEST_EDGE_PX = 1600
MIN_JPEG_QUALITY = 60

OUTPUT_SECTION_HEADER_RE = re.compile(r'^Image:\s*(.+?)\s*$')


class OCRPauseException(RuntimeError):
    """Raised when OCR processing must pause after hitting the per-page attempt limit."""
    pass

# --- Helper function for sanitizing filenames ---
def sanitize_filename(filename: str) -> str:
    """
    Replace any character that is not alphanumeric or underscore with an underscore.
    """
    return re.sub(r'\W+', '_', filename)
# --- End helper function ---

def extract_page_number(filename: str) -> int:
    match = re.search(r'page_(\d+)', filename)
    return int(match.group(1)) if match else float('inf')


def _utcnow_iso() -> str:
    return datetime.now().isoformat()


def _is_error_text(text: Optional[str]) -> bool:
    if not text:
        return False
    return text.lstrip().startswith("[ERROR:")


def _is_info_text(text: Optional[str]) -> bool:
    if not text:
        return False
    return text.lstrip().startswith("[INFO:")


def _is_successful_ocr_text(text: Optional[str]) -> bool:
    if not text:
        return False
    stripped = text.lstrip()
    if not stripped:
        return False
    return not stripped.startswith(("[ERROR:", "[INFO:"))


def _state_file_path_for_output(output_file_path: Path) -> Path:
    return output_file_path.with_name(f"{output_file_path.name}.ocr_state.json")


def _archive_dir_for_output(output_file_path: Path) -> Path:
    return output_file_path.parent / "log_archive"


def _unique_temp_path(path: Path) -> Path:
    # Unique per (pid, thread, monotonic-ns) so concurrent writers never collide
    # on the same .tmp file. os.replace is atomic on the final path.
    suffix = f".{os.getpid()}.{threading.get_ident()}.{time.monotonic_ns()}.tmp"
    return path.with_name(f"{path.name}{suffix}")


def _write_text_atomic(path: Path, content: str) -> None:
    temp_path = _unique_temp_path(path)
    with open(temp_path, "w", encoding="utf-8") as tf:
        tf.write(content)
    _replace_with_retry(temp_path, path)


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    temp_path = _unique_temp_path(path)
    with open(temp_path, "w", encoding="utf-8") as jf:
        json.dump(payload, jf, indent=2, ensure_ascii=False)
    _replace_with_retry(temp_path, path)


def _replace_with_retry(temp_path: Path, target_path: Path, retries: int = 5, base_delay_seconds: float = 0.1) -> None:
    last_permission_error: Optional[PermissionError] = None
    for attempt_idx in range(1, retries + 1):
        try:
            os.replace(temp_path, target_path)
            return
        except PermissionError as perm_err:
            last_permission_error = perm_err
            time.sleep(base_delay_seconds * attempt_idx)

    # Last-resort fallback: overwrite target directly, then remove the temp file.
    # This may not be fully atomic, but prevents losing progress if replace is blocked by transient file locks.
    try:
        with open(temp_path, "rb") as src_f:
            payload = src_f.read()
        with open(target_path, "wb") as dst_f:
            dst_f.write(payload)
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            # Best effort cleanup only; some sync/indexing tools keep transient locks.
            pass
        return
    except Exception:
        if last_permission_error is not None:
            raise last_permission_error
        raise


def _unlink_with_retry(path: Path, retries: int = 10, base_delay_seconds: float = 0.1) -> bool:
    for attempt_idx in range(1, retries + 1):
        try:
            path.unlink(missing_ok=True)
            return True
        except PermissionError:
            time.sleep(base_delay_seconds * attempt_idx)
        except OSError:
            time.sleep(base_delay_seconds * attempt_idx)
    return not path.exists()


def _compute_images_fingerprint(images_dir: str, image_files: List[str]) -> str:
    hasher = hashlib.sha256()
    base_dir = Path(images_dir)
    for image_name in image_files:
        image_path = base_dir / image_name
        if image_path.exists():
            stat = image_path.stat()
            hasher.update(f"{image_name}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8"))
        else:
            hasher.update(f"{image_name}|missing".encode("utf-8"))
    return hasher.hexdigest()


def _load_state_file(path: Path, verbose: bool = False) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as sf:
            return json.load(sf)
    except (json.JSONDecodeError, OSError) as state_err:
        if verbose:
            print(f"[WARN] Failed to load OCR state '{path}': {state_err}")
        return None


def _find_archived_state_candidates(output_file_path: Path) -> List[Path]:
    archive_dir = _archive_dir_for_output(output_file_path)
    if not archive_dir.exists():
        return []
    pattern = f"{output_file_path.name}.ocr_state*.json"
    candidates = [p for p in archive_dir.glob(pattern) if p.is_file()]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates


def _archive_state_file_if_completed(state_file_path: Path, output_file_path: Path, verbose: bool = False) -> Optional[Path]:
    if not state_file_path.exists():
        return None
    archive_folder = _archive_dir_for_output(output_file_path)
    archive_folder.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    archived_name = f"{state_file_path.stem}_{timestamp}{state_file_path.suffix}"
    archived_path = archive_folder / archived_name
    try:
        shutil.move(str(state_file_path), str(archived_path))
        if verbose:
            print(f"[INFO] Archived OCR state: {archived_path}")
        return archived_path
    except PermissionError:
        # Fall back to copy + best-effort delete in environments with transient locks.
        try:
            shutil.copy2(str(state_file_path), str(archived_path))
            removed = _unlink_with_retry(state_file_path)
            if removed:
                print(f"[WARN] OCR state could not be moved atomically; copied+removed via fallback: {archived_path}")
            else:
                print(f"[WARN] OCR state could not be moved atomically; copied to archive but source is still present: {archived_path}")
            return archived_path
        except Exception as archive_err:
            print(f"[WARN] Failed to archive OCR state '{state_file_path}': {archive_err}")
            return None
    except Exception as archive_err:
        print(f"[WARN] Failed to archive OCR state '{state_file_path}': {archive_err}")
        return None


def _print_progress(
    pid: Any,
    total_pages: int,
    done_pages: int,
    resumed_pages: int,
    attempt_cycles: int,
    current_image: Optional[str],
    attempt_idx: Optional[int],
    max_page_attempts: int,
    status: str,
    started_monotonic: float,
    force_print: bool = True
) -> None:
    if not force_print:
        return
    pct = 100.0 if total_pages == 0 else (done_pages / total_pages) * 100.0
    bar_width = 24
    filled = min(bar_width, max(0, int(round((pct / 100.0) * bar_width))))
    bar = f"[{'#' * filled}{'-' * (bar_width - filled)}]"
    elapsed = time.monotonic() - started_monotonic
    current = current_image if current_image else "-"
    if attempt_idx is None:
        attempt_repr = "-/-"
    else:
        attempt_repr = f"{attempt_idx}/{max_page_attempts}"
    print(
        f"[{pid}] [PROGRESS] {bar} {done_pages}/{total_pages} ({pct:5.1f}%) "
        f"resumed={resumed_pages} attempts={attempt_cycles} current={current} attempt={attempt_repr} "
        f"status={status} elapsed={elapsed:.1f}s"
    )


def _parse_output_sections(output_file_path: Path) -> Dict[str, str]:
    if not output_file_path.exists():
        return {}

    with open(output_file_path, "r", encoding="utf-8") as of:
        lines = of.read().splitlines()

    sections: Dict[str, str] = {}
    current_image: Optional[str] = None
    current_body: List[str] = []

    def flush_section() -> None:
        if current_image is None:
            return
        sections[current_image] = "\n".join(current_body).rstrip()

    for line in lines:
        match = OUTPUT_SECTION_HEADER_RE.match(line)
        if match:
            flush_section()
            current_image = match.group(1)
            current_body = []
            continue
        if current_image is not None:
            current_body.append(line)

    flush_section()
    return sections


def _write_output_sections_atomic(output_file_path: Path, image_files: List[str], page_texts: Dict[str, str]) -> None:
    sections: List[str] = []
    for image_name in image_files:
        text = page_texts.get(image_name)
        if text is None:
            continue
        section_text = text.rstrip()
        if section_text:
            sections.append(f"Image: {image_name}\n{section_text}")
        else:
            sections.append(f"Image: {image_name}")
    _write_text_atomic(output_file_path, "\n\n".join(sections))


def _initialize_state_from_legacy(
    image_files: List[str],
    existing_sections: Dict[str, str],
    images_fingerprint: str,
    max_page_attempts: int
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    now = _utcnow_iso()
    pages: Dict[str, Dict[str, Any]] = {}
    page_texts: Dict[str, str] = {}

    for image_name in image_files:
        existing_text = existing_sections.get(image_name)
        if _is_successful_ocr_text(existing_text):
            pages[image_name] = {
                "status": "done",
                "attempts_used": 0,
                "last_error": None,
                "updated_at": now
            }
            page_texts[image_name] = existing_text if existing_text is not None else ""
        else:
            pages[image_name] = {
                "status": "pending",
                "attempts_used": 0,
                "last_error": existing_text.splitlines()[0] if existing_text and _is_error_text(existing_text) else None,
                "updated_at": now
            }

    state: Dict[str, Any] = {
        "schema_version": STATE_SCHEMA_VERSION,
        "images_fingerprint": images_fingerprint,
        "max_page_attempts": max_page_attempts,
        "run_status": "running",
        "pause_reason": None,
        "updated_at": now,
        "pages": pages
    }
    return state, page_texts


def _state_matches_current_images(state: Dict[str, Any], image_files: List[str], images_fingerprint: str) -> bool:
    if not isinstance(state, dict):
        return False
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        return False
    if state.get("images_fingerprint") != images_fingerprint:
        return False
    pages = state.get("pages")
    if not isinstance(pages, dict):
        return False
    for image_name in image_files:
        if image_name not in pages:
            return False
    return True


def _load_or_initialize_state(
    output_file_path: Path,
    state_file_path: Path,
    image_files: List[str],
    existing_sections: Dict[str, str],
    images_fingerprint: str,
    max_page_attempts: int,
    resume_enabled: bool,
    verbose: bool = False
) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, Any]]:
    resume_meta: Dict[str, Any] = {
        "source": "fresh",
        "state_path": None,
        "notes": []
    }

    if not resume_enabled:
        state, page_texts = _initialize_state_from_legacy(
            image_files=image_files,
            existing_sections={},
            images_fingerprint=images_fingerprint,
            max_page_attempts=max_page_attempts
        )
        resume_meta["source"] = "no_resume"
        resume_meta["notes"].append("Resume disabled by --no-resume.")
        return state, page_texts, resume_meta

    loaded_state: Optional[Dict[str, Any]] = None
    chosen_source: Optional[str] = None
    chosen_path: Optional[Path] = None

    main_state_valid: Optional[Dict[str, Any]] = None
    candidate_main = _load_state_file(state_file_path, verbose=verbose)
    if candidate_main is not None:
        if _state_matches_current_images(candidate_main, image_files, images_fingerprint):
            main_state_valid = candidate_main
        elif verbose:
            print(f"[WARN] Ignoring incompatible OCR state file: {state_file_path}")

    archived_state_valid: Optional[Dict[str, Any]] = None
    archived_state_valid_path: Optional[Path] = None
    for archived_state_path in _find_archived_state_candidates(output_file_path):
        archived_candidate = _load_state_file(archived_state_path, verbose=verbose)
        if archived_candidate is None:
            continue
        if _state_matches_current_images(archived_candidate, image_files, images_fingerprint):
            archived_state_valid = archived_candidate
            archived_state_valid_path = archived_state_path
            break
        elif verbose:
            print(f"[WARN] Ignoring incompatible archived OCR state file: {archived_state_path}")

    if main_state_valid is not None and main_state_valid.get("run_status") in {"running", "paused"}:
        loaded_state = main_state_valid
        chosen_source = "state_file"
        chosen_path = state_file_path
    elif archived_state_valid is not None:
        loaded_state = archived_state_valid
        chosen_source = "archived_state"
        chosen_path = archived_state_valid_path
        resume_meta["notes"].append("Loaded resume state from log_archive.")
    elif main_state_valid is not None:
        loaded_state = main_state_valid
        chosen_source = "state_file"
        chosen_path = state_file_path

    if loaded_state is not None:
        resume_meta["source"] = chosen_source or "state_file"
        resume_meta["state_path"] = str(chosen_path) if chosen_path else None

    if loaded_state is None:
        state, page_texts = _initialize_state_from_legacy(
            image_files=image_files,
            existing_sections=existing_sections,
            images_fingerprint=images_fingerprint,
            max_page_attempts=max_page_attempts
        )
        if existing_sections:
            resume_meta["source"] = "legacy_output"
            resume_meta["notes"].append("Built resume state from existing output sections.")
        else:
            resume_meta["source"] = "fresh"
            resume_meta["notes"].append("No prior state/output found; starting fresh.")
        return state, page_texts, resume_meta

    now = _utcnow_iso()
    previous_run_status = loaded_state.get("run_status")
    loaded_state["max_page_attempts"] = max_page_attempts
    loaded_state["images_fingerprint"] = images_fingerprint
    loaded_state["schema_version"] = STATE_SCHEMA_VERSION
    loaded_state["run_status"] = "running"
    loaded_state["pause_reason"] = None
    loaded_state["updated_at"] = now

    pages = loaded_state.get("pages", {})
    page_texts: Dict[str, str] = {}

    for image_name in image_files:
        page_state = pages.get(image_name, {})
        status = page_state.get("status", "pending")
        existing_text = existing_sections.get(image_name)

        if previous_run_status == "paused" and status != "done":
            status = "pending"
            page_state["attempts_used"] = 0

        if status == "done" and _is_successful_ocr_text(existing_text):
            page_texts[image_name] = existing_text if existing_text is not None else ""
            page_state["status"] = "done"
            page_state["last_error"] = None
        elif status == "done":
            page_state["status"] = "pending"
            page_state["last_error"] = "[ERROR: State marked page as done, but no successful section exists in output file.]"
            page_state["attempts_used"] = 0
        else:
            page_state["status"] = "pending"
            page_state["last_error"] = page_state.get("last_error")
            if not isinstance(page_state.get("attempts_used"), int):
                page_state["attempts_used"] = 0

        page_state["updated_at"] = now
        pages[image_name] = page_state

    loaded_state["pages"] = pages
    return loaded_state, page_texts, resume_meta


def _run_ocr_cycle_for_image(
    image_path: str,
    image_name: str,
    model_repeats: List[Tuple[str, int]],
    total_api_calls_per_image: int,
    judge_model: Optional[str],
    judge_with_image: bool,
    ocr_log_file_path: str,
    judge_decision_log_file_path: str,
    executor: concurrent.futures.ThreadPoolExecutor,
    pid: Any,
    verbose: bool,
    max_image_kb: int = 0,
) -> Tuple[bool, Optional[str], str]:
    base64_image_data: Optional[str] = None
    try:
        base64_image_data = _image_to_base64(image_path, max_kb=max_image_kb)
    except Exception as image_err:
        error_text = f"[ERROR: Failed to load/convert image: {image_err}]"
        if verbose:
            print(f"[{pid}] {error_text} ({image_name})")
        return False, None, error_text

    ocr_futures_map: Dict[concurrent.futures.Future, Tuple[str, int, int]] = {}
    model_info_for_judge_ordered: List[Tuple[str, int]] = []

    for model_name, repeat_count in model_repeats:
        for i in range(repeat_count):
            attempt_num = i + 1
            future = executor.submit(
                _post_ocr_request,
                model_name,
                base64_image_data,
                ocr_log_file_path,
                image_name,
                attempt_num
            )
            ocr_futures_map[future] = (model_name, attempt_num, len(model_info_for_judge_ordered))
            model_info_for_judge_ordered.append((model_name, attempt_num))

    ocr_results_for_image_ordered: List[str] = [""] * len(model_info_for_judge_ordered)
    for future in concurrent.futures.as_completed(ocr_futures_map):
        model_name_orig, attempt_num_orig, original_idx = ocr_futures_map[future]
        try:
            result_text = future.result()
            ocr_results_for_image_ordered[original_idx] = result_text
        except Exception as future_err:
            ocr_results_for_image_ordered[original_idx] = (
                f"[ERROR: Future for {model_name_orig} Att.{attempt_num_orig} failed directly: {future_err}]"
            )

    if not any(ocr_results_for_image_ordered):
        final_text_for_image = f"[ERROR: No OCR results gathered for image {image_name}]"
    elif total_api_calls_per_image == 1:
        final_text_for_image = ocr_results_for_image_ordered[0]
    elif judge_model:
        try:
            final_text_for_image = _post_judge_request(
                judge_model=judge_model,
                model_outputs=ocr_results_for_image_ordered,
                image_name=image_name,
                model_info_for_judge=model_info_for_judge_ordered,
                judge_decision_log_file=judge_decision_log_file_path,
                base64_image=base64_image_data if judge_with_image else None,
                judge_with_image=judge_with_image
            )
        except Exception as judge_exc:
            print(f"[{pid}] Judge request for {image_name} failed: {judge_exc}. Defaulting to first valid OCR result.")
            first_valid_ocr = next(
                (res for res in ocr_results_for_image_ordered if _is_successful_ocr_text(res)),
                None
            )
            final_text_for_image = first_valid_ocr if first_valid_ocr else (
                ocr_results_for_image_ordered[0] if ocr_results_for_image_ordered else "[ERROR: Judge failed and no OCR results]"
            )
    else:
        print(f"[{pid}] WARNING: Multiple OCR results for {image_name} but no judge. Taking first result.")
        final_text_for_image = ocr_results_for_image_ordered[0] if ocr_results_for_image_ordered else "[ERROR: No OCR results and no judge]"

    if _is_successful_ocr_text(final_text_for_image):
        return True, final_text_for_image, ""
    return False, None, final_text_for_image

def _image_to_base64(image_path: str, max_kb: int = 0) -> str:
    """Encode image as base64 JPEG. If max_kb > 0, cap the payload size.

    Budget strategy: try quality=95 first. If over budget, reduce quality in
    steps down to MIN_JPEG_QUALITY; if still over, shrink longest edge by 20%
    per iteration down to MIN_LONGEST_EDGE_PX. Below that floor we stop —
    OCR text legibility beats byte count.
    """
    try:
        with Image.open(image_path) as src_img:
            if src_img.mode in ('RGBA', 'P', 'LA'):
                src_img = src_img.convert('RGB')
            elif src_img.mode not in ('RGB', 'L'):
                src_img = src_img.convert('RGB')

            quality = 95
            cur_img = src_img
            buffered = io.BytesIO()
            cur_img.save(buffered, format="JPEG", quality=quality)
            img_bytes = buffered.getvalue()
            orig_size_kb = len(img_bytes) / 1024

            if max_kb > 0 and orig_size_kb > max_kb:
                while (len(img_bytes) / 1024) > max_kb and quality > MIN_JPEG_QUALITY:
                    quality = max(MIN_JPEG_QUALITY, quality - 5)
                    buffered = io.BytesIO()
                    cur_img.save(buffered, format="JPEG", quality=quality)
                    img_bytes = buffered.getvalue()

                while (len(img_bytes) / 1024) > max_kb:
                    w, h = cur_img.size
                    longest = max(w, h)
                    if longest <= MIN_LONGEST_EDGE_PX:
                        break
                    target_longest = max(int(longest * 0.8), MIN_LONGEST_EDGE_PX)
                    scale = target_longest / longest
                    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
                    cur_img = cur_img.resize(new_size, Image.LANCZOS)
                    buffered = io.BytesIO()
                    cur_img.save(buffered, format="JPEG", quality=quality)
                    img_bytes = buffered.getvalue()

                final_size_kb = len(img_bytes) / 1024
                final_w, final_h = cur_img.size
                pid = os.getpid() if hasattr(os, 'getpid') else 'main'
                print(
                    f"[{pid}] [NORMALIZE] {Path(image_path).name}: "
                    f"{orig_size_kb:.0f}KB -> {final_size_kb:.0f}KB "
                    f"(size={final_w}x{final_h}, q={quality})"
                )

        return base64.b64encode(img_bytes).decode("utf-8")
    except Exception as e:
        pid = os.getpid() if hasattr(os, 'getpid') else 'main'
        print(f"[{pid}] Error converting image {image_path} to base64: {e}")
        raise

def _post_ocr_request(model_name: str, base64_image: str, ocr_log_file: str, image_name_for_log: str, attempt_num_for_log: int) -> str:
    start_time = datetime.now()
    pid_str = f"Proc-{os.getpid() if hasattr(os, 'getpid') else 'N/A'}_Thread-{threading.get_ident()}"

    request_payload = {
        "model": model_name,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "**Critical Task:** Perform a complete and lossless textual reconstruction of the "
                        "provided image. You are acting as a perfect digital transcriber with visual "
                        "understanding capabilities.  **Input:** A single image.  **Mandatory Output "
                        "Requirements:** 1.  **Text Transcription (Verbatim & Formatted):** * "
                        "Extract **every single character** of text exactly as it appears. Do not "
                        "summarize or paraphrase.    * Replicate formatting using Markdown: "
                        "`**Bold**`, `*Italic*`, `- Unordered List`, `1. Ordered List`, ` ``` Code Block "
                        "```, standard Markdown tables.    * Represent mathematical content "
                        "accurately: Use `<math>LaTeX expression</math>` for inline math and `<math "
                        "display=\"block\">LaTeX expression</math>` for display/block equations. Ensure "
                        "LaTeX is KaTeX compatible.    * Preserve meaningful line breaks and paragraph "
                        "structures.  2.  **Visual Element Identification & Detailed Description:** * "
                        "Identify **all** non-text elements: photographs, illustrations, charts (bar, "
                        "line, pie, etc.), diagrams (flowcharts, schematics, etc.), icons, logos, and "
                        "significant layout features (columns, borders, headers, footers if visually "
                        "distinct from main text).    * For each visual element, provide a **detailed "
                        "textual description** embedded at the precise location it appears relative to "
                        "the text. Use the format `[Visual Description: <Detailed Description Here>]`. "
                        "* **Description Content:** * **Type:** Explicitly state the type "
                        "(e.g., \"bar chart,\" \"photograph of a cat,\" \"flowchart\").        * "
                        "**Content:** Describe what is depicted. For data visualizations, include title, "
                        "axis labels, data values/series/trends visible in the image. For diagrams, "
                        "describe components, labels, and connections. For photos/illustrations, describe "
                        "the subject, setting, and key details.        * **Semantic Context:** Briefly "
                        "explain the element's apparent purpose or relationship to the adjacent text "
                        "(e.g., \"illustrating the previous paragraph's point,\" \"providing data for the "
                        "analysis below,\" \"company logo\").  3.  **Integration:** Combine the transcribed "
                        "text and the bracketed visual descriptions into a **single Markdown output**. "
                        "The flow and structure should mirror the original image layout as closely as "
                        "textually possible.  **Constraint:** Do not omit *any* text or visual element. "
                        "Strive for absolute completeness and accuracy in both transcription and "
                        "description. The final output must be a comprehensive textual representation "
                        "capturing the full informational content of the image.  Use the original "
                        "language e.g. german. Avoid unnecessary translation to english. "
                    )
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                }
            ]
        }]
    }

    response_data = None
    cleaned_text = f"[ERROR: OCR request for {model_name} did not complete successfully]"
    try:
        response = _http_post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "X-Title": "pdf2anki-ocr"
            },
            data=json.dumps(request_payload),
            timeout=120
        )
        response.raise_for_status()
        response_data = response.json()
        
        if response_data and response_data.get("choices") and \
           isinstance(response_data["choices"], list) and len(response_data["choices"]) > 0 and \
           isinstance(response_data["choices"][0], dict) and response_data["choices"][0].get("message") and \
           isinstance(response_data["choices"][0]["message"], dict):
            cleaned_text = response_data["choices"][0]["message"].get("content", "").strip()
            if not cleaned_text:
                 cleaned_text = "[INFO: API returned empty content for OCR]"
        else:
            problematic_response_summary = str(response_data)[:500]
            cleaned_text = f"[ERROR: Unexpected API response structure. Summary: {problematic_response_summary}]"
            print(f"[{pid_str}] OCR WARNING for {image_name_for_log}, attempt {attempt_num_for_log}, model {model_name}: {cleaned_text}")

    except requests.exceptions.Timeout:
        cleaned_text = f"[ERROR: API Request Timed Out after 120s for model {model_name}]"
        print(f"[{pid_str}] OCR TIMEOUT for {image_name_for_log}, attempt {attempt_num_for_log}, model {model_name}")
    except requests.exceptions.RequestException as exc:
        cleaned_text = f"[ERROR: API Request Failed - {type(exc).__name__}: {str(exc)[:100]}]"
        print(f"[{pid_str}] OCR REQUEST_EXCEPTION for {image_name_for_log}, attempt {attempt_num_for_log}, model {model_name}: {exc}")
    except Exception as exc: 
        cleaned_text = f"[ERROR: OCR Processing Failed - {type(exc).__name__}: {str(exc)[:100]}]"
        print(f"[{pid_str}] OCR GENERAL_EXCEPTION for {image_name_for_log}, attempt {attempt_num_for_log}, model {model_name}: {exc}")
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    with open(ocr_log_file, "a", encoding="utf-8") as lf:
        lf.write(
            f"\n[{pid_str}] [OCR CALL COMPLETED] {start_time.isoformat()} => {end_time.isoformat()} ({duration:.2f}s)\n"
            f"Image: {image_name_for_log}, Model: {model_name}, Attempt: {attempt_num_for_log}\n"
            f"Response: {cleaned_text.replace(chr(10), ' ')}\n"
            "-----------------------------------------\n"
        )
    return cleaned_text

def _post_judge_request(
    judge_model: str,
    model_outputs: List[str],
    image_name: str,
    model_info_for_judge: List[Tuple[str, int]],
    judge_decision_log_file: str,
    base64_image: Optional[str] = None,
    judge_with_image: bool = False
) -> str:
    pid_str = f"Proc-{os.getpid() if hasattr(os, 'getpid') else 'N/A'}_Thread-{threading.get_ident()}"
    start_time = datetime.now()

    valid_candidates_for_judge = []
    valid_model_info_for_judge = []
    for idx, text_candidate in enumerate(model_outputs):
        if not text_candidate.startswith(("[ERROR:", "[INFO: API returned empty content for OCR]")): # More robust check
            valid_candidates_for_judge.append(text_candidate)
            valid_model_info_for_judge.append(model_info_for_judge[idx])

    if not valid_candidates_for_judge:
        error_summary = "; ".join([f"'{output[:50]}...'" for output in model_outputs]) if model_outputs else "No candidates provided."
        fallback_text = f"[ERROR: No valid OCR candidates to judge for {image_name}. Original errors/info: {error_summary}]"
        print(f"[{pid_str}] JUDGE SKIPPED for {image_name}: No valid candidates. Fallback: {fallback_text}")
        with open(judge_decision_log_file, "a", encoding="utf-8") as df:
            df.write(f"\n[{pid_str}] [Judge SKIPPED - No Valid Candidates] {datetime.now().isoformat()}\n")
            df.write(f"Image: {image_name}\nJudge Model: {judge_model}\n")
            df.write(f"Original Candidates (summary): {error_summary}\n")
            df.write(f"Fallback Text: {fallback_text}\n-------------------------------------\n")
        return fallback_text
    
    enumerations = []
    for i, text_candidate in enumerate(valid_candidates_for_judge):
        model_name, attempt_num = valid_model_info_for_judge[i]
        header = f"Candidate {i + 1} (from Model: {model_name}, Attempt: {attempt_num}):"
        enumerations.append(f"{header}\n---\n{text_candidate}\n---")
    
    enumerations_str = "\n\n".join(enumerations)
    content_blocks: List[Dict[str, Any]] = []
    
    prompt_intro_text = ""
    if judge_with_image and base64_image:
        content_blocks.append({"type": "text", "text": "This is the original image that was processed by the OCR models:"})
        content_blocks.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}})
        prompt_intro_text = (
            "Below are the textual outputs generated by one or more OCR models for the image shown above. "
            "Your task is to act as an authoritative judge. Review all candidates carefully. "
            "Select the single candidate that provides the most accurate, complete, and well-formatted "
            "transcription of the image's content, including all text and descriptions of visual elements as requested in the original OCR prompt. "
            "Consider verbatim accuracy, preservation of formatting (Markdown, LaTeX), and the quality of visual descriptions.\n\n"
            "The candidates are:\n\n"
        )
    else: 
        prompt_intro_text = (
            "Below are textual outputs generated by one or more OCR models for an image (not shown to you). "
            "Your task is to act as an authoritative judge. Review all candidates carefully. "
            "Select the single candidate that appears to be the most accurate, complete, and well-formatted "
            "transcription, assuming it was derived from an image. "
            "Consider verbatim accuracy, preservation of formatting (Markdown, LaTeX), and the quality of any visual descriptions mentioned.\n\n"
            "The candidates are:\n\n"
        )
    
    content_blocks.append({
        "type": "text",
        "text": f"{prompt_intro_text}{enumerations_str}\n\nBased on your assessment, please output ONLY the full text of the BEST candidate. Do NOT include the candidate number, model name, or any other commentary. Your response should be solely the chosen text itself."
    })

    request_payload = {"model": judge_model, "messages": [{"role": "user", "content": content_blocks}]}
    final_text = f"[ERROR: Judge request for {judge_model} did not complete successfully]"
    response_data_judge = None

    try:
        response = _http_post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json", "X-Title": "pdf2anki-judge"},
            data=json.dumps(request_payload),
            timeout=120
        )
        response.raise_for_status()
        response_data_judge = response.json()
        if response_data_judge and response_data_judge.get("choices") and \
           isinstance(response_data_judge["choices"], list) and len(response_data_judge["choices"]) > 0 and \
           isinstance(response_data_judge["choices"][0], dict) and response_data_judge["choices"][0].get("message") and \
           isinstance(response_data_judge["choices"][0]["message"], dict):
            final_text = response_data_judge["choices"][0]["message"].get("content", "").strip()
            if not final_text: 
                 final_text = "[INFO: Judge returned empty content. Defaulting to first valid candidate.]"
                 if valid_candidates_for_judge: final_text = valid_candidates_for_judge[0]
                 else: final_text = "[ERROR: Judge returned empty, and no valid candidates to fallback to.]"
        else:
            final_text = f"[ERROR: Judge returned unexpected response. Defaulting to first valid candidate.]"
            if valid_candidates_for_judge: final_text = valid_candidates_for_judge[0]
            print(f"[{pid_str}] JUDGE WARNING for {image_name}, model {judge_model}: Unexpected API. Data: {str(response_data_judge)[:500]}")
    
    except requests.exceptions.Timeout:
        final_text = f"[ERROR: Judge API Request Timed Out for model {judge_model}. Defaulting to first valid candidate.]"
        if valid_candidates_for_judge: final_text = valid_candidates_for_judge[0]
        print(f"[{pid_str}] JUDGE TIMEOUT for {image_name}, model {judge_model}")
    except requests.exceptions.RequestException as exc:
        final_text = f"[ERROR: Judge API Request Failed - {type(exc).__name__}. Defaulting to first valid candidate.]"
        if valid_candidates_for_judge: final_text = valid_candidates_for_judge[0]
        print(f"[{pid_str}] JUDGE REQUEST_EXCEPTION for {image_name}, model {judge_model}: {exc}")
    except Exception as exc:
        final_text = f"[ERROR: Judge Processing Failed - {type(exc).__name__}. Defaulting to first valid candidate.]"
        if valid_candidates_for_judge: final_text = valid_candidates_for_judge[0]
        print(f"[{pid_str}] JUDGE GENERAL_EXCEPTION for {image_name}, model {judge_model}: {exc}")

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    with open(judge_decision_log_file, "a", encoding="utf-8") as df:
        df.write(f"\n[{pid_str}] [Judge Decision] {start_time.isoformat()} => {end_time.isoformat()} ({duration:.2f}s)\n")
        df.write(f"Image: {image_name}\nJudge Model: {judge_model}\nJudge with image: {judge_with_image}\n")
        df.write("--- Valid Candidates Presented to Judge ---\n")
        for i, text_candidate in enumerate(valid_candidates_for_judge):
            m_name, att_num = valid_model_info_for_judge[i]
            df.write(f"Candidate {i + 1} (Model: {m_name}, Attempt: {att_num}):\n{text_candidate}\n---\n")
        df.write(f"--- Judge Picked ---\n{final_text}\n-------------------------------------\n")
    return final_text

def _archive_old_logs(output_file_path_str: str, log_files_to_archive: List[str]) -> None:
    try:
        output_dir = Path(output_file_path_str).parent
        archive_folder = output_dir / "log_archive"
        archive_folder.mkdir(parents=True, exist_ok=True)
        for log_file_path_str in log_files_to_archive:
            log_file = Path(log_file_path_str)
            if log_file.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                archived_name = f"{log_file.stem}_{timestamp}{log_file.suffix}"
                shutil.move(str(log_file), str(archive_folder / archived_name))
    except Exception as e:
        pid = os.getpid() if hasattr(os, 'getpid') else 'main'
        print(f"[{pid}] Warning: Failed to archive log files for {output_file_path_str}: {e}")


def _process_single_page(
    *,
    image_name: str,
    image_path: str,
    image_idx: int,
    state: Dict[str, Any],
    page_texts: Dict[str, str],
    image_files: List[str],
    output_file_path: Path,
    state_file_path: Path,
    model_repeats: List[Tuple[str, int]],
    total_api_calls_per_image: int,
    judge_model: Optional[str],
    judge_with_image: bool,
    ocr_log_file_path: str,
    judge_decision_log_file_path: str,
    executor: concurrent.futures.ThreadPoolExecutor,
    max_page_attempts: int,
    pid: Any,
    verbose: bool,
    no_resume: bool,
    total_pages: int,
    resumed_pages_count: int,
    started_monotonic: float,
    counters: Dict[str, int],
    state_lock: threading.RLock,
    pause_event: threading.Event,
    max_image_kb: int = 0,
) -> bool:
    """Process a single page with retries. Mutates state, page_texts, and counters.

    counters keys: processed, attempt_cycles, failed_cycles, newly_done.
    state_lock guards state/page_texts/counters/file-writes; OCR API calls run outside the lock.
    pause_event is set by the first page that hits max_page_attempts — other in-flight
    pages short-circuit before their next retry so the pool drains quickly.

    Returns True if the page ended up done; raises OCRPauseException if max
    attempts were hit or the logic-invariant check fails.
    """
    with state_lock:
        page_state = state["pages"][image_name]
        already_done = page_state.get("status") == "done" and not no_resume

    if already_done:
        if verbose:
            print(f"[{pid}] Skipping already completed image {image_idx + 1}/{len(image_files)}: {image_name}")
        return True

    if verbose:
        print(f"[{pid}] Processing image {image_idx + 1}/{len(image_files)}: {image_name}")

    with state_lock:
        attempts_used = int(page_state.get("attempts_used", 0))
    page_completed = False

    for attempt_idx in range(attempts_used + 1, max_page_attempts + 1):
        if pause_event.is_set():
            # Another page triggered a pause; stop retrying so the pool drains.
            if verbose:
                print(f"[{pid}] Pause signalled; aborting retries for {image_name}.")
            break

        with state_lock:
            counters["attempt_cycles"] += 1
            _print_progress(
                pid=pid,
                total_pages=total_pages,
                done_pages=counters["processed"],
                resumed_pages=resumed_pages_count,
                attempt_cycles=counters["attempt_cycles"],
                current_image=image_name,
                attempt_idx=attempt_idx,
                max_page_attempts=max_page_attempts,
                status="attempting",
                started_monotonic=started_monotonic,
                force_print=True
            )

        is_success, final_text, error_text = _run_ocr_cycle_for_image(
            image_path=image_path,
            image_name=image_name,
            model_repeats=model_repeats,
            total_api_calls_per_image=total_api_calls_per_image,
            judge_model=judge_model,
            judge_with_image=judge_with_image,
            ocr_log_file_path=ocr_log_file_path,
            judge_decision_log_file_path=judge_decision_log_file_path,
            executor=executor,
            pid=pid,
            verbose=verbose,
            max_image_kb=max_image_kb,
        )

        with state_lock:
            page_state["attempts_used"] = attempt_idx
            page_state["updated_at"] = _utcnow_iso()

            if is_success and final_text is not None:
                page_state["status"] = "done"
                page_state["last_error"] = None
                # Only promote run_status to "running" if we're not already paused —
                # otherwise a late-success could overwrite a paused sibling's state.
                if state.get("run_status") != "paused":
                    state["run_status"] = "running"
                    state["pause_reason"] = None
                state["updated_at"] = _utcnow_iso()
                page_texts[image_name] = final_text

                _write_output_sections_atomic(output_file_path, image_files, page_texts)
                _write_json_atomic(state_file_path, state)
                counters["processed"] += 1
                counters["newly_done"] += 1
                page_completed = True

                _print_progress(
                    pid=pid,
                    total_pages=total_pages,
                    done_pages=counters["processed"],
                    resumed_pages=resumed_pages_count,
                    attempt_cycles=counters["attempt_cycles"],
                    current_image=image_name,
                    attempt_idx=attempt_idx,
                    max_page_attempts=max_page_attempts,
                    status="completed",
                    started_monotonic=started_monotonic,
                    force_print=True
                )
                break

            counters["failed_cycles"] += 1
            page_state["status"] = "pending"
            page_state["last_error"] = (error_text or "[ERROR: OCR cycle failed without a concrete error message.]")[:1000]
            state["updated_at"] = _utcnow_iso()
            _write_json_atomic(state_file_path, state)

            if attempt_idx >= max_page_attempts:
                page_state["status"] = "paused"
                state["run_status"] = "paused"
                state["pause_reason"] = (
                    f"Reached max_page_attempts={max_page_attempts} for '{image_name}'. "
                    "Fix external issue and rerun to resume."
                )
                state["updated_at"] = _utcnow_iso()
                _write_json_atomic(state_file_path, state)
                _print_progress(
                    pid=pid,
                    total_pages=total_pages,
                    done_pages=counters["processed"],
                    resumed_pages=resumed_pages_count,
                    attempt_cycles=counters["attempt_cycles"],
                    current_image=image_name,
                    attempt_idx=attempt_idx,
                    max_page_attempts=max_page_attempts,
                    status="paused",
                    started_monotonic=started_monotonic,
                    force_print=True
                )
                pause_reason = state["pause_reason"]
                pause_event.set()
                raise OCRPauseException(pause_reason)

        # Bounded backoff before retrying this page (outside the lock).
        backoff_seconds = min(5.0, 0.5 * attempt_idx)
        if verbose:
            print(f"[{pid}] Retry backoff for {image_name}: sleeping {backoff_seconds:.1f}s")
        time.sleep(backoff_seconds)

    with state_lock:
        current_status = page_state.get("status")
    if not page_completed and current_status != "paused" and not pause_event.is_set():
        raise OCRPauseException(
            f"Page '{image_name}' did not complete and was not marked paused. "
            "Stopping to avoid ambiguous state."
        )

    return page_completed


def convert_images_to_text(
    images_dir: str,
    output_file: str,
    model_repeats: List[Tuple[str, int]],
    judge_model: Optional[str] = None,
    judge_mode: str = "authoritative",
    ensemble_strategy: Optional[str] = None,
    trust_score: Optional[float] = None,
    judge_with_image: bool = False,
    no_resume: bool = False,
    max_page_attempts: int = DEFAULT_MAX_PAGE_ATTEMPTS,
    verbose: bool = False,
    max_concurrent_pages: int = 1,
    max_image_kb: int = DEFAULT_MAX_IMAGE_KB,
) -> str:
    pid = os.getpid() if hasattr(os, 'getpid') else 'main'
    if verbose:
        print(
            f"[{pid}] convert_images_to_text called for images in '{images_dir}', "
            f"output to '{output_file}', resume={'off' if no_resume else 'on'}, "
            f"max_page_attempts={max_page_attempts}"
        )

    if not model_repeats:
        raise ValueError(f"[{pid}] No OCR model specified in model_repeats.")

    if max_page_attempts < 1:
        raise ValueError(f"[{pid}] max_page_attempts must be >= 1, got {max_page_attempts}.")

    if max_concurrent_pages < 1:
        raise ValueError(f"[{pid}] max_concurrent_pages must be >= 1, got {max_concurrent_pages}.")

    if judge_mode != "authoritative" and verbose:
        print(f"[{pid}] WARN: Unsupported judge_mode '{judge_mode}'. Falling back to authoritative behavior.")

    if ensemble_strategy is not None and verbose:
        print(f"[{pid}] INFO: ensemble_strategy is currently a placeholder and has no runtime effect.")

    if trust_score is not None and verbose:
        print(f"[{pid}] INFO: trust_score is currently a placeholder and has no runtime effect.")

    total_api_calls_per_image = sum(repeat_count for _, repeat_count in model_repeats)
    if total_api_calls_per_image > 1 and not judge_model:
        raise ValueError(
            f"[{pid}] Multiple OCR calls per image implied (total {total_api_calls_per_image}) "
            "but no judge model specified. This should be caught by the calling function in core.py."
        )

    output_file_path = Path(output_file)
    state_file_path = _state_file_path_for_output(output_file_path)

    log_file_basename_prefix = sanitize_filename(output_file_path.stem)
    instance_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    unique_log_suffix = f"{log_file_basename_prefix}_pid{pid}_{instance_timestamp}"
    ocr_log_file_path = str(output_file_path.parent / f"{DEFAULT_OCR_LOG_BASENAME}_{unique_log_suffix}{LOG_EXTENSION}")
    judge_decision_log_file_path = str(output_file_path.parent / f"{DEFAULT_JUDGE_LOG_BASENAME}_{unique_log_suffix}{LOG_EXTENSION}")

    if verbose:
        print(f"[{pid}] OCR log for this worker: {ocr_log_file_path}")
        print(f"[{pid}] Judge log for this worker: {judge_decision_log_file_path}")

    image_files = [f for f in os.listdir(images_dir) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
    image_files.sort(key=extract_page_number)

    images_fingerprint = _compute_images_fingerprint(images_dir, image_files)
    existing_sections = _parse_output_sections(output_file_path) if not no_resume else {}

    state, page_texts, resume_meta = _load_or_initialize_state(
        output_file_path=output_file_path,
        state_file_path=state_file_path,
        image_files=image_files,
        existing_sections=existing_sections,
        images_fingerprint=images_fingerprint,
        max_page_attempts=max_page_attempts,
        resume_enabled=not no_resume,
        verbose=verbose
    )

    # Immediately materialize "known-good only" output; this removes stale [ERROR] sections from prior runs.
    _write_output_sections_atomic(output_file_path, image_files, page_texts)
    _write_json_atomic(state_file_path, state)

    total_pages = len(image_files)
    processed_images_count = sum(
        1 for image_name in image_files
        if state.get("pages", {}).get(image_name, {}).get("status") == "done"
    )
    resumed_pages_count = processed_images_count
    newly_done_pages_count = 0
    attempt_cycles = 0
    failed_attempt_cycles = 0
    started_monotonic = time.monotonic()

    state_source = resume_meta.get("source", "unknown")
    state_path_used = resume_meta.get("state_path")
    print(
        f"[{pid}] [RESUME] source={state_source}, state_path={state_path_used or '-'}, "
        f"output={output_file}, images_dir={images_dir}"
    )
    notes = resume_meta.get("notes", [])
    for note in notes:
        print(f"[{pid}] [RESUME] {note}")
    print(
        f"[{pid}] [RESUME] total_pages={total_pages}, already_done={resumed_pages_count}, "
        f"pending={max(0, total_pages - resumed_pages_count)}, max_page_attempts={max_page_attempts}"
    )
    _print_progress(
        pid=pid,
        total_pages=total_pages,
        done_pages=processed_images_count,
        resumed_pages=resumed_pages_count,
        attempt_cycles=attempt_cycles,
        current_image=None,
        attempt_idx=None,
        max_page_attempts=max_page_attempts,
        status="initialized",
        started_monotonic=started_monotonic
    )

    counters: Dict[str, int] = {
        "processed": processed_images_count,
        "attempt_cycles": attempt_cycles,
        "failed_cycles": failed_attempt_cycles,
        "newly_done": newly_done_pages_count,
    }
    state_lock = threading.RLock()
    pause_event = threading.Event()

    # Size the API-call pool so concurrent pages don't starve each other.
    # Each page may fan out up to total_api_calls_per_image requests; cap at 20
    # to stay polite to the upstream API.
    api_pool_size = max(
        MAX_API_CALL_THREADS,
        max_concurrent_pages * max(1, total_api_calls_per_image),
    )
    api_pool_size = min(api_pool_size, 20)

    try:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=api_pool_size,
            thread_name_prefix=f"OCR_API_Thread_PID{pid}"
        ) as executor:
            if max_concurrent_pages == 1:
                for image_idx, image_name in enumerate(image_files):
                    image_path = os.path.join(images_dir, image_name)
                    _process_single_page(
                        image_name=image_name,
                        image_path=image_path,
                        image_idx=image_idx,
                        state=state,
                        page_texts=page_texts,
                        image_files=image_files,
                        output_file_path=output_file_path,
                        state_file_path=state_file_path,
                        model_repeats=model_repeats,
                        total_api_calls_per_image=total_api_calls_per_image,
                        judge_model=judge_model,
                        judge_with_image=judge_with_image,
                        ocr_log_file_path=ocr_log_file_path,
                        judge_decision_log_file_path=judge_decision_log_file_path,
                        executor=executor,
                        max_page_attempts=max_page_attempts,
                        pid=pid,
                        verbose=verbose,
                        no_resume=no_resume,
                        total_pages=total_pages,
                        resumed_pages_count=resumed_pages_count,
                        started_monotonic=started_monotonic,
                        counters=counters,
                        state_lock=state_lock,
                        pause_event=pause_event,
                        max_image_kb=max_image_kb,
                    )
            else:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=max_concurrent_pages,
                    thread_name_prefix=f"OCR_Page_Thread_PID{pid}",
                ) as page_executor:
                    futures = []
                    for image_idx, image_name in enumerate(image_files):
                        image_path = os.path.join(images_dir, image_name)
                        fut = page_executor.submit(
                            _process_single_page,
                            image_name=image_name,
                            image_path=image_path,
                            image_idx=image_idx,
                            state=state,
                            page_texts=page_texts,
                            image_files=image_files,
                            output_file_path=output_file_path,
                            state_file_path=state_file_path,
                            model_repeats=model_repeats,
                            total_api_calls_per_image=total_api_calls_per_image,
                            judge_model=judge_model,
                            judge_with_image=judge_with_image,
                            ocr_log_file_path=ocr_log_file_path,
                            judge_decision_log_file_path=judge_decision_log_file_path,
                            executor=executor,
                            max_page_attempts=max_page_attempts,
                            pid=pid,
                            verbose=verbose,
                            no_resume=no_resume,
                            total_pages=total_pages,
                            resumed_pages_count=resumed_pages_count,
                            started_monotonic=started_monotonic,
                            counters=counters,
                            state_lock=state_lock,
                            pause_event=pause_event,
                            max_image_kb=max_image_kb,
                        )
                        futures.append(fut)

                    # Drain all futures. Remember the first pause but let the
                    # rest finish so in-flight pages record their progress.
                    first_pause: Optional[OCRPauseException] = None
                    for fut in concurrent.futures.as_completed(futures):
                        try:
                            fut.result()
                        except OCRPauseException as pause_exc:
                            if first_pause is None:
                                first_pause = pause_exc
                            # pause_event is already set by the raising page;
                            # other pages will short-circuit on their next retry.
                    if first_pause is not None:
                        raise first_pause

        processed_images_count = counters["processed"]
        newly_done_pages_count = counters["newly_done"]
        attempt_cycles = counters["attempt_cycles"]
        failed_attempt_cycles = counters["failed_cycles"]

        state["run_status"] = "completed"
        state["pause_reason"] = None
        state["updated_at"] = _utcnow_iso()
        _write_json_atomic(state_file_path, state)
        _write_output_sections_atomic(output_file_path, image_files, page_texts)
        archived_state_path = _archive_state_file_if_completed(
            state_file_path=state_file_path,
            output_file_path=output_file_path,
            verbose=verbose
        )

        elapsed_seconds = time.monotonic() - started_monotonic
        print(
            f"[{pid}] [SUMMARY] run_status=completed total_pages={total_pages} "
            f"resumed_pages={resumed_pages_count} newly_done={newly_done_pages_count} "
            f"attempt_cycles={attempt_cycles} failed_attempts={failed_attempt_cycles} "
            f"elapsed={elapsed_seconds:.1f}s archived_state={archived_state_path or '-'}"
        )

        if verbose:
            print(f"[{pid}] All images processed successfully for this document worker. Total: {processed_images_count}")
        _perf_tuner.record_observation(
            model_id=model_repeats[0][0] if model_repeats else "",
            concurrency=max_concurrent_pages,
            pages_completed=newly_done_pages_count,
            errors=failed_attempt_cycles,
            paused=False,
        )
        return output_file
    except OCRPauseException:
        processed_images_count = counters["processed"]
        newly_done_pages_count = counters["newly_done"]
        attempt_cycles = counters["attempt_cycles"]
        failed_attempt_cycles = counters["failed_cycles"]
        elapsed_seconds = time.monotonic() - started_monotonic
        print(
            f"[{pid}] [SUMMARY] run_status=paused total_pages={total_pages} "
            f"resumed_pages={resumed_pages_count} newly_done={newly_done_pages_count} "
            f"attempt_cycles={attempt_cycles} failed_attempts={failed_attempt_cycles} "
            f"elapsed={elapsed_seconds:.1f}s"
        )
        _perf_tuner.record_observation(
            model_id=model_repeats[0][0] if model_repeats else "",
            concurrency=max_concurrent_pages,
            pages_completed=newly_done_pages_count,
            errors=failed_attempt_cycles,
            paused=True,
        )
        raise
    finally:
        _archive_old_logs(output_file, [ocr_log_file_path, judge_decision_log_file_path])
        if verbose:
            print(f"[{pid}] Worker logs archived. Output for '{images_dir}' saved to '{output_file}'.")
