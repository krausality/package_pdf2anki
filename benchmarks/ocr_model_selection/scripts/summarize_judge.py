"""Judge-slot tables from ../results/. No API calls."""
import json, statistics as st
from collections import defaultdict
from bench_common import RESULTS, TRUTH


def wilson(k, n, z=1.96):
    if not n:
        return 0.0, 0.0
    p, d = k / n, 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, c - h), min(1.0, c + h)


# ── stage 2: real production pairs ────────────────────────────────────────────
s2 = json.load(open(RESULTS / "judge_real_pairs.json", encoding="utf-8"))
cands = json.load(open(RESULTS / "judge_candidates.json", encoding="utf-8"))

agg = defaultdict(lambda: defaultdict(list))
for k, v in s2.items():
    if not v.get("ok"):
        continue
    j = k.split("||")[0]
    agg[j]["cost"].append(v["cost"] or 0)
    agg[j]["verbatim"].append(v["verbatim"])
    agg[j]["recall"].append(v["recall"])
    agg[j]["lat"].append(v["lat"])
    if v.get("total"):
        agg[j]["hits"].append(v["hits"]); agg[j]["tot"].append(v["total"])

print("=" * 96)
print("TABLE 2 -- judge slot on REAL production pairs (two repeats of the same OCR model)")
print("=" * 96)
print(f"{'judge':40}{'$/call':>9}{'$/1000p':>9}{'verbatim':>10}{'text_e2e':>10}{'data_e2e':>10}{'s':>6}")
for j, a in sorted(agg.items(), key=lambda kv: st.median(kv[1]["cost"])):
    de = sum(a["hits"]) / sum(a["tot"]) if a["tot"] else float("nan")
    print(f"{j:40}{st.median(a['cost']):9.5f}{st.median(a['cost'])*1000:9.2f}"
          f"{st.mean(a['verbatim']):10.3f}{st.mean(a['recall']):10.3f}{de:10.2f}"
          f"{st.median(a['lat']):6.1f}")

diff = sum(1 for p, c in cands.items()
           if c.get("a", "").strip() != c.get("b", "").strip())
print(f"\n  the two production repeats produced different text on {diff}/{len(cands)} pages,")
print("  which is why this table cannot separate judges -- hence table 3.")

# ── stage 3: discriminative ───────────────────────────────────────────────────
s3 = json.load(open(RESULTS / "judge_discriminative.json", encoding="utf-8"))
pairs = json.load(open(RESULTS / "judge_disc_pairs.json", encoding="utf-8"))

d = defaultdict(lambda: {"good": 0, "n": 0, "first": 0, "longer": 0, "verb": [], "cost": []})
for k, v in s3.items():
    if not v.get("ok"):
        continue
    j, page, orient, order, _ = k.split("||")
    a = d[j]
    a["n"] += 1
    a["good"] += v["picked"] == "good"
    a["first"] += v["picked"] == ("good" if order == "good_first" else "bad")
    a["longer"] += v["picked"] == v["longer"]
    a[f"good_{orient}"] = a.get(f"good_{orient}", 0) + (v["picked"] == "good")
    a[f"n_{orient}"] = a.get(f"n_{orient}", 0) + 1
    a["verb"].append(v["verbatim"]); a["cost"].append(v["cost"] or 0)

print()
print("=" * 96)
print("TABLE 3 -- judge slot, DISCRIMINATIVE test")
print("  Pairs where one candidate objectively read FEWER known chart values.")
print("  Both presentation orders x 3 repetitions, so pure position bias averages to 0.50")
print("  and any deviation is real discrimination -- in either direction.")
print("=" * 96)
for p in pairs:
    print(f"  {p['page']:12} {p['orient']:13} {p['good_model'].split('/')[-1]} "
          f"({p['good_hits']}/{p['total']}, {p['good_len']}c)  vs  "
          f"{p['bad_model'].split('/')[-1]} ({p['bad_hits']}/{p['total']}, {p['bad_len']}c)")
print()
print(f"{'judge':40}{'picks best':>12}{'rate':>7}{'95% CI':>15}"
      f"{'g<b':>7}{'g>b':>7}{'1st':>6}{'longer':>8}{'verbatim':>10}")
for j, a in sorted(d.items(), key=lambda kv: -kv[1]["good"] / max(kv[1]["n"], 1)):
    lo, hi = wilson(a["good"], a["n"])
    sh = a.get("good_good_shorter", 0) / max(a.get("n_good_shorter", 0), 1)
    lg = a.get("good_good_longer", 0) / max(a.get("n_good_longer", 0), 1)
    print(f"{j:40}{a['good']:>7}/{a['n']:<4}{a['good']/a['n']:7.2f}  [{lo:.2f}, {hi:.2f}]"
          f"{sh:7.2f}{lg:7.2f}{a['first']/a['n']:6.2f}{a['longer']/a['n']:8.2f}"
          f"{st.mean(a['verb']):10.3f}")
print("  g<b / g>b = rate when the GOOD candidate was shorter / longer than the bad one.")
print("  A judge that just prefers length shows a large gap between those two columns.")

print("\n  'picks longer' is the diagnostic: a judge optimising for verbosity rather than")
print("  fidelity scores below chance whenever the worse candidate is the wordier one.")

# ── cost model ────────────────────────────────────────────────────────────────
raw = json.load(open(RESULTS / "ocr_raw.json", encoding="utf-8"))
ocr = st.median(v["cost"] for k, v in raw.items()
                if k.startswith("google/gemini-3.1-flash-lite||") and v.get("ok"))
print()
print("=" * 96)
print("TABLE 4 -- cost per page, measured (OCR x2 + one judge call)")
print("=" * 96)
prev, cur = "google/gemini-3-flash-preview", "google/gemini-3.1-flash-lite"
base = 2 * ocr + st.median(agg[prev]["cost"])
print(f"  OCR google/gemini-3.1-flash-lite x2 (repeat=[2]): {2*ocr:.5f} $/page")
print(f"{'configuration':44}{'$/page':>10}{'delta':>10}")
for label, j in [("previous  judge=gemini-3-flash-preview", prev),
                 ("current   judge=gemini-3.1-flash-lite", cur),
                 ("max-quality judge=gemini-3.6-flash", "google/gemini-3.6-flash")]:
    t = 2 * ocr + st.median(agg[j]["cost"])
    print(f"{label:44}{t:10.5f}{(t/base-1)*100:+9.1f}%")

spend = sum(v.get("cost") or 0 for v in list(raw.values()) + list(s2.values()) + list(s3.values())
            if isinstance(v, dict))
print(f"\nbenchmark API spend across all stages: ${spend:.2f}")
