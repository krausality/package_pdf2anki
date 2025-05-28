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
from datetime import datetime
from PIL import Image
from dotenv import load_dotenv
import concurrent.futures 
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path 
import sys 
import threading 

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

DEFAULT_OCR_LOG_BASENAME = "ocr"
DEFAULT_JUDGE_LOG_BASENAME = "decisionmaking"
LOG_EXTENSION = ".log"
MAX_API_CALL_THREADS = 5

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

def _image_to_base64(image_path: str) -> str:
    try:
        with Image.open(image_path) as img:
            if img.mode == 'RGBA':
                img = img.convert('RGB')
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG", quality=95) 
            img_bytes = buffered.getvalue()
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
        response = requests.post(
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
            f"Response (truncated): {cleaned_text[:120].replace(chr(10), ' ')}\n"
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
        response = requests.post(
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
            df.write(f"Candidate {i + 1} (Model: {m_name}, Attempt: {att_num}):\n{text_candidate[:200]}...\n---\n")
        df.write(f"--- Judge Picked ---\n{final_text[:500]}...\n-------------------------------------\n")
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

def convert_images_to_text(
    images_dir: str,
    output_file: str,
    model_repeats: List[Tuple[str, int]],
    judge_model: Optional[str] = None,
    judge_mode: str = "authoritative",
    ensemble_strategy: Optional[str] = None,
    trust_score: Optional[float] = None,
    judge_with_image: bool = False,
    verbose: bool = False
) -> str:
    pid = os.getpid() if hasattr(os, 'getpid') else 'main'
    if verbose:
        print(f"[{pid}] convert_images_to_text (pic2text.py) called for images in '{images_dir}', output to '{output_file}'")

    if not model_repeats:
        raise ValueError(f"[{pid}] No OCR model specified in model_repeats.")
    
    total_api_calls_per_image = sum(repeat_count for _, repeat_count in model_repeats)
    if total_api_calls_per_image > 1 and not judge_model:
        raise ValueError(
            f"[{pid}] Multiple OCR calls per image implied (total {total_api_calls_per_image}) "
            "but no judge model specified. This should be caught by the calling function in core.py."
        )

    with open(output_file, "w", encoding="utf-8") as f: f.write("")
    processed_images_count = 0

    output_file_path = Path(output_file)
    # Use sanitize_filename here
    log_file_basename_prefix = sanitize_filename(output_file_path.stem) # <<< --- CORRECTED
    instance_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    unique_log_suffix = f"{log_file_basename_prefix}_pid{pid}_{instance_timestamp}"
    ocr_log_file_path = str(output_file_path.parent / f"{DEFAULT_OCR_LOG_BASENAME}_{unique_log_suffix}{LOG_EXTENSION}")
    judge_decision_log_file_path = str(output_file_path.parent / f"{DEFAULT_JUDGE_LOG_BASENAME}_{unique_log_suffix}{LOG_EXTENSION}")
    
    if verbose:
        print(f"[{pid}] OCR log for this worker: {ocr_log_file_path}")
        print(f"[{pid}] Judge log for this worker: {judge_decision_log_file_path}")

    image_files = [f for f in os.listdir(images_dir) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
    image_files.sort(key=extract_page_number)

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_API_CALL_THREADS, thread_name_prefix=f"OCR_API_Thread_PID{pid}") as executor:
        for image_idx, image_name in enumerate(image_files):
            image_path = os.path.join(images_dir, image_name)
            if verbose: print(f"[{pid}] Submitting OCR tasks for image {image_idx + 1}/{len(image_files)}: {image_name}")
            
            base64_image_data: Optional[str] = None
            try:
                base64_image_data = _image_to_base64(image_path)
            except Exception as e:
                print(f"[{pid}] Failed to convert {image_name} to base64. Error: {e}. Appending error to output.")
                with open(output_file, "a", encoding="utf-8") as f:
                    if processed_images_count > 0: f.write("\n\n")
                    f.write(f"Image: {image_name}\n[ERROR: Failed to load/convert image: {e}]")
                processed_images_count +=1
                continue

            ocr_futures_map = {} 
            model_info_for_judge_ordered: List[Tuple[str,int]] = []

            for model_name, repeat_count in model_repeats:
                for i in range(repeat_count):
                    attempt_num = i + 1
                    future = executor.submit(_post_ocr_request, model_name, base64_image_data, ocr_log_file_path, image_name, attempt_num)
                    # Store future with its metadata for ordered reconstruction
                    ocr_futures_map[future] = (model_name, attempt_num, len(model_info_for_judge_ordered)) # Store original index
                    model_info_for_judge_ordered.append((model_name, attempt_num))
            
            # Initialize results list to match the order of submission
            ocr_results_for_image_ordered: List[str] = [""] * len(model_info_for_judge_ordered)

            for future in concurrent.futures.as_completed(ocr_futures_map):
                _model_name_orig, _attempt_num_orig, original_idx = ocr_futures_map[future]
                try:
                    res_text = future.result()
                    ocr_results_for_image_ordered[original_idx] = res_text
                except Exception as exc_f:
                    err_res_text = f"[ERROR: Future for {_model_name_orig} Att.{_attempt_num_orig} failed directly: {exc_f}]"
                    ocr_results_for_image_ordered[original_idx] = err_res_text
            
            final_text_for_image = ""
            if not any(ocr_results_for_image_ordered): # Check if list is empty or all are empty strings
                final_text_for_image = f"[ERROR: No OCR results gathered for image {image_name}]"
            elif total_api_calls_per_image == 1:
                final_text_for_image = ocr_results_for_image_ordered[0]
            else:
                if judge_model:
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
                        first_valid_ocr = next((r for r in ocr_results_for_image_ordered if not r.startswith(("[ERROR:", "[INFO:"))), None)
                        final_text_for_image = first_valid_ocr if first_valid_ocr else (ocr_results_for_image_ordered[0] if ocr_results_for_image_ordered else "[ERROR: Judge failed and no OCR results]")
                else:
                    print(f"[{pid}] WARNING: Multiple OCR results for {image_name} but no judge. Taking first result.")
                    final_text_for_image = ocr_results_for_image_ordered[0] if ocr_results_for_image_ordered else "[ERROR: No OCR results and no judge]"
            
            with open(output_file, "a", encoding="utf-8") as f:
                if processed_images_count > 0: f.write("\n\n")
                f.write(f"Image: {image_name}\n{final_text_for_image}")
            processed_images_count += 1
            if verbose: print(f"[{pid}] Appended result for {image_name} to {output_file}")

    if verbose: print(f"[{pid}] All images processed for this document worker. Total: {processed_images_count}")
    _archive_old_logs(output_file, [ocr_log_file_path, judge_decision_log_file_path])
    if verbose: print(f"[{pid}] Worker logs archived. Output for '{images_dir}' saved to '{output_file}'.")
    return output_file
