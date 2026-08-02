"""Regenerate every table in ../README.md from ../results/. No API calls."""
import json, statistics as st
from collections import defaultdict
from bench_common import (RESULTS, TRUTH, PAGES, recall, order_score,
                          truth_tokens, data_hits, has_data)

raw = json.load(open(RESULTS / "ocr_raw.json", encoding="utf-8"))
pages = sorted(TRUTH, key=lambda k: int(k.split("_")[1]))
GT = {k: truth_tokens(k) for k in pages}
DATA_PAGES = [p for p in pages if has_data(p)]


def page_of(key):
    return key.split("||")[1].replace(".png", "")


per = defaultdict(dict)
for key, r in raw.items():
    model, pg = key.split("||")[0], page_of(key)
    if not r.get("ok"):
        per[model][pg] = None
        continue
    dh = data_hits(pg, r["text"]) if has_data(pg) else None
    per[model][pg] = {
        "recall": recall(GT[pg], r["text"]),
        "order": order_score(GT[pg], r["text"]),
        "hits": dh[0] if dh else None, "total": dh[1] if dh else None,
        "misses": dh[2] if dh else [],
        "cost": r.get("cost"), "lat": r.get("latency"),
        "in": r.get("prompt_tokens"), "out": r.get("completion_tokens"),
        "reason": r.get("reasoning_tokens") or 0,
        # A response cut off by the token limit means the model ran away into a
        # repetition loop. pdf2anki does NOT detect this -- it never reads
        # finish_reason -- so such a blob is written to disk as a valid page.
        "deg": r.get("finish") == "length",
    }

# Values printed as text on the slide (table cells, formula operands, the graph's
# legend) can be transcribed without understanding the graphic. Only the bar and
# line chart force a model to MEASURE the drawing -- that is the column that
# separated the models on real slides, so it gets reported separately.
VISION_PAGES = [p for p in DATA_PAGES if TRUTH[p].get("vision_required")]

rows = []
for model, d in per.items():
    ok = [v for v in d.values() if v]
    if not ok:
        continue
    hits = sum(v["hits"] for v in ok if v["hits"] is not None)
    total = sum(v["total"] for v in ok if v["total"] is not None)
    vh = sum(d[p]["hits"] for p in VISION_PAGES if d.get(p))
    vt = sum(d[p]["total"] for p in VISION_PAGES if d.get(p))
    rows.append({
        "model": model,
        "recall": st.mean(v["recall"] for v in ok),
        "worst": min(v["recall"] for v in ok),
        "order": st.mean(v["order"] for v in ok),
        "data": hits / total if total else float("nan"),
        "hits": hits, "total": total,
        "vision": vh / vt if vt else float("nan"), "vh": vh, "vt": vt,
        # Median, not mean: a single degenerate response (see `deg`) can be 150x
        # the normal cost and would otherwise misrepresent the typical page.
        "cost": st.median(v["cost"] or 0 for v in ok),
        "cost_mean": st.mean(v["cost"] or 0 for v in ok),
        "lat": st.median(v["lat"] for v in ok if v["lat"]),
        "deg": sum(1 for v in ok if v["deg"]),
        "fail": len(d) - len(ok),
    })
rows.sort(key=lambda r: (-r["vision"], -r["recall"]))

print("=" * 104)
print("TABLE 1 -- OCR candidates on the public corpus. Both quality columns are OBJECTIVE:")
print("  text   = multiset recall of the known slide text")
print("  DATA   = share of known chart/table values read correctly (label must be near its value)")
print("=" * 104)
print(f"{'model':42}{'text':>7}{'worst':>7}{'CHART':>7}{'hits':>8}{'alldata':>9}"
      f"{'$/1000p':>9}{'(mean)':>9}{'s':>6}{'deg':>5}{'fail':>5}")
for r in rows:
    vh = f"{r['vh']}/{r['vt']}"
    print(f"{r['model']:42}{r['recall']:7.3f}{r['worst']:7.3f}"
          f"{r['vision']:7.2f}{vh:>8}{r['data']:9.2f}{r['cost']*1000:9.2f}"
          f"{r['cost_mean']*1000:9.2f}{r['lat']:6.1f}{r['deg']:5}{r['fail']:5}")
print("  CHART   = bar/line chart values, only obtainable by measuring the drawing")
print("  alldata = all known values incl. those printed as text (table, formula, legend)")
print("  $/1000p = MEDIAN page; (mean) shows how far one degenerate response drags it")
print("  deg     = responses cut off by the token limit, i.e. repetition loops")

print(f"\nper-page data accuracy ({len(DATA_PAGES)} pages carry known values):")
hdr = "".join(f"{TRUTH[p]['kind'][:9]:>11}" for p in DATA_PAGES)
print(f"{'model':42}{hdr}")
for r in rows:
    cells = ""
    for p in DATA_PAGES:
        v = per[r["model"]].get(p)
        cell = "FAIL" if not v else f"{v['hits']}/{v['total']}"
        cells += f"{cell:>11}"
    print(f"{r['model']:42}{cells}")

print("\nwhat the production model missed (if anything):")
prod = "google/gemini-3.1-flash-lite"
for p in DATA_PAGES:
    v = per[prod].get(p)
    if v and v["misses"]:
        print(f"  {p:9} {TRUTH[p]['kind']:10} {', '.join(v['misses'])}")
    elif v:
        print(f"  {p:9} {TRUTH[p]['kind']:10} alle {v['total']} Werte korrekt")

tot = sum(r.get("cost") or 0 for r in raw.values() if isinstance(r, dict))
print(f"\nstage-1 API spend: ${tot:.2f} over {len(raw)} calls")
