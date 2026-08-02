# OCR-Modellauswahl für `pdf2anki pdf2text` — reproduzierbarer Benchmark

**Korpus:** 10 selbst erzeugte deutsche Vorlesungsfolien, copyrightfrei, mit exakter Ground
Truth (siehe [CORPUS.md](CORPUS.md)) · **Stand:** 2026-08-02 · **API-Kosten des Laufs:** $1.09

Dies ist der reproduzierbare Nachbau einer Erststudie, die gegen echte Vorlesungsfolien
gemessen hatte. Weder jener Korpus noch dessen OCR-Ergebnisse durften veröffentlicht werden —
es war fremdes Material, und eine Transkription ist derselbe Inhalt in anderer Form. Die
Erststudie ist deshalb nicht Teil dieses Repos; ihre Befunde sind unten im Abschnitt
[Was repliziert](#was-gegenüber-der-erststudie-repliziert--und-was-nicht) zusammengefasst.

Hier sind Korpus, Rohdaten und Skripte vollständig im Repo — jede Zahl unten ist nachrechenbar.

```
cd scripts
python summarize.py          # Tabelle 1
python summarize_judge.py    # Tabellen 2-4
```

---

## Der methodische Kernpunkt

**Textausbeute misst bei Folienmaterial nichts.** Alle zwölf Kandidaten liegen zwischen
0.89 und 0.998 — und trotzdem unterscheidet sich die Brauchbarkeit drastisch, weil die
eigentliche Information in Diagrammen steckt, die in keiner Textebene auftaucht.

Der schärfste Beleg steht in Tabelle 1: `gemini-2.5-flash-lite` erreicht **0.996 Textausbeute
— höher als das Produktionsmodell (0.993)** — und liest dabei **0 von 12 Balkenwerten**
korrekt. Wer nach Textmetrik auswählt, wählt dieses Modell aus und merkt den Schaden nie.

Weil der Korpus generiert ist, sind die wahren Werte bekannt. `CHART` ist deshalb kein
LLM-Urteil, sondern eine Trefferzählung.

## Tabelle 1 — OCR-Kandidaten

| Modell | Text | schlecht. | **CHART** | Treffer | $/1000 S. | s | deg |
|---|---|---|---|---|---|---|---|
| `gemini-3.5-flash-lite` | 0.998 | 0.985 | **1.00** | 20/20 | 1.11 | 2.8 | 0 |
| `qwen/qwen3.5-flash-02-23` | 0.998 | 0.985 | **1.00** | 20/20 | 0.56 | 36.0 | 0 |
| `qwen/qwen3.7-flash` | 0.995 | 0.971 | **1.00** | 20/20 | 0.44 | 59.3 | 0 |
| **`gemini-3.1-flash-lite`** *(Produktion)* | 0.993 | 0.941 | **1.00** | 20/20 | **0.73** | **3.5** | 1 |
| `gemini-3-flash-preview` | 0.989 | 0.952 | **1.00** | 20/20 | 1.69 | 3.6 | 0 |
| `gemini-3.6-flash` | 0.980 | 0.952 | **1.00** | 20/20 | 11.37 | 6.8 | 0 |
| `bytedance-seed/seed-2.0-mini` | 0.890 | 0.353 | 1.00 | 20/20 | 1.34 | 23.8 | 2 |
| `xiaomi/mimo-v2.5` | 0.980 | 0.889 | 0.75 | 15/20 | 1.67 | 23.2 | 0 |
| `qwen/qwen3-vl-30b-a3b-instruct` | 0.955 | 0.778 | 0.65 | 13/20 | 0.66 | 5.0 | 0 |
| `openai/gpt-5-nano` | 0.963 | 0.837 | 0.35 | 7/20 | 1.88 | 31.6 | 0 |
| `gemini-2.5-flash-lite` | **0.996** | 0.971 | **0.15** | 3/20 | 0.49 | 2.9 | 0 |
| `mistral-small-3.2-24b` | 0.975 | 0.926 | 0.05 | 1/20 | 0.26 | 6.3 | 0 |

`CHART` = Balken-/Liniendiagrammwerte, nur durch Vermessen der Grafik zu bekommen.
`$/1000 S.` ist der **Median**; `deg` zählt Antworten, die ins Token-Limit liefen
(siehe unten) — deren Kosten würden den Mittelwert verzerren.

Sechs Modelle erreichen volle Diagrammtreue. Unter denen ist `gemini-3.1-flash-lite` das
schnellste bei nahezu niedrigsten Kosten; die beiden billigeren Qwen-Modelle sind 10- bis
17-mal langsamer. **Die Produktionswahl ist bestätigt.**

## Tabellen 2–3 — der Judge-Slot

Bei zwei Wiederholungen desselben OCR-Modells sind die Kandidaten fast gleich, deshalb kann
Tabelle 2 Judges nicht trennen (alle: Text 0.993–0.998, Daten 1.00). Tabelle 3 legt jedem
Judge Paare vor, bei denen ein Kandidat **objektiv weniger** bekannte Diagrammwerte gelesen
hat — „besser" ist hier gezählt, nicht geschätzt.

Entscheidend am Design: die Paare sind **längenbalanciert**. Je Seite gibt es eine Variante,
in der der gute Kandidat kürzer ist, und eine, in der er länger ist. Ohne diese Balance sind
„wählt den besseren" und „wählt den längeren" dieselbe Zahl und der Test kann Treue nicht von
Geschwätzigkeit unterscheiden — genau dieser Fehler steckte im ersten Anlauf.

| Judge | trifft besser | 95 % KI | gut&kürzer | gut&länger | wählt länger | verbatim | $/1000 S. |
|---|---|---|---|---|---|---|---|
| **`gemini-3.1-flash-lite`** *(aktuell)* | **24/24 = 1.00** | [0.86, 1.00] | 1.00 | 1.00 | 0.50 | **1.000** | **0.79** |
| `gemini-3.5-flash-lite` | 24/24 = 1.00 | [0.86, 1.00] | 1.00 | 1.00 | 0.50 | 0.998 | 1.11 |
| `gemini-3-flash-preview` *(vorher)* | 23/24 = 0.96 | [0.80, 0.99] | 0.92 | 1.00 | 0.54 | 0.992 | 1.65 |
| `gemini-3.6-flash` | 18/24 = 0.75 | [0.55, 0.88] | **0.50** | 1.00 | 0.75 | 0.984 | 8.18 |
| `gemini-2.5-flash-lite` | 12/24 = 0.50 | [0.31, 0.69] | 0.50 | 0.50 | 0.50 | **0.891** | 0.46 |

Zwei Dinge fallen auf. `gemini-3.6-flash` — das teuerste Modell im Test — zeigt eine klare
Längenpräferenz: 1.00 wenn der gute Kandidat der längere ist, 0.50 wenn nicht. Und
`gemini-2.5-flash-lite` erreicht nur 0.891 Verbatim-Treue: es schreibt den gewählten Text um,
statt ihn durchzureichen. Als Judge ist es damit unbrauchbar, unabhängig vom Preis.

## Tabelle 4 — Kosten je Seite

Produktionskonfiguration: `repeat: [2]`, `judge_mode: authoritative`, `judge_with_image: true`
→ zwei OCR-Calls plus ein Judge-Call, der den Gewinnertext neu ausgibt.

| Konfiguration | $/Seite | Δ |
|---|---|---|
| vorher: Judge = `gemini-3-flash-preview` | 0.00312 | — |
| **aktuell: Judge = `gemini-3.1-flash-lite`** | **0.00225** | **−27.7 %** |
| Maximalqualität: Judge = `gemini-3.6-flash` | 0.00965 | +209 % |

Der Judge-Slot verbraucht damit weiterhin rund ein Drittel des Budgets, obwohl er auf den
meisten Seiten zwischen zwei nahezu identischen Kandidaten entscheidet.

---

## Nebenbefund: das Produktionsmodell kann entgleisen

Auf `page_5` (Kontrollflussgraph) lief `gemini-3.1-flash-lite` in eine Wiederholungsschleife:
**65 532 Output-Tokens, `finish_reason=length`, 1,97 MB Text, $0.0987 für eine Seite** — das
150-Fache der normalen Seitenkosten — bei 177 s statt 3,5 s. In sechs Wiederholungen derselben
Seite trat es nicht erneut auf; es ist also selten und stochastisch, nicht seitenspezifisch.
Insgesamt: 3 von 120 Calls im Lauf, verteilt auf zwei Modelle.

Kritisch ist nicht die Häufigkeit, sondern die Behandlung. `pdf2anki/pic2text.py` liest
`finish_reason` **an keiner Stelle**, und `_is_successful_ocr_text()` prüft nur auf die
Präfixe `[ERROR:` und `[INFO:`. Ein Wiederholungsblob gilt deshalb als **erfolgreiches**
OCR-Ergebnis: er wird in die `.txt` geschrieben, im State als fertig markiert und an den
Judge weitergereicht.

Der Weiterreichung lässt sich die Schadensausbreitung ansehen. Für `page_5` bekam jeder
Judge den 1,97-MB-Blob als Kandidat 1 vorgelegt:

| Judge | $ für page_5 | $ für page_4 (normal) | Faktor |
|---|---|---|---|
| `gemini-3.1-flash-lite` | 0.01659 | 0.00081 | **20×** |
| `gemini-3-flash-preview` | 0.03326 | 0.00169 | 20× |
| `gemini-3.6-flash` | 0.10321 | 0.00797 | 13× |

Eine einzelne entgleiste Seite kostet damit rund **$0.115 statt $0.00225 — das 51-Fache**,
verteilt auf OCR- und Judge-Slot. Immerhin: **alle fünf Judges wählten den gesunden
Kandidaten**, der Judge fängt den Qualitätsschaden also ab — den Kostenschaden nicht.

Ein Guard auf `finish_reason == "length"` oder auf ein plausibles Verhältnis von
Output-Tokens zu Seiteninhalt wäre billig und würde beides verhindern.

---

## Was gegenüber der Erststudie repliziert — und was nicht

Beides gehört in den Bericht, sonst ist der Nachbau wertlos.

**Repliziert:**
* Kostenmodell: −27.7 % durch den Judge-Wechsel (Erststudie: −28.4 %).
* Textausbeute diskriminiert nicht — hier sogar deutlich schärfer belegbar, weil
  `gemini-2.5-flash-lite` die *höchste* Textausbeute mit der *schlechtesten* Diagrammtreue
  verbindet.
* `gemini-2.5-flash-lite` erfindet Diagrammwerte statt sie zu lesen.
* `gemini-2.5-flash-lite` ist als Judge nicht verbatim-treu.
* Das Produktionsmodell `gemini-3.1-flash-lite` liegt auf der Preis/Leistungs-Front.

**Repliziert NICHT:**
* Die Erststudie fand den vorherigen Judge `gemini-3-flash-preview` mit 17/60 = 0.28
  *signifikant unter dem Zufall*, verursacht durch eine Präferenz für den längeren
  Kandidaten (0.85). Hier erreicht derselbe Judge **0.96** und zeigt keine Längenpräferenz.
  Die Längenpräferenz taucht stattdessen bei `gemini-3.6-flash` auf (0.50 vs 1.00).
* Erklärung: In der Erststudie war der schlechtere Kandidat in 8 von 10 Paaren der längere,
  weil dort schwächere Modelle mit ausufernden Bildbeschreibungen antworteten. Auf diesem
  Korpus ist der Zusammenhang anders. Der dramatische Befund war also
  **korpusspezifisch und nicht verallgemeinerbar** — die daraus abgeleitete Entscheidung
  bleibt trotzdem richtig, aber aus einem anderen Grund: der aktuelle Judge ist hier
  schlicht der beste **und** der günstigste unter den brauchbaren.

## Grenzen

* 10 Seiten, davon **nur 2** mit Werten, die echtes Diagrammlesen erfordern. Die
  `CHART`-Spalte beruht auf 20 Werten je Modell; Tabelle 3 auf n=24 je Judge. Für die
  Spitzengruppe (sechs Modelle bei 1.00) reicht die Auflösung nicht — der Korpus trennt die
  schwachen Modelle sauber, nicht die starken untereinander.
* Synthetische Folien sind sauberer als reale: keine Kompressionsartefakte, keine
  überlappenden Elemente, keine Screenshots. Der erste Entwurf dieses Korpus war so leicht,
  dass *alle* Modelle 100 % erreichten; die aktuelle Fassung ist bewusst nachgeschärft
  (siehe CORPUS.md), erreicht aber nicht die Unordnung echter Vorlesungsfolien.
* `data_hits` prüft, ob die korrekte Zahl innerhalb von 90 Zeichen nach dem Label steht.
  Das ist eine Heuristik: ungewöhnliche Ausgabeformate können als Fehltreffer zählen.
* Gemessen an einem Tag mit den jeweils aktuellen Modellversionen. Preise und Modelle
  ändern sich; `openrouter_models_*.json` hält den Katalog des Messzeitpunkts fest.

## Verzeichnis

```
ocr_model_selection/
├── README.md                dieser Bericht
├── CORPUS.md                Herkunft, Lizenz und Schwierigkeitskalibrierung des Korpus
├── corpus/
│   ├── slides.pdf           10 generierte Folien
│   └── truth.json           exakte Ground Truth je Seite
├── pages/                   gerenderte Seiten (300 dpi, via pdf2pic)
├── results/                 alle Rohergebnisse
└── scripts/
    ├── make_corpus.py       erzeugt Korpus + Ground Truth, prüft sich selbst
    ├── bench_common.py      Produktions-Prompt/-Encoder, Metriken
    ├── run_ocr_bench.py     Stufe 1
    ├── run_judge_bench.py   Stufen 2+3
    ├── summarize.py         Tabelle 1
    └── summarize_judge.py   Tabellen 2-4
```

Alle Messstufen sind idempotent: vorhandene Ergebnisse werden übersprungen, nur Fehlendes
wird nachgerufen. Ein vollständiger Neulauf braucht `OPENROUTER_API_KEY` (Umgebung oder
`../../.env`) und kostet ≈ $1.
