"""Stage 1: run every OCR candidate over every corpus page (production prompt/encoder)."""
import concurrent.futures as cf, json, sys
from bench_common import PAGES, RESULTS, ocr_call

MODELS = [
    "google/gemini-3.1-flash-lite",      # production model
    "google/gemini-2.5-flash-lite",
    "google/gemini-3.5-flash-lite",
    "google/gemini-3-flash-preview",
    "google/gemini-3.6-flash",
    "qwen/qwen3.7-flash",
    "qwen/qwen3.5-flash-02-23",
    "qwen/qwen3-vl-30b-a3b-instruct",
    "mistralai/mistral-small-3.2-24b-instruct",
    "openai/gpt-5-nano",
    "bytedance-seed/seed-2.0-mini",
    "xiaomi/mimo-v2.5",
]
if len(sys.argv) > 1:
    MODELS = sys.argv[1:]

pages = sorted(PAGES.glob("*.png"), key=lambda p: int(p.stem.split("_")[1]))
outfile = RESULTS / "ocr_raw.json"
out = json.load(open(outfile, encoding="utf-8")) if outfile.exists() else {}

jobs = [(m, p) for m in MODELS for p in pages
        if f"{m}||{p.name}" not in out or not out[f"{m}||{p.name}"].get("ok")]
print(f"{len(pages)} pages x {len(MODELS)} models -> {len(jobs)} calls to make")


def work(job):
    m, p = job
    return f"{m}||{p.name}", ocr_call(m, p)


done = 0
with cf.ThreadPoolExecutor(max_workers=6) as ex:
    for key, r in ex.map(work, jobs):
        out[key] = r
        done += 1
        print(f"[{done}/{len(jobs)}] {'ok ' if r.get('ok') else 'ERR'} {key}  "
              f"cost={r.get('cost')} in={r.get('prompt_tokens')} out={r.get('completion_tokens')} "
              f"{r.get('latency') and round(r['latency'], 1)}s {r.get('error') or ''}", flush=True)
        json.dump(out, open(outfile, "w", encoding="utf-8"), ensure_ascii=False)

json.dump(out, open(outfile, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", outfile)
