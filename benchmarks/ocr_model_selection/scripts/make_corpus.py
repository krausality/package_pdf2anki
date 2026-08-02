"""Generate the benchmark corpus: 10 synthetic German lecture slides + exact ground truth.

Why synthetic: the original study ran against real lecture slides, which are
third-party material and cannot be published. This corpus is generated from
code, so it is copyright-free and the whole benchmark becomes reproducible.

Why it is also *better*: because we draw the slides ourselves, we know every
bar value, table cell and graph edge exactly. Data fidelity -- the dimension
that separated the OCR models -- becomes objectively measurable instead of
depending on an LLM rubric.

Built on PyMuPDF only, which pdf2anki already requires. No extra dependencies.
Deterministic: same input, same bytes.

    python make_corpus.py            # writes ../corpus/slides.pdf + truth.json
"""
import json
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
CORPUS.mkdir(parents=True, exist_ok=True)

W, H = 842, 595            # A4 landscape @72dpi, the usual slide aspect
MARGIN = 48
DARK = (0.09, 0.20, 0.42)
ACCENT = (0.25, 0.45, 0.72)
GREY = (0.42, 0.42, 0.42)
LIGHT = (0.85, 0.87, 0.90)
BLACK = (0, 0, 0)

FOOT = "Synthetischer Beispielkurs - Folienkorpus fuer OCR-Messungen"
truth = {}


def _chrome(page, n, title, subtitle=None):
    """Header bar + footer, mirroring how real lecture decks are laid out."""
    page.draw_rect(fitz.Rect(MARGIN, 34, W - MARGIN, 88), color=None, fill=DARK)
    page.insert_text((MARGIN + 16, 62), title, fontname="hebo", fontsize=19,
                     color=(1, 1, 1))
    if subtitle:
        page.insert_text((MARGIN + 16, 80), subtitle, fontname="heit", fontsize=11,
                         color=(0.85, 0.88, 0.95))
    page.draw_line(fitz.Point(MARGIN, H - 40), fitz.Point(W - MARGIN, H - 40),
                   color=LIGHT, width=1)
    page.insert_text((MARGIN, H - 24), FOOT, fontname="helv", fontsize=8, color=GREY)
    page.insert_text((W - MARGIN - 52, H - 24), f"Seite {n}", fontname="helv",
                     fontsize=8, color=GREY)
    texts = [title, FOOT, f"Seite {n}"]
    if subtitle:
        texts.append(subtitle)
    return texts


def _bullets(page, items, x, y, size=12, leading=22):
    out = []
    for level, txt in items:
        page.insert_text((x + level * 22, y), "•" if level == 0 else "–",
                         fontname="helv", fontsize=size, color=ACCENT)
        page.insert_text((x + level * 22 + 14, y), txt, fontname="helv",
                         fontsize=size, color=BLACK)
        out.append(txt)
        y += leading
    return out, y


# ── 1 title ──────────────────────────────────────────────────────────────────
def slide_01(page):
    texts = _chrome(page, 1, "Softwarequalität: Messen und Bewerten",
                    "Kapitel 1 - Einfuehrung und Begriffsbildung")
    body, _ = _bullets(page, [
        (0, "Qualität ist die Gesamtheit der Merkmale einer Einheit"),
        (0, "bezüglich ihrer Eignung, festgelegte Erfordernisse zu erfüllen"),
        (0, "Interne Merkmale: Wartbarkeit, Änderbarkeit, Prüfbarkeit"),
        (0, "Externe Merkmale: Zuverlässigkeit, Effizienz, Benutzbarkeit"),
        (1, "Größe allein ist kein Qualitätsmaß"),
        (1, "Maße müssen validiert und reproduzierbar sein"),
    ], MARGIN + 20, 160)
    return {"kind": "text", "text": texts + body}


# ── 2 bar chart: the decisive slide ──────────────────────────────────────────
def slide_02(page):
    texts = _chrome(page, 2, "Qualitätsmerkmale priorisieren",
                    "Erhebung im Projekt Beispielsystem")
    # 12 categories, gridlines only every 2 units, no value labels on the bars and
    # several values landing BETWEEN gridlines. A model has to actually measure the
    # bar against the axis instead of snapping to the nearest labelled tick -- which
    # is where the cheap models failed on real slides.
    values = {
        "Zuverlässigkeit": 9, "Wartbarkeit": 6, "Effizienz": 4,
        "Benutzbarkeit": 8, "Portabilität": 3, "Testbarkeit": 7,
        "Sicherheit": 10, "Skalierbarkeit": 5, "Änderbarkeit": 11,
        "Interoperabilität": 2, "Nachvollziehbarkeit": 13, "Robustheit": 1,
    }
    x0, y0, plot_w, row_h = 268, 122, 430, 28
    axis_max, tick = 14, 2
    n = len(values)
    for gv in range(0, axis_max + 1, tick):
        gx = x0 + plot_w * gv / axis_max
        page.draw_line(fitz.Point(gx, y0 - 5), fitz.Point(gx, y0 + row_h * n),
                       color=LIGHT, width=0.6)
        page.insert_text((gx - 3, y0 + row_h * n + 14), str(gv),
                         fontname="helv", fontsize=8, color=GREY)
    for i, (label, v) in enumerate(values.items()):
        cy = y0 + i * row_h
        page.insert_text((MARGIN + 8, cy + 15), label, fontname="helv",
                         fontsize=9, color=BLACK)
        page.draw_rect(fitz.Rect(x0, cy + 5, x0 + plot_w * v / axis_max, cy + 20),
                       color=None, fill=ACCENT)
    page.insert_text((x0, y0 + row_h * n + 32),
                     "Priorisierung (0 = irrelevant, 14 = kritisch)",
                     fontname="heit", fontsize=9, color=GREY)
    lx, ly = W - MARGIN - 108, y0 + 6
    page.draw_rect(fitz.Rect(lx, ly, lx + 100, ly + 30), color=LIGHT, fill=(1, 1, 1))
    page.draw_rect(fitz.Rect(lx + 8, ly + 11, lx + 22, ly + 20), color=None, fill=ACCENT)
    page.insert_text((lx + 28, ly + 19), "Priorität", fontname="helv", fontsize=9, color=BLACK)
    return {"kind": "barchart", "text": texts + list(values) + ["Priorität"],
            "values": values, "axis": {"min": 0, "max": axis_max, "tick": tick},
            "vision_required": True}


# ── 3 table ──────────────────────────────────────────────────────────────────
def slide_03(page):
    texts = _chrome(page, 3, "Messwerte je Modul", "Erhebung nach Integrationstest")
    header = ["Modul", "LOC", "Zyklomatisch", "Defekte"]
    rows = [
        ["Parser", "1240", "18", "7"],
        ["Scheduler", "860", "24", "11"],
        ["Renderer", "2130", "31", "4"],
        ["Persistenz", "540", "9", "2"],
    ]
    x, y, colw, rowh = MARGIN + 40, 150, [220, 110, 150, 110], 34
    page.draw_rect(fitz.Rect(x, y, x + sum(colw), y + rowh), color=None, fill=DARK)
    cx = x
    for c, head in enumerate(header):
        page.insert_text((cx + 12, y + 22), head, fontname="hebo", fontsize=12,
                         color=(1, 1, 1))
        cx += colw[c]
    for r, row in enumerate(rows):
        ry = y + rowh * (r + 1)
        if r % 2 == 0:
            page.draw_rect(fitz.Rect(x, ry, x + sum(colw), ry + rowh),
                           color=None, fill=(0.95, 0.96, 0.98))
        cx = x
        for c, cell in enumerate(row):
            page.insert_text((cx + 12, ry + 22), cell, fontname="helv",
                             fontsize=12, color=BLACK)
            cx += colw[c]
    for c in range(len(colw) + 1):
        gx = x + sum(colw[:c])
        page.draw_line(fitz.Point(gx, y), fitz.Point(gx, y + rowh * (len(rows) + 1)),
                       color=LIGHT, width=0.8)
    return {"kind": "table", "text": texts + header + [c for r in rows for c in r],
            "header": header, "rows": rows}


# ── 4 formulas ───────────────────────────────────────────────────────────────
def slide_04(page):
    texts = _chrome(page, 4, "Zyklomatische Komplexität",
                    "Definition nach McCabe und Rechenbeispiel")
    lines = [
        "M = E - N + 2P",
        "E = Anzahl der Kanten des Kontrollflussgraphen",
        "N = Anzahl der Knoten",
        "P = Anzahl der Zusammenhangskomponenten",
    ]
    y = 150
    for i, ln in enumerate(lines):
        page.insert_text((MARGIN + 30, y), ln,
                         fontname="hebo" if i == 0 else "helv",
                         fontsize=17 if i == 0 else 12, color=DARK if i == 0 else BLACK)
        y += 30 if i == 0 else 22
    page.draw_rect(fitz.Rect(MARGIN + 20, y + 12, W - MARGIN - 20, y + 118),
                   color=LIGHT, fill=(0.97, 0.98, 1.0))
    ex = ["Beispiel: E = 14, N = 11, P = 1",
          "M = 14 - 11 + 2 * 1 = 5",
          "Schwellwert: M > 10 gilt als wartungskritisch"]
    yy = y + 40
    for ln in ex:
        page.insert_text((MARGIN + 40, yy), ln, fontname="helv", fontsize=13, color=BLACK)
        yy += 26
    return {"kind": "formula", "text": texts + lines + ex,
            "values": {"E": 14, "N": 11, "P": 1, "M": 5, "Schwellwert": 10}}


# ── 5 control-flow graph ─────────────────────────────────────────────────────
def slide_05(page):
    texts = _chrome(page, 5, "Kontrollflussgraph", "Grundlage der Pfadüberdeckung")
    pos = {"n1": (200, 150), "n2": (200, 235), "n3": (110, 330), "n4": (300, 330),
           "n5": (200, 420), "n6": (430, 235), "n7": (430, 420)}
    edges = [("n1", "n2"), ("n2", "n3"), ("n2", "n4"), ("n3", "n5"),
             ("n4", "n5"), ("n2", "n6"), ("n6", "n7"), ("n7", "n5")]
    for a, b in edges:
        page.draw_line(fitz.Point(*pos[a]), fitz.Point(*pos[b]), color=GREY, width=1.4)
    for name, (cx, cy) in pos.items():
        page.draw_circle(fitz.Point(cx, cy), 20, color=DARK, fill=(1, 1, 1), width=1.6)
        page.insert_text((cx - 9, cy + 4), name, fontname="hebo", fontsize=11, color=DARK)
    legend, _ = _bullets(page, [
        (0, "Knoten: 7"), (0, "Kanten: 8"), (0, "Komponenten: 1"),
        (0, "M = 8 - 7 + 2 = 3"),
    ], 560, 170)
    return {"kind": "graph", "text": texts + list(pos) + legend,
            "nodes": sorted(pos), "edges": [list(e) for e in edges],
            "values": {"Knoten": 7, "Kanten": 8, "Komponenten": 1, "M": 3}}


# ── 6 nested bullets ─────────────────────────────────────────────────────────
def slide_06(page):
    texts = _chrome(page, 6, "Prüfverfahren im Überblick", "Statisch und dynamisch")
    body, _ = _bullets(page, [
        (0, "Statische Verfahren"),
        (1, "Review: Inspektion, Walkthrough, Stellungnahme"),
        (1, "Statische Analyse: Datenflussanomalien, Metriken"),
        (0, "Dynamische Verfahren"),
        (1, "Strukturtest: Anweisungs-, Zweig-, Pfadüberdeckung"),
        (1, "Funktionstest: Äquivalenzklassen, Grenzwertanalyse"),
        (0, "Formale Verfahren"),
        (1, "Verifikation gegen eine Spezifikation"),
        (1, "Symbolische Ausführung und Modellprüfung"),
    ], MARGIN + 30, 150)
    return {"kind": "text", "text": texts + body}


# ── 7 line chart ─────────────────────────────────────────────────────────────
def slide_07(page):
    texts = _chrome(page, 7, "Defektdichte über die Sprints",
                    "Gefundene Defekte je 1000 LOC")
    # Values are NOT printed next to the points -- otherwise reading the chart
    # degrades to reading text and the metric stops measuring chart comprehension.
    # Gridlines every 5 units, several values landing between them.
    series = {1: 12, 2: 15, 3: 9, 4: 7, 5: 8, 6: 4, 7: 3, 8: 2}
    x0, y0, pw, ph, ymax = 140, 160, 560, 280, 20
    page.draw_line(fitz.Point(x0, y0), fitz.Point(x0, y0 + ph), color=GREY, width=1.2)
    page.draw_line(fitz.Point(x0, y0 + ph), fitz.Point(x0 + pw, y0 + ph),
                   color=GREY, width=1.2)
    for gv in range(0, ymax + 1, 5):
        gy = y0 + ph - ph * gv / ymax
        page.draw_line(fitz.Point(x0, gy), fitz.Point(x0 + pw, gy), color=LIGHT, width=0.6)
        page.insert_text((x0 - 26, gy + 4), str(gv), fontname="helv", fontsize=9, color=GREY)
    pts = []
    for i, (sprint, val) in enumerate(series.items()):
        px = x0 + pw * i / (len(series) - 1)
        py = y0 + ph - ph * val / ymax
        pts.append((px, py))
        page.insert_text((px - 5, y0 + ph + 18), str(sprint), fontname="helv",
                         fontsize=10, color=GREY)
    for a, b in zip(pts, pts[1:]):
        page.draw_line(fitz.Point(*a), fitz.Point(*b), color=ACCENT, width=2.2)
    for px, py in pts:
        page.draw_circle(fitz.Point(px, py), 4, color=ACCENT, fill=ACCENT)
    page.insert_text((x0 + pw / 2 - 30, y0 + ph + 40), "Sprint", fontname="helv",
                     fontsize=10, color=GREY)
    return {"kind": "linechart", "text": texts + ["Sprint"],
            "values": {str(k): v for k, v in series.items()},
            "axis": {"min": 0, "max": ymax}, "vision_required": True}


# ── 8 code ───────────────────────────────────────────────────────────────────
def slide_08(page):
    texts = _chrome(page, 8, "Beispiel: prüfbare Methode",
                    "Zyklomatische Komplexität M = 4")
    code = [
        "public int einstufen(int wert) {",
        "    if (wert < 0) {",
        "        throw new IllegalArgumentException(\"negativ\");",
        "    }",
        "    if (wert < 10) return 1;",
        "    if (wert < 100) return 2;",
        "    return 3;",
        "}",
    ]
    page.draw_rect(fitz.Rect(MARGIN + 20, 140, W - MARGIN - 20, 140 + 22 * len(code) + 20),
                   color=LIGHT, fill=(0.96, 0.96, 0.96))
    y = 166
    for ln in code:
        page.insert_text((MARGIN + 36, y), ln, fontname="cour", fontsize=11, color=BLACK)
        y += 22
    return {"kind": "code", "text": texts + code, "code": code}


# ── 9 two columns ────────────────────────────────────────────────────────────
def slide_09(page):
    texts = _chrome(page, 9, "Review versus Test", "Stärken und Grenzen")
    page.insert_text((MARGIN + 30, 140), "Review", fontname="hebo", fontsize=14, color=DARK)
    left, _ = _bullets(page, [
        (0, "findet Ursachen, nicht nur Symptome"),
        (0, "früh im Prozess einsetzbar"),
        (0, "überträgt Wissen im Team"),
        (0, "erfordert Personalzeit"),
    ], MARGIN + 30, 172, size=11, leading=24)
    page.draw_line(fitz.Point(W / 2, 130), fitz.Point(W / 2, H - 70), color=LIGHT, width=1)
    page.insert_text((W / 2 + 40, 140), "Test", fontname="hebo", fontsize=14, color=DARK)
    right, _ = _bullets(page, [
        (0, "zeigt beobachtbares Fehlverhalten"),
        (0, "automatisierbar und wiederholbar"),
        (0, "benötigt lauffähigen Code"),
        (0, "belegt keine Fehlerfreiheit"),
    ], W / 2 + 40, 172, size=11, leading=24)
    return {"kind": "text", "text": texts + ["Review", "Test"] + left + right}


# ── 10 dense prose ───────────────────────────────────────────────────────────
def slide_10(page):
    texts = _chrome(page, 10, "Gütekriterien für Maße", "Reliabilität und Validität")
    para = [
        "Ein Maß heißt reliabel, wenn wiederholte Messungen desselben Gegenstandes",
        "unter gleichen Bedingungen übereinstimmende Werte liefern. Reliabilität ist",
        "notwendig, aber nicht hinreichend: ein zuverlässig falsch messendes Verfahren",
        "bleibt unbrauchbar. Validität verlangt zusätzlich, dass das Maß tatsächlich",
        "die Eigenschaft erfasst, über die eine Aussage getroffen werden soll.",
        "",
        "Häufige Fehlschlüsse in der Praxis sind die Gleichsetzung von Codegröße mit",
        "Komplexität, die Übertragung projektspezifischer Schwellwerte auf fremde",
        "Kontexte sowie die Deutung einer Korrelation als Kausalität. Maße steuern",
        "Verhalten: sobald eine Kennzahl zum Ziel wird, verliert sie ihre Aussagekraft.",
    ]
    y = 152
    for ln in para:
        page.insert_text((MARGIN + 30, y), ln, fontname="helv", fontsize=12, color=BLACK)
        y += 24
    return {"kind": "text", "text": texts + [p for p in para if p]}


SLIDES = [slide_01, slide_02, slide_03, slide_04, slide_05,
          slide_06, slide_07, slide_08, slide_09, slide_10]


def verify(pdf_path):
    """Assert the ground truth matches what is actually ON the page.

    The built-in fonts use WinAnsi encoding, so characters outside it (typographic
    dashes, German quotation marks) are silently substituted at render time. If the
    ground truth still claimed the original character, every model would be marked
    wrong for text that was never drawn. Comparing the truth against the rendered
    PDF's own text layer catches exactly that class of bug.
    """
    doc = fitz.open(str(pdf_path))
    problems = []
    for i, _ in enumerate(SLIDES, 1):
        rendered = doc[i - 1].get_text("text")
        flat = " ".join(rendered.split())
        for s in truth[f"page_{i}"]["text"]:
            if " ".join(s.split()) not in flat:
                problems.append((f"page_{i}", s))
    doc.close()
    if problems:
        print(f"\n[FAIL] {len(problems)} ground-truth string(s) are not on the rendered page:")
        for pg, s in problems[:12]:
            print(f"  {pg}: {s!r}")
        raise SystemExit(1)
    print("[OK] every ground-truth string verified against the rendered PDF text layer")


def main():
    doc = fitz.open()
    for i, fn in enumerate(SLIDES, 1):
        page = doc.new_page(width=W, height=H)
        truth[f"page_{i}"] = fn(page)
    pdf = CORPUS / "slides.pdf"
    doc.save(str(pdf), deflate=True)
    doc.close()

    json.dump(truth, open(CORPUS / "truth.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"wrote {pdf} ({pdf.stat().st_size // 1024} KB, {len(SLIDES)} slides)")
    for k, v in truth.items():
        extra = ""
        if "values" in v:
            extra = f", {len(v['values'])} known values"
        if "rows" in v:
            extra = f", {len(v['rows'])}x{len(v['header'])} table"
        if "edges" in v:
            extra = f", {len(v['nodes'])} nodes / {len(v['edges'])} edges"
        print(f"  {k:9} {v['kind']:10} {len(v['text']):3} text items{extra}")
    verify(pdf)


if __name__ == "__main__":
    main()
