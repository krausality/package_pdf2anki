"""Shared harness for the public OCR model-selection benchmark.

Uses the *production* prompt and the *production* image encoder from pdf2anki,
so measured quality and cost transfer 1:1 to `pdf2anki pdf2text`.

Two objective metrics, both independent of any LLM's judgement:
  * text_recall  -- how much of the known slide text was transcribed
  * data_accuracy -- how many known chart/table/graph values were read correctly

The second one is what this corpus buys us. In the earlier study against real
lecture slides, data fidelity could only be estimated by an LLM rubric, because
nobody knew the true bar values. Here the slides are generated, so the values
are known exactly and the metric is a plain count of hits.
"""
import json, os, re, sys, threading, time, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # .../ocr_model_selection
REPO = ROOT.parent.parent                          # .../package_pdf2anki

sys.path.insert(0, str(REPO))
import requests
from pdf2anki import pic2text

CORPUS = ROOT / "corpus"
PAGES = ROOT / "pages"
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)

TRUTH = json.loads((CORPUS / "truth.json").read_text(encoding="utf-8"))


def _load_key():
    k = os.getenv("OPENROUTER_API_KEY", "")
    if k:
        return k
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("no OPENROUTER_API_KEY (set the env var or put it in .env)")


API_KEY = _load_key()
URL = "https://openrouter.ai/api/v1/chat/completions"

# --- the exact production OCR prompt (pic2text._post_ocr_request) ---
OCR_PROMPT = (
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

_b64_cache, _lock = {}, threading.Lock()


def image_b64(path: Path) -> str:
    """Production encoder: pic2text._image_to_base64 with DEFAULT_MAX_IMAGE_KB."""
    with _lock:
        if path.name in _b64_cache:
            return _b64_cache[path.name]
    b = pic2text._image_to_base64(str(path), max_kb=pic2text.DEFAULT_MAX_IMAGE_KB)
    with _lock:
        _b64_cache[path.name] = b
    return b


def call(model: str, content_blocks, title="bench", timeout=300, retries=3):
    payload = {"model": model, "messages": [{"role": "user", "content": content_blocks}],
               "usage": {"include": True}}
    last = None
    for attempt in range(retries):
        t0 = time.time()
        try:
            r = requests.post(URL, headers={
                "Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json",
                "X-Title": title}, data=json.dumps(payload), timeout=timeout)
            dt = time.time() - t0
            if r.status_code != 200:
                last = f"HTTP {r.status_code}: {r.text[:300]}"
                if r.status_code in (429, 500, 502, 503, 520, 524):
                    time.sleep(3 * (attempt + 1)); continue
                return {"ok": False, "error": last, "latency": dt}
            d = r.json()
            if not d.get("choices"):
                last = f"no choices: {str(d)[:300]}"; time.sleep(2); continue
            text = ((d["choices"][0].get("message") or {}).get("content") or "").strip()
            u = d.get("usage") or {}
            return {"ok": bool(text), "text": text, "latency": dt,
                    "prompt_tokens": u.get("prompt_tokens"),
                    "completion_tokens": u.get("completion_tokens"),
                    "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                    "cost": u.get("cost"), "finish": d["choices"][0].get("finish_reason"),
                    "error": None if text else "empty content"}
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:200]}"
            time.sleep(3 * (attempt + 1))
    return {"ok": False, "error": last, "latency": None}


def ocr_call(model: str, img_path: Path):
    return call(model, [
        {"type": "text", "text": OCR_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64(img_path)}"}},
    ], title="pdf2anki-bench-ocr")


# ---------------- objective metric 1: text recall ----------------
_WORD = re.compile(r"[0-9A-Za-zÄÖÜäöüß_.,()\-+*/=<>%]+", re.UNICODE)


def norm_tokens(text: str):
    t = unicodedata.normalize("NFKC", text or "").replace("­", "")
    t = re.sub(r"[*_`#>|\\]", " ", t)
    t = re.sub(r"<math[^>]*>|</math>", " ", t)
    toks = [w.strip(".,()").lower() for w in _WORD.findall(re.sub(r"\s+", " ", t))]
    return [w for w in toks if w]


def truth_tokens(page_key: str):
    return norm_tokens(" ".join(TRUTH[page_key]["text"]))


def recall(gt_tokens, cand_text):
    from collections import Counter
    if not gt_tokens:
        return None
    gt, cand = Counter(gt_tokens), Counter(norm_tokens(cand_text))
    return sum(min(n, cand.get(w, 0)) for w, n in gt.items()) / sum(gt.values())


def order_score(gt_tokens, cand_text):
    import difflib
    cand = norm_tokens(cand_text)
    if not gt_tokens or not cand:
        return 0.0
    sm = difflib.SequenceMatcher(None, gt_tokens, cand, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / len(gt_tokens)


# ---------------- objective metric 2: data accuracy ----------------
_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")
WINDOW = 90          # characters after a label in which its value must appear


def _flat(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text or "").split())


def data_hits(page_key: str, cand_text: str):
    """Return (hits, total, misses) for the known label->value pairs of a page.

    A hit means: the label appears in the output, and the correct number appears
    within WINDOW characters after it. That window matters -- without it, a page
    containing the digit 7 anywhere would score a hit for every label whose value
    is 7. Labels the model never mentions count as misses, not as skips.
    """
    spec = TRUTH[page_key]
    pairs = []
    if "values" in spec:
        pairs += [(k, str(v)) for k, v in spec["values"].items()]
    if "rows" in spec:                       # table: row label -> each cell
        for row in spec["rows"]:
            pairs += [(row[0], c) for c in row[1:]]
    if not pairs:
        return None
    flat = _flat(cand_text)
    low = flat.lower()
    hits, misses = 0, []
    for label, value in pairs:
        ok = False
        start = 0
        while True:
            i = low.find(label.lower(), start)
            if i < 0:
                break
            seg = flat[i + len(label): i + len(label) + WINDOW]
            if value in _NUM.findall(seg):
                ok = True
                break
            start = i + 1
        hits += ok
        if not ok:
            misses.append(f"{label}={value}")
    return hits, len(pairs), misses


def has_data(page_key: str) -> bool:
    spec = TRUTH[page_key]
    return "values" in spec or "rows" in spec


# ---------------- blind rubric (visual descriptions etc.) ----------------
RUBRIC = """You are grading an OCR/transcription system. Above is the ORIGINAL page image.
Below is ONE candidate transcription produced by an automated system that was asked to:
(a) transcribe every character verbatim in the original language (German) using Markdown,
(b) render math as <math>LaTeX</math>,
(c) replace every non-text element with a detailed `[Visual Description: ...]` block that
    states the element type, its content (for charts: title, axis labels, DATA VALUES,
    trends; for diagrams: nodes, labels, connections) and its semantic context.

Grade the candidate against the image on this rubric. Be strict and specific.

- text_fidelity (0-10): is every visible text string present and verbatim correct
  (German spelling, umlauts, numbers, page/footer text)?
- data_fidelity (0-10): are ALL numeric/graphical values read off correctly --
  bar/axis values, table cells, node labels, edge directions, formula operands?
  Return null if the page carries no such values.
- math_fidelity (0-10): are formulas reproduced correctly and in usable LaTeX?
  Return null if the page has no math.
- visual_desc (0-10): are all non-text elements described, and are the descriptions
  accurate and informative enough to replace seeing the image?
- structure (0-10): reading order, headings, lists, tables, layout preserved?
- hallucinations: list concrete statements in the candidate that are FALSE for this
  image. Empty list if none.
- omissions: list concrete visible content MISSING from the candidate.

Return ONLY a JSON object:
{"text_fidelity":n,"data_fidelity":n|null,"math_fidelity":n|null,"visual_desc":n,
 "structure":n,"hallucinations":["..."],"omissions":["..."],"one_line":"..."}

CANDIDATE TRANSCRIPTION:
---
%s
---"""
