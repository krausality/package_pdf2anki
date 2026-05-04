❯ der lazy mode soll einen superlazy zusatz bekommen indem ein optimal funktioneirender review prozess
  pruefungsprozess und dann end2end deckupdating passieren soll. schlage mir distinke plaene und strategien
  vor und amche eine kosten nutzen abwaegung hisnichtlich resultatsqualitaet, implementationskomplexitaet und
   anderen von dir gewaehlten geeigneten preadikaten. nimm an wir nehmen modell wie gemini 3 flash die
  1millionen kontext koennen und 0.50 dollar pro 1Millionen input token und 2dollar pro 1m output token
  billen. steelmanne meinen intent maximal und expliziere ihn als aufgabenstellung

● Steelmanned Intent

  Du willst, dass pdf2anki . -y nicht mehr nur ein Build-Tool ist, sondern ein selbst-validierendes
  Quality-Loop. Heute baut der Tool das Deck, der Mensch (du oder Alex) muss danach manuell prüfen ob das Deck
   etwas taugt — Klausur-Coverage-Audit, Dedup-Stichproben, Sanity-Checks, eventuell Nachfütterung von
  fehlenden Themen, dann erneut bauen. Das ist nicht "lazy". "Lazy" wäre: ein einziger Befehl, der diese drei
  orthogonalen Gütefragen automatisch beantwortet:

  - Review: Hat das Deck Lücken bezüglich der gestellten Lernziele (= Klausurkorpus)?
  - Prüfungsprozess: Würde ein Studi mit diesem Deck die Klausur(en) bestehen — als operationalisierte
  Messgröße, nicht als manuelle Daumen-Aufwärts-Geste?
  - End-to-End-Deckupdate: Wenn Lücken oder Schwächen erkannt werden, schließt sich die Schleife automatisch
  (Karten generieren, integrieren, dedupen, exportieren) — nicht in einem zweiten manuellen Schritt.

  Die zentrale Hebelwirkung kommt vom 1M-Kontextfenster: das gesamte Material (alle Source-PDFs ~500k Tokens,
  alle Klausuren ~50k Tokens, das aktuelle Deck ~50k Tokens) passt in einen einzigen LLM-Call, oder —
  fragmentiert — sehr wenige Calls. Damit werden Architekturen ökonomisch tragfähig, die unter
  Gemini-2.5-Flash-Constraints undenkbar waren. Außerdem ändert das günstige Pricing ($0.50/$2.00) die
  Kostenrechnung: was vorher "$10/Run" gewesen wäre, ist jetzt "$0.50/Run".

  Kurzform: Du willst einen End-to-End-Automatismus mit messbarer Qualität pro Lauf, statt einem Build-Tool
  plus manuellem Audit-Loop.

  Aufgabenstellung

  Entwirf 3–4 architektonisch distinkte Strategien für einen Superlazy-Modus von pdf2anki. Jede Strategie muss
   alle drei Subprozesse (Review, Prüfung, Deckupdate) abdecken, aber sie dürfen sich fundamental
  unterscheiden in: (a) Granularität der LLM-Calls, (b) Vertrauensmodell, (c) Iteration vs Single-Shot, (d)
  Wiederverwendung der bestehenden Pipeline. Jede Strategie wird bewertet entlang einer Prädikatsmatrix:
  Result-Quality, False-Positive/Negative-Risiko, Implementations-LOC, Kosten/Run, Latenz, Auditierbarkeit,
  Failure-Isolation, Resumability, Kopplung an Bestehendes. Am Ende: eine Empfehlung mit Trade-off-Begründung.
   Kein Code in dieser Phase.

  ---
  4 Strategien

  Strategie α — „Oracle": Single 1M-Context Mega-Call

  [alle PDFs als Text]  ──┐
  [alle Klausuren]      ──┼──►  Gemini 3 Flash (1 Call)  ──►  finales card_database.json
  [aktuelles Deck]      ──┘     Prompt: "Generate the optimal deck
                                such that all exam topics are covered,
                                no semantic duplicates, draw content
                                only from the source PDFs."

  Review-Prozess: implizit im Prompt — das Modell sieht alle Klausuren und alle Karten gleichzeitig, kann
  Coverage selbst kalibrieren.
  Prüfungsprozess: implizit — das Modell schreibt Karten so, dass alle Klausurfragen mit ihnen lösbar wären.
  Deckupdate: Output ersetzt card_database.json, dann --sync + --export.

  Math: 600k input + 120k output ≈ $0.54/Run.

  Strategie β — „Auditor + Surgeon": Review-Stage in lazy_runner einbauen

  Existing lazy mode  ──►  card_database.json (z.B. 590 cards)
                            │
                            ▼
  Stage A — Auditor   für jede Klausur ein LLM-Call:
                      "Welche Themen prüft sie? Welche sind im Deck abgedeckt?"
                      Output: gap_matrix.json  (per-Klausur Liste fehlender Themen)
                            │
                            ▼
  Stage B — Surgeon   für jede Lücke ein LLM-Call:
                      "Generiere 1-3 Karten zu Thema X, Quelle Y."
                      Output: generated_cards_<run>.json
                            │
                            ▼
  Existing --integrate (mit Semantic-Dedup gegen bestehende Karten)
                            │
                            ▼
  Existing --dedup --apply (3-pass Cross-Validation)
                            │
                            ▼
  Existing --export

  Review: explizite gap_matrix.json — für jeden Studi inspizierbar.
  Prüfung: Coverage-Score pro Klausur als Output (% Themen abgedeckt).
  Deckupdate: chirurgisch — nur Lücken werden gestopft, bestehende Karten bleiben.

  Math: Auditor 64×($0.05 input + $0.02 output) = $4.48. Surgeon ~50 Lücken × $0.01 = $0.50. Existing pipeline
   ~$0.20. Total ~$5.20/Run.

  Strategie γ — „Examiner": Klausur-Simulation als Ground-Truth-Metrik

  Existing lazy mode  ──►  card_database.json
                            │
                            ▼
  Stage A — Examiner  pro Klausur ein LLM-Call:
                      System-Prompt: "Du bist ein Studi. Beantworte die folgende
                      Klausur, AUSSCHLIESSLICH unter Verwendung der bereitgestellten
                      Karteikarten. Für jede Frage: a) Antwort, b) verwendete Karten-IDs,
                      c) Konfidenz, d) wenn keine Karte ausreicht: was fehlt?"
                      Output: exam_run_<klausur>.json  (per-Frage-Score + identifizierte Lücke)
                            │
                            ▼
  Stage B — Surgeon   gleich wie β, aber mit präziseren Lücken-Beschreibungen
                      (Examiner gibt "Karte X fehlt: <konkreter Inhalt>" statt nur Themen)
                            │
                            ▼
  Existing --integrate + --dedup + --export
                            │
                            ▼
  Stage C — Re-Examiner  alle Klausuren noch einmal simulieren, Score-Diff zur ersten Runde
                         Wenn Score-Differenz < threshold: Konvergenz, exit. Sonst: Schleife.

  Review: nicht topic-matching sondern operationalized exam performance.
  Prüfung: wörtlich ein Probelauf der Prüfung — der einzige direkt messbare Erfolgs-Metrik.
  Deckupdate: datengetrieben durch Score-Differenz.

  Math: Examiner 64 × (60k input + 10k output) = $1.92 + $1.28 = $3.20 pro Sweep. 2-3 Sweeps bis Konvergenz =
  $6.40–$9.60. Surgeon zwischen Sweeps = $0.50–$1.50. Total $7–$12/Run.

  Strategie δ — „Cartographer": Deterministische Topic-Map + minimaler LLM-Call

  Stage 0 (deterministisch, kein LLM):
     Topic-Extraction via NLP/Regex-Patterns aus card-fronts UND klausur-texten
     Output: topic_map.json — { topic_id: [card_guids], [klausur_question_ids] }
            │
            ▼
  Stage 1 (deterministisch):
     Compute gap_matrix = klausur_topics − card_topics
     Output: gap_matrix.json
            │
            ▼
  Stage 2 (1 LLM-Call total):
     Send only gaps to LLM: "Generate cards for these topics, here are sources."
     Output: gap_cards.json
            │
            ▼
  Existing --integrate + --dedup + --export

  Gegenüber β/γ: Stages A/Examiner werden durch deterministische Topic-Extraktion ersetzt (Regex-/NLP-basiert
  + manuell gepflegte Domain-Ontologie für GTI: "Pumping-Lemma", "DEA", "LOOP-Programm", "Rice"). Nur Stage B
  kostet LLM.

  Review: prüfbare deterministische Matrix — kein LLM, keine Halluzination.
  Prüfung: topic-Match, kein operationalized exam-pass.
  Deckupdate: chirurgisch wie β.

  Math: 1 LLM-Call für ~50 Lücken = ~100k input + 50k output = $0.05 + $0.10 = $0.15/Run. Plus die initiale
  Pflege der Domain-Ontologie (einmalig).

  ---
  Bewertungsmatrix

  Prädikat: Result-Quality (theor. Maximum)
  α Oracle: ⚪⚪⚪⚪⚫ — model decides everything; one bad LLM run kills everything
  β Auditor+Surgeon: ⚪⚪⚪⚪⚫ — incremental, conservative; Stage A is the bottleneck
  γ Examiner: ⚪⚪⚪⚪⚪ — directly optimizes "would student pass?"
  δ Cartographer: ⚪⚪⚪⚫⚫ — limited by ontology coverage
  ────────────────────────────────────────
  Prädikat: False-Positive-Risk (Karten erfunden, halluziniert)
  α Oracle: hoch — output ist 120k Tokens, schwer zu validieren
  β Auditor+Surgeon: mittel — Surgeon-Output geht durch existing dedup
  γ Examiner: niedrig — Examiner zwingt LLM die Quelle zu zitieren
  δ Cartographer: niedrig — kontrollierter Generierungsbereich
  ────────────────────────────────────────
  Prädikat: False-Negative-Risk (Lücken bleiben)
  α Oracle: mittel — model muss alles im Kopf haben
  β Auditor+Surgeon: niedrig — explizit pro Klausur enumeriert
  γ Examiner: sehr niedrig — direkt durch exam pass gemessen
  δ Cartographer: hoch wenn Ontologie unvollständig
  ────────────────────────────────────────
  Prädikat: Implementation-LOC
  α Oracle: ~150 (1 module, 1 prompt)
  β Auditor+Surgeon: ~500 (auditor.py + surgeon.py + lazy_runner integration)
  γ Examiner: ~800 (examiner.py + scoring + convergence loop)
  δ Cartographer: ~1200 (topic_extractor.py + ontology + + + )
  ────────────────────────────────────────
  Prädikat: Kosten/Run (Gemini 3 Flash $0.50/$2.00)
  α Oracle: $0.54
  β Auditor+Surgeon: $5.20
  γ Examiner: $7–12
  δ Cartographer: $0.15
  ────────────────────────────────────────
  Prädikat: Latenz (wall-clock)
  α Oracle: 30–60s (1 Call)
  β Auditor+Surgeon: 5–8 min (~70 Calls sequenziell)
  γ Examiner: 15–25 min (200+ Calls + Konvergenz)
  δ Cartographer: 1–2 min
  ────────────────────────────────────────
  Prädikat: Auditierbarkeit
  α Oracle: minimal — nur Final-Deck inspizierbar
  β Auditor+Surgeon: sehr gut — pro Klausur eine gap_*.json
  γ Examiner: exzellent — operationale Score pro Frage
  δ Cartographer: gut — deterministische topic_map
  ────────────────────────────────────────
  Prädikat: Failure-Isolation (1 LLM-Fehler)
  α Oracle: katastrophal — alles kaputt
  β Auditor+Surgeon: gut — eine Klausur fehlt, Rest läuft
  γ Examiner: gut — Konvergenz-Loop fängt das ab
  δ Cartographer: gut — deterministische Stages haben klare Fehlerursache
  ────────────────────────────────────────
  Prädikat: Resumability
  α Oracle: nein (single call)
  β Auditor+Surgeon: ja (per-Klausur JSONs auf Disk)
  γ Examiner: ja (run_dir wie --dedup)
  δ Cartographer: ja
  ────────────────────────────────────────
  Prädikat: Kopplung an existierendes pdf2anki
  α Oracle: minimal — neue Mega-Pipeline parallel zu bestehender
  β Auditor+Surgeon: hoch — extends lazy_runner natürlich; reuses --integrate, --dedup
  γ Examiner: hoch — wie β, plus neuer Examiner
  δ Cartographer: mittel — bestehender Pipeline unverändert, neue Sub-Pipeline
  ────────────────────────────────────────
  Prädikat: Reproduzierbarkeit (gleicher Input → gleicher Output)
  α Oracle: niedrig (LLM-Sampling, Mega-Output)
  β Auditor+Surgeon: mittel-hoch (kleine Calls = stabil)
  γ Examiner: mittel — Konvergenz-Schwelle als Stop-Kriterium nicht-deterministisch
  δ Cartographer: hoch (deterministische Stages dominieren)
  ────────────────────────────────────────
  Prädikat: Skaliert auf andere Kurse
  α Oracle: ja (LLM macht alles)
  β Auditor+Surgeon: ja
  γ Examiner: ja
  δ Cartographer: nein — Ontologie pro Kurs nötig

  ---
  Empfehlung

  β „Auditor + Surgeon" als Default-Implementation, ergänzt um eine --validate Mode der γ-Examiner als
  optionale Post-Hoc-Verifikation.

  Begründung:

  - α ist technisch verlockend, praktisch riskant — wenn der eine 600k-Token-Call halluziniert, kostet ein
  Re-Run zwar nur $0.54, aber der User sieht die Halluzination möglicherweise nicht (Output-Volume zu groß für
   Spotcheck). Single-point-of-failure für ein Tool das semesterweise gepflegt wird.
  - β ist das pdf2anki-native Modell: jede Stage liefert auditierbare JSON-Outputs (genau wie das jetzt schon
  gebaute --dedup-Pattern), die per-Klausur-Granularität ermöglicht es einem Studi mid-flight zu verstehen
  "warum wurden diese 5 neuen Karten generiert", und der Pfad reuses --integrate (mit semantic-dedup) plus
  --dedup (mit cross-validation), die wir gerade gehärtet haben. Implementations-Aufwand ist überschaubar
  (~500 LOC), und das Pricing-Argument deines Modells ($5.20/Run einmal pro Semester) ist trivial.
  - γ liefert die einzige direkt messbare Qualität ("würde Alex die Klausur bestehen?"), aber: (a) doppelt so
  teuer wie β, (b) dreifach komplexer, (c) Konvergenz-Loop ist nicht-deterministisch. Lösung: γ als optionaler
   --validate-Pfad NACH β. β baut das Deck, γ misst es. Wenn der Score eine Schwelle (z.B. 80% Klausur-Pass)
  unterschreitet, gibt es einen Warning + automatisch eine zweite Surgeon-Runde. Das fängt das eine Szenario
  unterschreitet, gibt es einen Warning + automatisch eine zweite Surgeon-Runde. Das fängt das eine Szenario
  ab, das β strukturell nicht erkennt: Karten die thematisch korrekt klassifiziert sind, aber die konkrete
  Klausurfrage doch nicht beantworten (z.B. Definition vorhanden, aber Anwendungsbeispiel fehlt).
  - δ wäre rechnerisch optimal ($0.15/Run!), aber die Ontologie-Pflege je Kurs widerspricht dem
  Lazy-Mode-Geist von pdf2anki — der ganze Punkt von pdf2anki . ist, dass der Studi NICHTS konfigurieren muss.
   Die deterministischen Stages aus δ können aber als Pre-Filter in β eingebaut werden, um den Auditor-Call zu
   beschleunigen (Regex-Topic-Match findet 80% der Coverage trivial, der LLM muss nur die restlichen 20%
  prüfen). Das senkt β-Kosten von $5.20 auf vermutlich $1–2, ohne LOC-Komplexität nennenswert zu erhöhen.

  Konkrete Empfehlung der finalen Architektur:

  pdf2anki . --super-lazy [--validate]

    Phase 1  — Existing lazy mode (PDFs → cards → first-pass dedup → export)
    Phase 2A — Cartographer-Lite: deterministische Topic-Token-Match
               (kostenlos, identifiziert offensichtliche Coverage)
    Phase 2B — Auditor: LLM bestätigt + findet die nicht-trivialen Lücken
               (1 Call pro Klausur, nur für ungeklärte Themen)
    Phase 3  — Surgeon: Karten für identifizierte Lücken
    Phase 4  — Existing --integrate + --dedup + --export
    Phase 5  — Optional --validate: Examiner-Klausursimulation
               (zeigt operationalized pass-rate; bei < threshold: Phase 3 nochmal)

    Total: ~$2 pro Run, ~5 min, voll auditierbar, voll resumable.

  ---
  Welcher Pfad? Ich kann den β+δ-Hybrid implementieren als nächsten Schritt — oder du möchtest erst die
  Examiner-Komponente γ stand-alone testen (als Quality-Probe, ohne Implementations-Commitment), um die
  Pricing-Annahmen für Gemini 3 Flash zu validieren bevor wir das Architektur-Setup committen?

✻ Crunched for 2m 54s

❯ resketche die finale architektur phasenempfehlung angepasst auf β „Auditor + Surgeon" als
  Default-Implementation, ergänzt um eine --validate Mode der γ-Examiner als
    optionale Post-Hoc-Verifikation. - ausserdem skizziere ausfuehrlich die dementsprechende strategie. phase
   1 bleibt so klar, phase 1.5 muss noch geplant werden in der ja inhaltagnostisch erstmal die dokumente
  rausgesucht werden muessen die klausur/aufgaben/uebungsblaetter/xyz geeignet sind um dann beta und gamma zu
   drive. steelmanne meinen intent maximal und expliziere ihn als aufgabenstellung

● Steelmanned Intent

  Du erkennst zurecht: β und γ funktionieren nur, wenn das System a priori weiß welche Dokumente was sind.
  Heute behandelt pdf2anki . jeden .pdf/.txt als gleichberechtigte Source — daher landen Klausurfragen genauso
   im Karten-Kompost wie Skript-Definitionen, was die Coverage-Logik korrumpiert. Eine Klausur ist
  konzeptionell nicht dasselbe wie ein Skript-Kapitel: sie ist eine Probe dessen, was das Deck am Ende leisten
   muss, nicht eine Quelle für Karten-Inhalt. Eine Musterlösung ist Antwort-Material für Karten, nicht eine
  eigene Klausur. Ein Übungsblatt ist beides: es enthält Aufgaben (klausurnah) und liefert Stoff. Diese Rollen
   zu unterscheiden ist die nicht-triviale Voraussetzung für jede Form von "Coverage" oder "Pass"-Messung.

  Inhaltsagnostik bedeutet hier: kein hardcoded "if filename contains klausur", sondern ein generisches
  Discovery-Modul, das einem Studi in jeder Vorlesung in jeder Sprache mit jeder Verzeichnis-Struktur
  funktioniert. Das schließt aber nicht aus, dass deterministische Heuristiken (Filename-Patterns,
  Verzeichnis-Tokens, Pdf-Metadaten) als günstige Pre-Filter genutzt werden — solange sie in einem klar
  getrennten Stage liegen, dessen Resultat ein LLM danach validiert oder überstimmt. Außerdem muss die
  Pipeline graceful sein: ein Korpus mit Skript aber ohne Klausuren darf nicht crashen — er degradiert zu
  einem schwächeren Audit (gegen Skript-Inhaltsverzeichnis statt Klausurfragen).

  Phase 1.5 ist also die Anschluss-Schaltstelle zwischen "Material rein" (Phase 1) und "Material
  qualifizieren" (Phase 2 ff.). Sie produziert ein Rollen-Mapping, das die nachfolgenden Phasen
  fütterungs-präzise mit den richtigen Subkorpora versorgt — Test-Set für Auditor und Examiner, Source-Set für
   Surgeon, Pairing-Tabelle für die Antwort-Gewinnung aus Lösungsdokumenten.

  Aufgabenstellung

  Skizziere die finale --super-lazy Architektur mit den nun sieben Phasen (1, 1.5, 2A, 2B, 3, 4, 5). Phase 1
  bleibt unverändert (existing lazy mode). Phase 1.5 muss vollständig neu entworfen werden: Inputs,
  Sub-Stages, Output-Schema, Edge-Cases (fehlende Klausuren, ambiguose Dokumente, Pairing-Konflikte,
  Mehrsprachigkeit), Failure-Modes, Audit-Granularität. Phase 1.5 muss inhaltsagnostisch funktionieren — keine
   Annahmen über Sprache, Filename-Konvention oder Verzeichnis-Struktur. Sie darf deterministische Heuristiken
   als günstigen Pre-Filter nutzen, muss aber das Ergebnis durch eine LLM-Verifikations-Stufe validieren. Dann
   zeige für jede der nachfolgenden Phasen 2A/2B/3/4/5 explizit, welcher Subkorpus aus Phase 1.5 in sie
  hineinläuft.

  ---
  Final Architecture — pdf2anki . --super-lazy [--validate]

                                                         ┌─────────────────────────────┐
                                                         │ Phase 1: Lazy Mode (extant) │
                                                         │  PDF-discover → OCR →       │
                                                         │  ingest → integrate (with   │
                                                         │  in-flow dedup) → export    │
                                                         └──────────────┬──────────────┘
                                                                        │
                                                                        ▼
                                                         ┌─────────────────────────────┐
                                                         │ Phase 1.5: Document Role    │
                                                         │ Discovery   (NEW)           │
                                                         │  →  role_map.json           │
                                                         │  →  pair_map.json           │
                                                         │  →  test_corpus.json        │
                                                         │  →  source_corpus.json      │
                                                         └──────────────┬──────────────┘
                                                                        │
                                ┌───────────────────────────────────────┴───────────────────┐
                                ▼                                                           ▼
                  ┌──────────────────────────┐                                ┌──────────────────────────┐
                  │ Phase 2A: Cartographer-  │  (deterministic, no LLM)       │   ──────skip wenn        │
                  │ Lite Topic Match         │                                │   test_corpus = ∅────►   │
                  │  card-fronts ↔ exam-     │                                │                          │
                  │  fragments per regex     │                                │                          │
                  │  →  obvious_coverage.json│                                │                          │
                  └────────────┬─────────────┘                                │                          │
                               ▼                                              │                          │
                  ┌──────────────────────────┐                                │                          │
                  │ Phase 2B: LLM Auditor    │  1 LLM-Call pro Klausur        │                          │
                  │ on residual gaps only    │  (mit cached source_corpus)    │                          │
                  │  →  gap_matrix.json      │                                │                          │
                  └────────────┬─────────────┘                                │                          │
                               ▼                                              │                          │
                  ┌──────────────────────────┐                                │                          │
                  │ Phase 3: Surgeon         │  1 Call pro Lücke              │                          │
                  │  generate cards for gaps │  (sources aus source_corpus)   │                          │
                  │  →  generated_cards.json │                                │                          │
                  └────────────┬─────────────┘                                │                          │
                               ▼                                              │                          │
                  ┌──────────────────────────┐                                │                          │
                  │ Phase 4: Re-Integrate    │  reuse existing                │                          │
                  │  --integrate (with       │  --integrate / --dedup /       │                          │
                  │  semantic dedup)         │  --export                      │                          │
                  │  --dedup --apply         │                                │                          │
                  │  --export                │                                │                          │
                  └────────────┬─────────────┘                                │                          │
                               ▼                                              │                          │
     --validate?  ─────────────┬─────────────────────────────────────────────►│                          │
                               ▼                                              ▼                          │
                  ┌──────────────────────────────────────────────────────────────────────┐               │
                  │ Phase 5 (optional): γ-Examiner                                       │               │
                  │  Pro Klausur: LLM nimmt das Deck als einziges Hilfsmittel und        │               │
                  │  „beantwortet" die Klausur. Output: per-Frage Pass/Fail + zitierte   │               │
                  │  Karten + identifizierte Restlücken.                                 │               │
                  │  Pass-Rate < threshold? → Phase 3 nochmal mit Restlücken            │               │
                  │  → exam_results.json + verdict.json                                  │               │
                  └──────────────────────────────────────────────────────────────────────┘

  ---
  Phase 1.5 — Document Role Discovery (detaillierte Strategie)

  Eingabe

  Aus Phase 1 vorhanden: alle PDF-Dateien des Projekts plus deren OCR'd .txt-Versionen. Dazu File-Metadata
  (Pfad, Größe, mtime), Verzeichnis-Tokens (Kursmaterial/Skript_ws_25/skript-1.pdf → tokens [Kursmaterial,
  Skript_ws_25]), und PDF-Header-Metadata wenn vorhanden.

  Ausgabe-Artefakte

  role_map.json — Rolle pro Dokument

  {
    "schema_version": 1,
    "documents": [
      {
        "path": "Kursmaterial/Skript_ws_25/skript-1.pdf",
        "role": "script",
        "subrole": null,
        "confidence": "HIGH",
        "decided_by": "deterministic",
        "rationale": "Filename token 'skript' + first-page contains 'Vorlesung'"
      },
      {
        "path": "altklausuren_und_protokolle/.../klausur23ss.pdf",
        "role": "exam",
        "subrole": "main",
        "confidence": "HIGH",
        "decided_by": "deterministic",
        "rationale": "Filename token 'klausur' + structural cue: scoring table on cover page"
      },
      {
        "path": ".../klausur23ss_musterlösung.pdf",
        "role": "solution",
        "subrole": null,
        "paired_with": "altklausuren_und_protokolle/.../klausur23ss.pdf",
        "confidence": "HIGH",
        "decided_by": "deterministic+pairing",
        "rationale": "filename suffix '_musterlösung' + prefix matches existing exam"
      },
      {
        "path": ".../Hausuebung01.pdf",
        "role": "exercise",
        "subrole": "graded_homework",
        "confidence": "MEDIUM",
        "decided_by": "llm",
        "rationale": "Tokens 'hausuebung' ambiguous; LLM identified problem-set structure plus point-table →
  exercise sheet"
      }
    ]
  }

  Rollenkatalog (festes Vokabular):

  ┌───────────┬────────────────────────────────────────────────────────┬──────────────────────────────────┐
  │   role    │                       Bedeutung                        │      Phase-2-Zugehörigkeit       │
  ├───────────┼────────────────────────────────────────────────────────┼──────────────────────────────────┤
  │ script    │ Vorlesungsskript / Folien — primäre Karten-Quelle      │ source_corpus                    │
  ├───────────┼────────────────────────────────────────────────────────┼──────────────────────────────────┤
  │ exam      │ Geprüfte Klausur — Test-Bench für β/γ                  │ test_corpus                      │
  ├───────────┼────────────────────────────────────────────────────────┼──────────────────────────────────┤
  │ exercise  │ Übungsblatt / Tutorium / Hausübung — Sekundärquelle    │ source_corpus + (optional)       │
  │           │ UND klausurnahe Aufgaben                               │ test_corpus                      │
  ├───────────┼────────────────────────────────────────────────────────┼──────────────────────────────────┤
  │ solution  │ Musterlösung zu exam oder exercise — Antwort-Material  │ reference_corpus                 │
  ├───────────┼────────────────────────────────────────────────────────┼──────────────────────────────────┤
  │ notes     │ Mitschriften / Protokolle / Notizen — schwächere       │ source_corpus                    │
  │           │ Quelle                                                 │                                  │
  ├───────────┼────────────────────────────────────────────────────────┼──────────────────────────────────┤
  │ auxiliary │ Formelsammlung, Glossar, README, Cheat-Sheet           │ source_corpus (low-priority)     │
  ├───────────┼────────────────────────────────────────────────────────┼──────────────────────────────────┤
  │ unknown   │ Konnte nicht zugeordnet werden — Output an User        │ escalation                       │
  └───────────┴────────────────────────────────────────────────────────┴──────────────────────────────────┘

  subrole ist optional, freitextlich, nur informativ. Z.B. main, repetitorium, kurzklausur, mock,
  graded_homework.

  pair_map.json — Dokumenten-Pärchen

  {
    "schema_version": 1,
    "pairs": [
      {"primary": "klausur23ss.pdf", "secondary": "klausur23ss_musterlösung.pdf",
       "relation": "exam_with_solution", "confidence": "HIGH"},
      {"primary": "Uebungsblatt03.pdf", "secondary": "Uebungsblatt03_loesung.pdf",
       "relation": "exercise_with_solution", "confidence": "HIGH"}
    ]
  }

  Wichtig wegen §2.4 der KLAUSUR_REVIEW.md-Logik: wenn beide existieren, ist die Solution-Version eine
  qualitativ bessere Quelle für Phase-2B-Auditor (sie enthält Aufgaben und Antworten in einem Dokument).
  Phase-2B nimmt das Solution-Dokument statt der unlabeled-Version.

  test_corpus.json und source_corpus.json — Materialized Views

  Aggregierte Listen, präfilterung der role_map:

  // test_corpus.json
  {
    "documents": ["klausur23ss_musterlösung.pdf", "klausur24ss_rep_loesungshinweise.pdf",
                  "klausur19ws.pdf", ...],
    "total": 64,
    "preferred_pairing_used": true
  }

  // source_corpus.json
  {
    "documents_by_role": {
      "script": ["skript-1.pdf"],
      "exercise": ["Uebungsblatt01.pdf", ..., "Hausuebung01.pdf", ...],
      "notes": ["mitschrift_tutorium01.pdf", ...]
    },
    "weights": {"script": 1.0, "exercise": 0.8, "notes": 0.5}
  }

  Sub-Phasen

  1.5a — Deterministischer Pre-Filter (kostenlos, schnell)

  Eingabe: Filename, Verzeichnis-Pfad, PDF-Header (Title, Author).

  Multi-language Token-Catalog (additiv pflegbar):

  exam       ← klausur, exam, prüfung, pruefung, kk, kurzklausur
  exercise   ← übung, uebung, exercise, hausübung, hausuebung, tutorium, tutorial,
               aufgabenblatt, übungsblatt, uebungsblatt, hu, ü
  solution   ← lösung, loesung, musterlösung, musterloesung, loesungshinweise,
               solution, sol, answer, solutions
  script     ← skript, script, vorlesung, lecture, slides, folien, lecturenotes
  notes      ← mitschrift, notes, protokoll, transcript, summary

  Algorithmus:
  1. Tokenize path: split auf /, _, -, ., lowercase
  2. Match gegen catalog → tentative role + confidence
  3. Spezialregel Pairing: wenn ein Doc eine Solution-Token hat UND ein Doc mit dem gleichen non-solution-Stem
   existiert → markiere als pair
  4. Spezialregel Suffix-Stripping: klausur23ss_musterlösung → stem klausur23ss, role candidate solution,
  pairing target klausur23ss.pdf falls vorhanden

  Confidence-Logik:
  - HIGH: ≥1 Token aus dem Catalog matcht und keine widersprüchlichen Signale
  - MEDIUM: 1 Token aber strukturell unklar (z.B. nur das Wort "übung" und sonst nix)
  - LOW: kein Catalog-Match, Filename ist generisch ("Document1.pdf", "scan_2024.pdf")

  Output: role_map_draft.json mit Confidence-Verteilung; HIGH-Entries gehen direkt in Phase 1.5c, MEDIUM und
  LOW werden an Phase 1.5b weitergereicht.

  1.5b — LLM-Verifikation (kostenpflichtig, präzise)

  Nur für MEDIUM- und LOW-Confidence-Dokumente und für stichprobenartige Validierung von HIGH-Entries (~5%).

  Single mega-call (1M-Context-fähig): Sende für jedes ungeklärte Dokument die ersten ~2 Seiten OCR-Text +
  Filename + Pfad-Tokens. Prompt:

  Du klassifizierst Lehrmaterial-Dokumente nach ihrer didaktischen Rolle.

  ROLLEN-VOKABULAR:
  - script:     Vorlesungsskript, Folien — Primärquelle für Lerninhalt
  - exam:       Geprüfte Klausur (graded summative assessment)
  - exercise:   Übungsblatt, Hausübung, Tutorium-Aufgaben
  - solution:   Musterlösung / Lösungshinweise zu exam oder exercise
  - notes:      Mitschriften, Protokolle (sekundäre, oft inoffizielle Quelle)
  - auxiliary:  Formelsammlung, Glossar, README, Spickzettel
  - unknown:    Lässt sich nicht zuordnen

  REGELN:
  - Eine Klausur hat typisch: Punktetabelle, Aufgabe-X-Format, Zeitlimit-Hinweis,
    Identifikations-Felder.
  - Eine Musterlösung hat: zugehörige Aufgaben + ausformulierte Antworten.
  - Übungsblätter haben: nummerierte Aufgaben, oft "Abgabe: <Datum>".
  - Skripte haben: Inhaltsverzeichnis, Kapitelstruktur, definitorischer Stil.

  EINGABE:
  [für jedes Dokument: path, filename, first 2 pages text]

  AUSGABE als JSON:
  {"classifications": [
    {"path": "...", "role": "<rolle>", "subrole": "<frei|null>",
     "confidence": "HIGH|MEDIUM|LOW", "rationale": "<1-2 Sätze>"}
  ]}

  Multi-language ist gratis: das Modell erkennt deutsche/englische/französische Begriffe ohne extra
  Konfiguration — genau das, was die Inhaltsagnostik fordert.

  1.5c — Pairing & Materialization

  Deterministisch, kein LLM nötig.

  Algorithmus (siehe README §2.4 Logik):
  1. Für jedes solution-Doc: extrahiere stem (klausur23ss_musterlösung → klausur23ss)
  2. Suche in role_map ein Dokument mit gleichem stem und Rolle exam oder exercise
  3. Wenn gefunden: erzeuge Eintrag in pair_map.json mit relation = exam_with_solution oder
  exercise_with_solution
  4. Wenn solution alleine steht ohne primary: behalte als standalone solution; dieses Doc wird in Phase 2B
  als eigene Klausur behandelt (typisch für WS17 Kurzklausuren wo nur Lösungs-PDFs vorliegen)
  5. Materialize test_corpus.json und source_corpus.json per Rollenfilter

  1.5d — Edge-Case-Handling und Eskalation

  Drei Eskalations-Pfade:

  ┌────────────────────────────────────────────────────┬──────────────────────────────────────────────────┐
  │                      Szenario                      │                    Verhalten                     │
  ├────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │                                                    │ Phase 2A/2B/3/5 werden übersprungen mit Warning. │
  │ test_corpus ist leer                               │  Pipeline degradiert zu reinem Build (Phase 1 +  │
  │                                                    │ 4).                                              │
  ├────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │                                                    │ Pipeline pausiert vor Phase 2 mit Bericht; user  │
  │ Mehr als 5 Docs als unknown klassifiziert          │ muss role_map.json manuell editieren oder mit    │
  │                                                    │ --super-lazy --skip-discovery skippen            │
  ├────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │                                                    │ Heuristik: kürzester Filename = primary,         │
  │ Pair-Conflict (3 Docs mit gleichem stem)           │ "_musterlösung" suffix = solution,               │
  │                                                    │ "_loesungshinweise" = secondary solution.        │
  │                                                    │ Konflikt protokollieren.                         │
  ├────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │                                                    │ Kein Problem für 1.5b (LLM ist                   │
  │ Sprache nicht erkannt                              │ sprachagnostisch); nur 1.5a degradiert auf       │
  │                                                    │ MEDIUM/LOW, was 1.5b einfach mehr arbeiten lässt │
  ├────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ Doc enthält alle Rollen-Signale (z.B.              │ LLM disambiguiert basierend auf Inhalt; Output   │
  │ "klausurvorbereitung_uebung_loesung.pdf")          │ mit subrole annotiert                            │
  └────────────────────────────────────────────────────┴──────────────────────────────────────────────────┘

  Audit & Resumability

  Wie bei --dedup:
  - Output in role_discovery_<timestamp>/
  - --from-phase 1.5b resumed direkt aus 1.5a-Output
  - role_map.json ist read-write: Studi kann manuelle Korrekturen einkippen, Phase 1.5c läuft danach
  idempotent
  - Metrics: discovery_summary.json mit Counter pro Rolle + Confidence-Verteilung

  Wie Phase 1.5 die nachfolgenden Phasen füttert

  ┌────────────────────┬──────────────────────────────────────────┬───────────────────────────────────────┐
  │       Phase        │                Konsumiert                │                 Wofür                 │
  ├────────────────────┼──────────────────────────────────────────┼───────────────────────────────────────┤
  │ 2A                 │ test_corpus.json                         │ Token-Match jeder Test-Frage gegen    │
  │ Cartographer-Lite  │                                          │ Karten-Fronts                         │
  ├────────────────────┼──────────────────────────────────────────┼───────────────────────────────────────┤
  │                    │ test_corpus.json (Test) +                │ Pro Klausur: LLM bekommt              │
  │ 2B LLM-Auditor     │ source_corpus.json (Quelle, gecached im  │ Klausurfragen + alle aktuellen        │
  │                    │ Prompt-Prefix) + pair_map.json           │ Karten-Fronts → identifiziert echte   │
  │                    │ (Lösung-Bevorzugung)                     │ Coverage-Lücken                       │
  ├────────────────────┼──────────────────────────────────────────┼───────────────────────────────────────┤
  │                    │ gap_matrix.json (aus 2B) +               │ Generiert Karten, muss Source angeben │
  │ 3 Surgeon          │ source_corpus.json (gewichtet:           │  aus der die Karte extrahiert wurde — │
  │                    │ script>exercise>notes)                   │  Halluzinations-Bremse                │
  ├────────────────────┼──────────────────────────────────────────┼───────────────────────────────────────┤
  │ 4 Re-Integrate     │ generated_cards.json                     │ Existing pipeline, semantic dedup     │
  │                    │                                          │ gegen aktuelles Deck                  │
  ├────────────────────┼──────────────────────────────────────────┼───────────────────────────────────────┤
  │ 5 Examiner         │ test_corpus.json (gleicher Subkorpus wie │ Operationaler Pass-Test: LLM löst     │
  │ (--validate)       │  2B) + Final-Deck nach Phase 4           │ Klausuren mit Deck als einzigem       │
  │                    │                                          │ Hilfsmittel; Pass-Rate als Metrik     │
  └────────────────────┴──────────────────────────────────────────┴───────────────────────────────────────┘

  ---
  Aktualisierte Kostenrechnung

  ┌──────────────────────────────┬──────────────────────────────────────────────┬────────────────────────┐
  │            Phase             │     Kosten (Gemini 3 Flash $0.50/$2.00)      │    Wann fällt es an    │
  ├──────────────────────────────┼──────────────────────────────────────────────┼────────────────────────┤
  │ 1 (existing lazy mode)       │ ~$0.50                                       │ jedes Mal              │
  ├──────────────────────────────┼──────────────────────────────────────────────┼────────────────────────┤
  │ 1.5a (deterministic)         │ $0.00                                        │ jedes Mal              │
  ├──────────────────────────────┼──────────────────────────────────────────────┼────────────────────────┤
  │                              │                                              │ nur wenn               │
  │ 1.5b (LLM verify)            │ ~$0.10 (50k input + 5k output, single call)  │ MEDIUM/LOW-Docs        │
  │                              │                                              │ vorhanden              │
  ├──────────────────────────────┼──────────────────────────────────────────────┼────────────────────────┤
  │ 1.5c (pairing)               │ $0.00                                        │ jedes Mal              │
  ├──────────────────────────────┼──────────────────────────────────────────────┼────────────────────────┤
  │ 2A (Cartographer-Lite)       │ $0.00                                        │ nur wenn test_corpus ≠ │
  │                              │                                              │  ∅                     │
  ├──────────────────────────────┼──────────────────────────────────────────────┼────────────────────────┤
  │                              │ ~$0.50–$2.00 (skaliert mit residualen        │                        │
  │ 2B (Auditor)                 │ Lücken; 1M-Context erlaubt cached            │ dito                   │
  │                              │ source_corpus)                               │                        │
  ├──────────────────────────────┼──────────────────────────────────────────────┼────────────────────────┤
  │ 3 (Surgeon)                  │ ~$0.20–$0.80 (skaliert mit Lücken-Anzahl)    │ dito                   │
  ├──────────────────────────────┼──────────────────────────────────────────────┼────────────────────────┤
  │ 4 (existing                  │ ~$0.30                                       │ jedes Mal              │
  │ integrate+dedup+export)      │                                              │                        │
  ├──────────────────────────────┼──────────────────────────────────────────────┼────────────────────────┤
  │ 5 (Examiner, optional via    │ ~$2.00–$3.50                                 │ nur wenn --validate    │
  │ --validate)                  │                                              │                        │
  └──────────────────────────────┴──────────────────────────────────────────────┴────────────────────────┘

  Total --super-lazy ohne --validate: ~$1.10–$3.70/Run
  Total --super-lazy --validate: ~$3.10–$7.20/Run

  Vergleich zu vorherigen β-Schätzung ($5.20): Phase-2A-Pre-Filter und Caching des source_corpus im
  Prompt-Prefix senken Kosten signifikant. Die größte Variabilität kommt aus der Lücken-Menge: kleines Deck
  mit vielen Lücken → Surgeon teuer; reifes Deck mit wenigen Lücken → fast geschenkt.

  ---
  Offene Fragen vor Implementation

  1. role "exercise" — soll es als Test-Korpus zählen oder nur als Source? Argument pro Test: Übungsblätter
  sind klausurnah und bilden gute Ground-Truth. Argument contra: dann wird der Surgeon ihre Aufgaben in Karten
   umwandeln, die er dann gegen Übungs-Fragen testet → potenzielle Zirkularität. Mein Vorschlag: default
  Source-only, mit Flag --exercises-as-tests für strenges Audit.
  2. Phase 1.5 Position im Pipeline-Flow — sollte sie wirklich nach Phase 1 laufen oder sinnvoller vor?
  Argument für nach: Phase 1 hat schon OCR'd, also sind die .txt-Dateien für 1.5b verfügbar. Argument für vor:
   dann könnte Phase 1 selbst die Rolle nutzen (z.B. Klausuren nicht in den Card-Pool aufnehmen, was
  vermutlich richtiger ist als jetzt). Mein Vorschlag: Phase 1.5 läuft VOR Phase 1, Phase 1 wird angepasst
  sodass sie nur source_corpus ingestet, nicht test_corpus. Das räumt das Daten-Modell sauber auf.
  3. --validate als Loop oder Single-Shot? — wenn die Pass-Rate unter Schwelle liegt: nochmal Phase 3+4 mit
  den neu identifizierten Lücken aus Phase 5? Risk: Endlos-Schleife wenn das Modell die gleichen Lücken in
  jeder Runde wieder findet. Mein Vorschlag: max 2 Iterationen, danach hart abbrechen mit Warning.

  Bestätige (oder korrigiere) diese drei Punkte, dann implementiere ich Phase 1.5 als ersten Baustein. Sie ist
   eigenständig committbar und blockiert nicht — auch ohne β/γ ist ein sauberer role_map.json schon ein Wert
  für sich (z.B. um die existing --ingest-Logik zu verbessern, sodass Klausuren nicht mehr versehentlich als
  Karten-Quelle landen).

✻ Worked for 2m 55s

❯ passe deinen plan nochmal an. ich will keinen cartographer lite.(deterministic, no LLM) ist porblematisch
  bzgl universalisierungs approach des repos. Das schließt aber nicht aus, dass deterministische Heuristiken
  (Filename-Patterns,
    Verzeichnis-Tokens, Pdf-Metadaten) als günstige Pre-Filter genutzt werden — solange sie in einem klar
    getrennten Stage liegen - da stimme ich auch nicht richtig zu. pdf2anki soll keine guenstigen prefilter
  als dauerhafte heuristiken verwenden oder hardcoden. wenn heuristiken intra-korpus verwendet werden dann
  nur wenn sie von einem llm gesetzt werden. gib den angepassten plan vollstaendig aus. steelmanne meinen
  intent maximal und expliziere ihn als aufgabenstellung

● Steelmanned Intent

  Du erkennst eine Architektur-Hygiene-Frage, die ich zu locker behandelt habe: pdf2anki soll ein universelles
   Tool sein. Das heißt operational: ein Studi mit chinesischen Statistik-Skripten, ein französischer
  Biostudent, ein indischer Maschinenbau-Lehrling — alle sollten pdf2anki . benutzen können ohne dass das Tool
   kulturelle/linguistische/disziplinäre Annahmen mitbringt. Sobald irgendwo im Repo ein Token-Catalog
  {"klausur", "exam", "prüfung"} oder ein Topic-Match-Regex r"pumping[-_ ]lemma" einzieht, ist das Tool nicht
  mehr universell — es ist ein deutsches CS-Studi-Tool das in andere Kontexte schlecht generalisiert. Jede
  solche Heuristik ist eine embedded assumption, die in der Code-Review schwer auffällt aber in der nächsten
  Zielgruppe sofort bricht.

  Der saubere Pfad: das LLM ist die einzige semantische Schicht. pdf2anki ist Plumbing +
  LLM-Call-Orchestrierung + JSON-Manipulation. Wenn pro Korpus Heuristiken nötig sind, derived sie das LLM zur
   Laufzeit und legt sie in die Run-Artefakte — sie leben dort als beobachtete Eigenschaften des konkreten
  Korpus, nicht als hardcoded Code-Constants. Auch deterministische Stages bleiben erlaubt, aber nur wenn sie
  keine semantische Entscheidung treffen — z.B. JSON-Joins über bereits-vom-LLM-vergebene Schlüssel, Filter
  über LLM-vergebene Confidence-Levels, Materialization von Corpus-Views per Rolle. Das ist Plumbing, nicht
  Heuristik.

  Konsequenz: Phase 2A "Cartographer-Lite" fliegt komplett raus. Sie war eine Coverage-Heuristik mit
  eingebackener Topic-Ontologie, das ist exakt die Klasse Code die du nicht im Repo haben willst. Mit Gemini 3
   Flash bei 1M Context und $0.50 / $2.00 Pricing ist die Optimierung "spar dir den LLM-Call durch
  Regex-Match" nicht mehr nötig — die Mega-Call-Pattern aus dem --dedup-Detection-Stage skaliert direkt auf
  alle Audit-Stages. Eine 700k-Token-Klausur-Audit-Mega-Call kostet $0.40. Das ist günstiger als die
  Komplexität eines deterministischen Pre-Filters wert ist.

  Damit reduziert sich der Plan auf weniger Stages, jede klar als "LLM-driven" oder "pure data-manipulation"
  markiert, mit explizitem Verbot hardcoded Vokabulare oder Patterns im Repo.

  Aufgabenstellung

  Skizziere den finalen --super-lazy Plan vollständig neu mit folgender Disziplin:

  1. Keine hardcoded semantischen Heuristiken im pdf2anki-Repo. Kein Token-Catalog für Rollen, kein
  Topic-Regex, keine Domain-Ontologie. Wenn eine Heuristik für einen konkreten Korpus nützlich wäre, erzeugt
  sie das LLM zur Laufzeit und legt sie als Run-Artefakt ab.
  2. Phase 2A entfernt. Nur noch Phase 2 (LLM-Auditor) mit einem oder wenigen Mega-Calls.
  3. Phase 1.5 wird LLM-First: keine deterministische Filename-Token-Vorprüfung. Single LLM mega-call
  klassifiziert alle Dokumente auf einen Schlag mit dem 1M-Context-Fenster. Pairing und Materialization sind
  danach pure JSON-Transformationen über LLM-Output.
  4. Für jede Stage explizit annotieren: "LLM-driven" (semantische Entscheidung) oder "data-manipulation"
  (kein Wissen, nur Umstrukturierung). Mischformen sind nicht erlaubt.
  5. Cost-Recompute mit dem Mega-Call-Pattern.
  6. Edge-Cases dokumentieren ohne deterministische Sprach- oder Domain-Annahmen.

  ---
  Final Architecture — pdf2anki . --super-lazy [--validate]

                                    ┌─────────────────────────────────────────────────┐
                                    │ Phase 1: Lazy Mode (existing)                   │
                                    │ DEFER ingest/integrate until role_map exists.   │
                                    │ This phase produces ONLY ocr'd .txt per pdf.    │
                                    └────────────────────────┬────────────────────────┘
                                                             │
                                                             ▼
                                    ┌─────────────────────────────────────────────────┐
                                    │ Phase 1.5: Document Role Discovery [LLM-driven] │
                                    │ → role_map.json   pair_map.json                 │
                                    │ → test_corpus.json   source_corpus.json         │
                                    └────────────────────────┬────────────────────────┘
                                                             │
                                                             ▼
                                    ┌─────────────────────────────────────────────────┐
                                    │ Phase 1.6: Resumed Lazy-Build [data-manipulation│
                                    │ + existing pipeline]                            │
                                    │ Ingest only documents in source_corpus.         │
                                    │ Existing --integrate (with semantic dedup)      │
                                    │ → card_database.json   collection_*.json        │
                                    └────────────────────────┬────────────────────────┘
                                                             │
                                [test_corpus = ∅?]───────────┼────skip rest, warn user
                                                             │
                                                             ▼
                                    ┌─────────────────────────────────────────────────┐
                                    │ Phase 2: Audit [LLM-driven, single mega-call]   │
                                    │ → gap_matrix.json                               │
                                    └────────────────────────┬────────────────────────┘
                                                             │
                                              [no gaps?]─────┼────skip rest, exit ok
                                                             │
                                                             ▼
                                    ┌─────────────────────────────────────────────────┐
                                    │ Phase 3: Surgeon [LLM-driven, single mega-call] │
                                    │ → generated_cards.json (with source citations)  │
                                    └────────────────────────┬────────────────────────┘
                                                             │
                                                             ▼
                                    ┌─────────────────────────────────────────────────┐
                                    │ Phase 4: Re-Integrate [existing pipeline]       │
                                    │ --integrate + --dedup --apply + --export        │
                                    └────────────────────────┬────────────────────────┘
                                                             │
                                              ────[--validate]───┐
                                                             │   │
                                                             ▼   ▼
                                    ┌─────────────────────────────────────────────────┐
                                    │ Phase 5: Examiner [LLM-driven] (optional)       │
                                    │ Per-Exam simulation; pass-rate as metric        │
                                    │ pass-rate < threshold ∧ iter < 2  →  Phase 3    │
                                    │ → exam_results.json   verdict.json              │
                                    └─────────────────────────────────────────────────┘

  Alle Phasen, die das Wort „LLM-driven" tragen, treffen semantische Entscheidungen — dort lebt das Wissen
  über Bedeutung. Alle Phasen, die „data-manipulation" tragen, nehmen LLM-Output als gegeben und
  transformieren ihn in Views, Joins, Filter. Mischformen sind verboten.

  ---
  Phase 1.5 — Document Role Discovery (revised)

  Was sich ändert ggü dem vorigen Plan

  ┌───────────────────────────────────────────────────────┬───────────────────────────────────────────────┐
  │                        Vorher                         │                     Jetzt                     │
  ├───────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ 1.5a deterministischer Filename-Token-Match           │ gestrichen                                    │
  ├───────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ 1.5b LLM nur für residuale MEDIUM/LOW-Docs            │ wird zu 1.5a, klassifiziert ALLE              │
  ├───────────────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ 1.5c Pairing per stem-Match (deterministisch, aber    │ bleibt — pure JSON-Transformation über        │
  │ von LLM identifiziert)                                │ LLM-bestätigte Pärchen                        │
  └───────────────────────────────────────────────────────┴───────────────────────────────────────────────┘

  1.5a — LLM-Klassifikation (single mega-call)

  Eingabe (alles im 1M-Context):
  - Pfad jedes Dokuments
  - Erste ~3-5 Seiten OCR-Text jedes Dokuments (Budget dynamisch: total ≤ 800k Tokens)
  - Optional: PDF-Metadata (Title, Author) wenn vorhanden — aber kein Filename-Pattern-Matching

  Prompt-Skelett (vollständig generisch, kein institutional/Sprach-Bias):

  Analyze this corpus of educational documents. Classify each document by its
  didactic role using the role vocabulary below. The role of a document is its
  intended FUNCTION in a learning workflow, not its filename or title.

  Role vocabulary (open-ended, mutually exclusive within a single doc):
  - script:    Primary teaching material (textbook, lecture script, slides).
               Definitorial/expository style, structured by chapters or sections.
  - exam:      Summative assessment that was/will be graded. Time-limited, formal
               question format, typically with point distribution and identification
               fields.
  - exercise:  Practice problems, homework, tutorial assignments. Numbered tasks,
               often paired with submission deadline. May be graded or ungraded.
  - solution:  Reference answers paired with an exam or exercise. Contains both
               questions and worked-out solutions.
  - notes:     Secondary, often informal: personal transcripts, tutorial protocols,
               study summaries.
  - auxiliary: Supporting material: glossary, formula sheet, reading list, README.
  - unknown:   Insufficient context to classify.

  For each document, additionally report:
  - pairing: if this document references another document in the corpus as its
             companion (e.g., a solution paired with its exam), name the partner
             and the relation type.
  - confidence: HIGH / MEDIUM / LOW
  - rationale: 1-2 sentences referencing concrete textual or structural cues you
               observed (NOT the filename).

  CORPUS:
  [Doc A]
    path: ...
    first_pages: ...
  [Doc B]
    ...

  Output JSON:
  {"classifications": [
    {"path": "...", "role": "...", "subrole": "...|null",
     "pairing": {"partner_path": "...|null", "relation": "exam_with_solution|exercise_with_solution|null"},
     "confidence": "HIGH|MEDIUM|LOW",
     "rationale": "..."}
  ], "corpus_observations": "<freitext: was hat das modell ueber den korpus an strukturellen mustern
  beobachtet?>"}

  Wichtig: das corpus_observations Feld ist explizit ein freier Text-Output, in dem das Modell beobachtete
  Korpus-spezifische Patterns festhalten kann (z.B. "alle Dateien in Sortiert/ sind Klausuren" oder "Dateien
  mit Suffix _loesung sind Lösungen zu der gleichnamigen Klausur"). Das ist die einzige Stelle, an der der
  Plan korpus-spezifische Heuristiken duldet — sie sind LLM-derived, im Run-Artefakt persistiert, nicht im
  Code, und nur informativ.

  Kosten (~80 Docs × 5k Tokens Vorab-Sample + 20k Output): 400k input + 20k output ≈ $0.24

  1.5b — Re-Klassifikation für niedrigvertrauliche Dokumente

  Optional: für jedes Doc mit confidence ∈ {MEDIUM, LOW} — sende den vollen OCR-Text (statt nur die ersten
  Seiten) zurück ans LLM für eine zweite Klassifikation. Pure LLM-driven.

  Kosten (variabel; meist 0–10 Dokumente, ~$0.05 maximal): ≤ $0.10

  1.5c — Pairing & Corpus-Materialization (data-manipulation, no semantic decision)

  Reine JSON-Transformation, kein LLM nötig:

  1. Aggregiere pairing-Felder aus 1.5a/b zu pair_map.json. Wenn ein Doc als Partner eines anderen
  referenziert wird, das aber nicht zurückreferenziert: einseitige Beziehung markieren, escalate wenn
  inconsistent.
  2. Projiziere role_map zu test_corpus.json: alle Docs mit role ∈ {exam}, plus standalone solution-Docs ohne
  Partner (das WS17-Kurzklausur-Szenario).
  3. Wenn ein Pair exam_with_solution existiert: in test_corpus.json wird die Solution-Version eingetragen
  (sie enthält Aufgaben + Antworten).
  4. Projiziere role_map zu source_corpus.json: alle Docs mit role ∈ {script, exercise, notes, auxiliary} plus
   Solutions die in test_corpus schon stehen (für Antwort-Referenzen).
  5. Optionaler User-Eingriff: role_map.json ist read-write; Re-run von 1.5c ist idempotent über manuelle
  Korrekturen.

  Diese Stage trifft keine semantische Entscheidung. Sie joint nur LLM-Output mit JSON-Schema. Erlaubt, weil
  Plumbing.

  Edge-Cases (alle ohne hardcoded Annahmen)

  ┌────────────────────────────┬──────────────────────────────────────────────────────────────────────────┐
  │          Szenario          │                                Verhalten                                 │
  ├────────────────────────────┼──────────────────────────────────────────────────────────────────────────┤
  │ test_corpus = ∅            │ Phasen 2/3/5 werden übersprungen, Pipeline degradiert zu Phase-1+4-Build │
  │                            │  mit Warning.                                                            │
  ├────────────────────────────┼──────────────────────────────────────────────────────────────────────────┤
  │                            │ Pipeline pausiert, schreibt Bericht mit den unknowns +                   │
  │ > 5 Docs als unknown       │ Re-Klassifikations-Hinweis, User kann manuell editieren oder             │
  │                            │ --accept-unknowns setzen.                                                │
  ├────────────────────────────┼──────────────────────────────────────────────────────────────────────────┤
  │ Pair-Konflikt (3 Docs      │ Der LLM-Output ist die Quelle der Wahrheit — wenn das LLM keine          │
  │ referenzieren sich         │ eindeutige Pairing-Aussage macht, behandelt 1.5c alle 3 als standalone.  │
  │ gegenseitig)               │ Audit-Eintrag in pair_conflicts.json.                                    │
  ├────────────────────────────┼──────────────────────────────────────────────────────────────────────────┤
  │ Mehrsprachigkeit           │ Kein Spezialcode nötig; LLM klassifiziert sprachagnostisch. Wenn der     │
  │                            │ Korpus ein Mix ist, wird das im corpus_observations-Freitext landen.     │
  ├────────────────────────────┼──────────────────────────────────────────────────────────────────────────┤
  │ Filename völlig generisch  │ LLM klassifiziert auf Basis von Inhalt allein; confidence darf           │
  │ (Document1.pdf)            │ MEDIUM/LOW sein.                                                         │
  ├────────────────────────────┼──────────────────────────────────────────────────────────────────────────┤
  │ Korpus zu groß für 1M-Call │ LLM-driven Chunking: erst kleine Stichprobe an LLM mit Frage "extract a  │
  │  (>2000 Docs)              │ corpus-classification scheme", dann Chunks gegen das LLM-erzeugte        │
  │                            │ Schema. Heuristik wird LLM-set, nicht hardcoded.                         │
  └────────────────────────────┴──────────────────────────────────────────────────────────────────────────┘

  ---
  Phase 1.6 — Resumed Lazy-Build (data-manipulation + existing pipeline)

  Die existing lazy_runner wird so angepasst, dass sie nur Docs aus source_corpus.json ingestet. Klausuren
  landen nicht mehr im Card-Pool — heute schon ein latenter Bug, der sich aber durch die fehlende
  Rolle-Trennung tarnt.

  ┌───────────┬───────────────────────┬────────────────────────────────────────────────────────────────────┐
  │ Sub-Stage │      LLM-driven?      │                            Was passiert                            │
  ├───────────┼───────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ 1.6a      │ data-manip            │ Filter PDFs nach source_corpus; Phase-1-OCR-Output wiederverwenden │
  ├───────────┼───────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ 1.6b      │ LLM-driven (existing) │ workflow --ingest auf source-Set                                   │
  ├───────────┼───────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ 1.6c      │ LLM-driven (existing) │ workflow --integrate mit semantic-dedup                            │
  ├───────────┼───────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ 1.6d      │ data-manip (existing) │ workflow --export                                                  │
  └───────────┴───────────────────────┴────────────────────────────────────────────────────────────────────┘

  Kostet ~$0.50 (entspricht heutigem Phase 1).

  ---
  Phase 2 — Audit (LLM-driven, single mega-call)

  Eingabe (im 1M-Context):
  - Vollständiger OCR-Text aller Klausuren aus test_corpus.json (~640k Tokens für 64 Klausuren)
  - Alle Karten-Fronts aus card_database.json (~18k Tokens)
  - Optional Karten-Backs (~100k Tokens) — falls Pass-Schätzung gemeinsam mit Audit gemacht werden soll, sonst
   weglassen

  Prompt:

  For each exam in the test corpus, identify the questions/tasks it poses.
  Then, for each question, decide whether the current Anki deck contains a card
  that would let a student answer it. If yes: cite the card front. If no:
  describe the missing concept/skill in 1 sentence.

  Output JSON:
  {"per_exam": [
    {"exam_path": "...",
     "questions": [
       {"question_id": "task_1a",
        "question_text": "...",
        "covered": true|false,
        "covering_card_fronts": ["..."],
        "gap_description": "...|null"}
     ],
     "exam_coverage_pct": 0.85}
  ]}

  Output: gap_matrix.json strukturiert per Klausur, per Frage. Jeder Gap ist atomic + actionable.

  Kosten: 700k input + 50k output ≈ $0.45

  ---
  Phase 3 — Surgeon (LLM-driven, single mega-call)

  Eingabe:
  - gap_matrix.json (alle Lücken)
  - source_corpus.json als materialisierten Volltext (~500k Tokens für GTI)
  - Aktuelles Deck card_database.json als Front-only-Index (zur Vermeidung von neu-erfundenen Duplikaten
  innerhalb des Surgeon-Outputs)

  Prompt:

  For each gap in the gap matrix, generate 1-3 Anki cards that fill the gap.
  You MUST cite the source_corpus passage from which each card is derived
  (quote ≥10 chars verbatim). If no source supports the gap, mark the gap
  as "unsourced" and skip card generation. Do NOT generate cards whose front
  is semantically equivalent to any front already in the existing deck.

  Output JSON:
  {"new_cards": [
    {"front": "...", "back": "...",
     "source_quote": "verbatim from source_corpus",
     "source_path": "...",
     "addresses_gap_id": "..."}
  ], "unsourced_gaps": ["gap_id_1", ...]}

  Output: generated_cards.json, jede Karte mit Quellen-Zitat (Halluzinations-Bremse).

  Kosten: 500k source + 50k matrix + 30k output ≈ $0.31

  ---
  Phase 4 — Re-Integrate (existing pipeline, data-manipulation)

  generated_cards.json wandert via --integrate in den SSOT (mit semantic-dedup gegen bestehende Karten), dann
  --dedup --apply (3-pass cross-validation, mit dem in dieser Session implementierten Code), dann --export.
  Reuses alles bereits Gebaute.

  Kosten: ~$0.30

  ---
  Phase 5 — Examiner (--validate, LLM-driven, optional)

  Pro Klausur ein LLM-Call (Granularität für Audit-Trail):
  - Eingabe: Klausur-Text + Deck (Fronts+Backs als "Lernmaterial")
  - Aufgabe: LLM löst die Klausur, ausschließlich unter Verwendung des Decks. Pro Frage: Antwort, verwendete
  Karten-IDs, Confidence, eventuell ungelöste Lücken.

  Prompt-Pattern (per-Klausur):

  You are taking this exam. Your only allowed reference is the Anki deck below
  (no outside knowledge). For each task: (1) attempt an answer, (2) cite the
  card(s) you used, (3) report confidence, (4) if you cannot answer because the
  deck lacks specific information, describe what's missing.

  EXAM:
  [full text]

  DECK (your only allowed reference):
  [front+back of each card]

  Output JSON:
  {"exam_path": "...",
   "answers": [
     {"task_id": "...", "answer": "...",
      "cited_cards": [front_strings],
      "confidence": "HIGH|MEDIUM|LOW",
      "deck_gap": "...|null"}
   ],
   "estimated_pass": true|false,
   "score_estimate": 0.0-1.0}

  Output: exam_results.json per-Klausur + aggregierter verdict.json.

  Loop-Bedingung: Wenn verdict.json.aggregate_pass_rate < 0.8 UND iteration < 2 → identifizierte deck_gaps
  werden nach gap_matrix.json zurückgespeist und Phase 3+4 läuft erneut. Hartes Cap auf 2 Iterationen.

  Kosten: 64 × (12k input + 2k output) ≈ 770k input + 130k output ≈ $0.65 pro Sweep, max. 2 Sweeps = $1.30

  ---
  Cost-Recap — Gemini 3 Flash bei $0.50/$2.00

  ┌─────────────────────────────────────┬─────────────────────┬───────────────────────────────────────────┐
  │                Phase                │        Wann         │                Kosten/Run                 │
  ├─────────────────────────────────────┼─────────────────────┼───────────────────────────────────────────┤
  │ 1 (Lazy ohne Ingest)                │ jeder Run           │ ~$0.10 (nur OCR, kein ingest mehr in      │
  │                                     │                     │ dieser Phase)                             │
  ├─────────────────────────────────────┼─────────────────────┼───────────────────────────────────────────┤
  │ 1.5a Klassifikation (LLM)           │ jeder Run           │ ~$0.24                                    │
  ├─────────────────────────────────────┼─────────────────────┼───────────────────────────────────────────┤
  │ 1.5b Re-Klassifikation (LLM,        │ bei MEDIUM/LOW      │ ≤ $0.10                                   │
  │ optional)                           │                     │                                           │
  ├─────────────────────────────────────┼─────────────────────┼───────────────────────────────────────────┤
  │ 1.5c Materialization (data-manip)   │ jeder Run           │ $0                                        │
  ├─────────────────────────────────────┼─────────────────────┼───────────────────────────────────────────┤
  │ 1.6 Re-Lazy-Build (LLM              │ jeder Run           │ ~$0.50                                    │
  │ ingest+integrate)                   │                     │                                           │
  ├─────────────────────────────────────┼─────────────────────┼───────────────────────────────────────────┤
  │ 2 Audit (LLM mega-call)             │ wenn test_corpus ≠  │ ~$0.45                                    │
  │                                     │ ∅                   │                                           │
  ├─────────────────────────────────────┼─────────────────────┼───────────────────────────────────────────┤
  │ 3 Surgeon (LLM mega-call)           │ wenn gaps > 0       │ ~$0.31                                    │
  ├─────────────────────────────────────┼─────────────────────┼───────────────────────────────────────────┤
  │ 4 Re-Integrate (existing)           │ jeder Run mit       │ ~$0.30                                    │
  │                                     │ Phase-3             │                                           │
  ├─────────────────────────────────────┼─────────────────────┼───────────────────────────────────────────┤
  │ 5 Examiner (--validate, LLM)        │ optional, max 2     │ ~$1.30                                    │
  │                                     │ Sweeps              │                                           │
  └─────────────────────────────────────┴─────────────────────┴───────────────────────────────────────────┘

  Total --super-lazy: ~$2.00
  Total --super-lazy --validate: ~$3.30

  ---
  Disziplin-Übersicht: was ist im Repo erlaubt

  ┌──────────────────────────────────────────────────────────────────┬────────────────────────────────────┐
  │                               Was                                │          Im Code erlaubt?          │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ Hardcoded Token-Catalog für Rollen ({"klausur","exam"})          │ ❌ Nein                            │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ Hardcoded Topic-Regex für Coverage (r"pumping[-_ ]lemma")        │ ❌ Nein                            │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ Hardcoded Sprach-Annahmen (if doc.lang == "de": ...)             │ ❌ Nein                            │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ Hardcoded Filename-Pattern-Matching für Doc-Rollen               │ ❌ Nein                            │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ LLM-Prompt mit Beschreibung des Rollen-Vokabulars                │ ✅ Ja (das ist Spec, nicht         │
  │                                                                  │ Heuristik)                         │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ LLM-Prompt der das Modell fragt, ob es Korpus-Patterns sieht     │ ✅ Ja (Output ist Run-Artefakt)    │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ Run-Dir-Datei mit korpus-spezifischen Patterns die das LLM       │ ✅ Ja (corpus_observations)        │
  │ beobachtet hat                                                   │                                    │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ JSON-Joins über LLM-vergebene Schlüssel                          │ ✅ Ja (data-manipulation)          │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ Filter/Projection über LLM-vergebene Confidence                  │ ✅ Ja (data-manipulation)          │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ LLM-driven Chunking für überlange Korpora                        │ ✅ Ja (LLM-set Heuristik)          │
  └──────────────────────────────────────────────────────────────────┴────────────────────────────────────┘

  ---
  Offene Punkte vor Implementation

  1. Phase 1 vor oder nach 1.5? — Ich hab oben Phase 1 (OCR) vor 1.5 platziert, weil 1.5b den OCR-Text
  braucht. Phase-1-Ingest+Integrate aber NACH 1.5 (in Phase 1.6), damit Klausuren nicht versehentlich zu
  Karten werden. Sonst gleichbleibend.
  2. exercise als Test-Quelle? — meine Default-Empfehlung: als source-Material verwenden, nicht als Test.
  Optional --exercises-as-tests Flag falls User strenges Audit will.
  3. --validate Loop-Cap auf 2 — hart, kein Konfig-Override. Bestätige oder weiche das auf.

  Bestätige diese drei Punkte (oder korrigiere), dann implementiere ich Phase 1.5 als ersten committbaren
  │ hat                                            │
  ├──────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┤
  │ JSON-Joins über LLM-vergebene Schlüssel        ✅ Ja (data-manipulation)            │
  ├──────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┤
  │ Filter/Projection über LLM-vergebene Confidence✅ Ja (data-manipulation)            │
  ├──────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┤
  │ LLM-driven Chunking für überlange Korpora      ✅ Ja (LLM-set Heuristik)            │
  └──────────────────────────────────────────────────────────────────────────┴──────────────────────────────────────┘

  ---
  Offene Punkte vor Implementation

  1. Phase 1 vor oder nach 1.5? — Ich hab oben Phas(OCR) vor 1.5 platziert, weil 1.5b den OCR-Text braucht.
  Phase-1-Ingest+Integrate aber NACH 1.5 (in Phase 1.6), damit Klausuren nicht versehentlich zu Karten werden. Sonst
  gleichbleibend.
  2. exercise als Test-Quelle? — meine Default-Empfehlung: als source-Material verwenden, nicht als Test. Optional
  --exercises-as-tests Flag falls User strenges Audit will.
  3. --validate Loop-Cap auf 2 — hart, kein Konfig-Override. Bestätige oder weiche das auf.

  Bestätige diese drei Punkte (oder korrigiere), dann implementiere ich Phase 1.5 als ersten committbaren Baustein. Sie
     │
                               ▼
                            │
     │
     --validate?  ─────────────┬────────────────────
  ─────────────────────────►│
     │
                               ▼
                            ▼
     │
                  ┌─────────────────────────────────
  ─────────────────────────────────────┐
     │
                  │ Phase 5 (optional): γ-Examiner
                                       │
     │
                  │  Pro Klausur: LLM nimmt das Deck
   als einziges Hilfsmittel und        │
     │
                  │  „beantwortet" die Klausur.
  Output: per-Frage Pass/Fail + zitierte   │
         │
                  │  Karten + identifizierte
  Restlücken.                                 │
            │
                  │  Pass-Rate < threshold? → Phase
  3 nochmal mit Restlücken            │
    │
                  │  → exam_results.json +
  verdict.json                                  │
              │
                  └─────────────────────────────────
  ─────────────────────────────────────┘

  ---
  Phase 1.5 — Document Role Discovery (detaillierte
  Strategie)

  Eingabe

  Aus Phase 1 vorhanden: alle PDF-Dateien des
  Projekts plus deren OCR'd .txt-Versionen. Dazu
  File-Metadata (Pfad, Größe, mtime),
  Verzeichnis-Tokens
  (Kursmaterial/Skript_ws_25/skript-1.pdf → tokens
  [Kursmaterial, Skript_ws_25]), und
  PDF-Header-Metadata wenn vorhanden.

  Ausgabe-Artefakte

  role_map.json — Rolle pro Dokument

  {
    "schema_version": 1,
    "documents": [
      {
        "path":
  "Kursmaterial/Skript_ws_25/skript-1.pdf",
        "role": "script",
        "subrole": null,
        "confidence": "HIGH",
        "decided_by": "deterministic",
        "rationale": "Filename token 'skript' +
  first-page contains 'Vorlesung'"
      },
      {
        "path":
  "altklausuren_und_protokolle/.../klausur23ss.pdf",
        "role": "exam",
        "subrole": "main",
        "confidence": "HIGH",
        "decided_by": "deterministic",
        "rationale": "Filename token 'klausur' +
  structural cue: scoring table on cover page"
      },
      {
        "path": ".../klausur23ss_musterlösung.pdf",
        "role": "solution",
        "subrole": null,
        "paired_with":
  "altklausuren_und_protokolle/.../klausur23ss.pdf",
        "confidence": "HIGH",
        "decided_by": "deterministic+pairing",
        "rationale": "filename suffix
  '_musterlösung' + prefix matches existing exam"
      },
      {
        "path": ".../Hausuebung01.pdf",
        "role": "exercise",
        "subrole": "graded_homework",
        "confidence": "MEDIUM",
        "decided_by": "llm",
        "rationale": "Tokens 'hausuebung' ambiguous;
   LLM identified problem-set structure plus
  point-table → exercise sheet"
      }
    ]
  }

  Rollenkatalog (festes Vokabular):

  role: script
  Bedeutung: Vorlesungsskript / Folien — primäre
    Karten-Quelle
  Phase-2-Zugehörigkeit: source_corpus
  ────────────────────────────────────────
  role: exam
  Bedeutung: Geprüfte Klausur — Test-Bench für β/γ
  Phase-2-Zugehörigkeit: test_corpus
  ────────────────────────────────────────
  role: exercise
  Bedeutung: Übungsblatt / Tutorium / Hausübung —
    Sekundärquelle UND klausurnahe Aufgaben
  Phase-2-Zugehörigkeit: source_corpus + (optional)
    test_corpus
  ────────────────────────────────────────
  role: solution
  Bedeutung: Musterlösung zu exam oder exercise —
    Antwort-Material
  Phase-2-Zugehörigkeit: reference_corpus
  ────────────────────────────────────────
  role: notes
  Bedeutung: Mitschriften / Protokolle / Notizen —
    schwächere Quelle
  Phase-2-Zugehörigkeit: source_corpus
  ────────────────────────────────────────
  role: auxiliary
  Bedeutung: Formelsammlung, Glossar, README,
    Cheat-Sheet
  Phase-2-Zugehörigkeit: source_corpus
  (low-priority)
  ────────────────────────────────────────
  role: unknown
  Bedeutung: Konnte nicht zugeordnet werden — Output

    an User
  Phase-2-Zugehörigkeit: escalation

  subrole ist optional, freitextlich, nur
  informativ. Z.B. main, repetitorium, kurzklausur,
  mock, graded_homework.

  pair_map.json — Dokumenten-Pärchen

  {
    "schema_version": 1,
    "pairs": [
      {"primary": "klausur23ss.pdf", "secondary":
  "klausur23ss_musterlösung.pdf",
       "relation": "exam_with_solution",
  "confidence": "HIGH"},
      {"primary": "Uebungsblatt03.pdf", "secondary":
   "Uebungsblatt03_loesung.pdf",
       "relation": "exercise_with_solution",
  "confidence": "HIGH"}
    ]
  }

  Wichtig wegen §2.4 der KLAUSUR_REVIEW.md-Logik:
  wenn beide existieren, ist die Solution-Version
  eine qualitativ bessere Quelle für
  Phase-2B-Auditor (sie enthält Aufgaben und
  Antworten in einem Dokument). Phase-2B nimmt das
  Solution-Dokument statt der unlabeled-Version.

  test_corpus.json und source_corpus.json —
  Materialized Views

  Aggregierte Listen, präfilterung der role_map:

  // test_corpus.json
  {
    "documents": ["klausur23ss_musterlösung.pdf",
  "klausur24ss_rep_loesungshinweise.pdf",
                  "klausur19ws.pdf", ...],
    "total": 64,
    "preferred_pairing_used": true
  }

  // source_corpus.json
  {
    "documents_by_role": {
      "script": ["skript-1.pdf"],
      "exercise": ["Uebungsblatt01.pdf", ...,
  "Hausuebung01.pdf", ...],
      "notes": ["mitschrift_tutorium01.pdf", ...]
    },
    "weights": {"script": 1.0, "exercise": 0.8,
  "notes": 0.5}
  }

  Sub-Phasen

  1.5a — Deterministischer Pre-Filter (kostenlos,
  schnell)

  Eingabe: Filename, Verzeichnis-Pfad, PDF-Header
  (Title, Author).

  Multi-language Token-Catalog (additiv pflegbar):

  exam       ← klausur, exam, prüfung, pruefung, kk,
   kurzklausur
  exercise   ← übung, uebung, exercise, hausübung,
  hausuebung, tutorium, tutorial,
               aufgabenblatt, übungsblatt,
  uebungsblatt, hu, ü
  solution   ← lösung, loesung, musterlösung,
  musterloesung, loesungshinweise,
               solution, sol, answer, solutions
  script     ← skript, script, vorlesung, lecture,
  slides, folien, lecturenotes
  notes      ← mitschrift, notes, protokoll,
  transcript, summary

  Algorithmus:
  1. Tokenize path: split auf /, _, -, ., lowercase
  2. Match gegen catalog → tentative role +
  confidence
  3. Spezialregel Pairing: wenn ein Doc eine
  Solution-Token hat UND ein Doc mit dem gleichen
  non-solution-Stem existiert → markiere als pair
  4. Spezialregel Suffix-Stripping:
  klausur23ss_musterlösung → stem klausur23ss, role
  candidate solution, pairing target klausur23ss.pdf
   falls vorhanden

  Confidence-Logik:
  - HIGH: ≥1 Token aus dem Catalog matcht und keine
  widersprüchlichen Signale
  - MEDIUM: 1 Token aber strukturell unklar (z.B.
  nur das Wort "übung" und sonst nix)
  - LOW: kein Catalog-Match, Filename ist generisch
  ("Document1.pdf", "scan_2024.pdf")

  Output: role_map_draft.json mit
  Confidence-Verteilung; HIGH-Entries gehen direkt
  in Phase 1.5c, MEDIUM und LOW werden an Phase 1.5b
   weitergereicht.

  1.5b — LLM-Verifikation (kostenpflichtig, präzise)

  Nur für MEDIUM- und LOW-Confidence-Dokumente und
  für stichprobenartige Validierung von HIGH-Entries
   (~5%).

  Single mega-call (1M-Context-fähig): Sende für
  jedes ungeklärte Dokument die ersten ~2 Seiten
  OCR-Text + Filename + Pfad-Tokens. Prompt:

  Du klassifizierst Lehrmaterial-Dokumente nach
  ihrer didaktischen Rolle.

  ROLLEN-VOKABULAR:
  - script:     Vorlesungsskript, Folien —
  Primärquelle für Lerninhalt
  - exam:       Geprüfte Klausur (graded summative
  assessment)
  - exercise:   Übungsblatt, Hausübung,
  Tutorium-Aufgaben
  - solution:   Musterlösung / Lösungshinweise zu
  exam oder exercise
  - notes:      Mitschriften, Protokolle (sekundäre,
   oft inoffizielle Quelle)
  - auxiliary:  Formelsammlung, Glossar, README,
  Spickzettel
  - unknown:    Lässt sich nicht zuordnen

  REGELN:
  - Eine Klausur hat typisch: Punktetabelle,
  Aufgabe-X-Format, Zeitlimit-Hinweis,
    Identifikations-Felder.
  - Eine Musterlösung hat: zugehörige Aufgaben +
  ausformulierte Antworten.
  - Übungsblätter haben: nummerierte Aufgaben, oft
  "Abgabe: <Datum>".
  - Skripte haben: Inhaltsverzeichnis,
  Kapitelstruktur, definitorischer Stil.

  EINGABE:
  [für jedes Dokument: path, filename, first 2 pages
   text]

  AUSGABE als JSON:
  {"classifications": [
    {"path": "...", "role": "<rolle>", "subrole":
  "<frei|null>",
     "confidence": "HIGH|MEDIUM|LOW", "rationale":
  "<1-2 Sätze>"}
  ]}

  Multi-language ist gratis: das Modell erkennt
  deutsche/englische/französische Begriffe ohne
  extra Konfiguration — genau das, was die
  Inhaltsagnostik fordert.

  1.5c — Pairing & Materialization

  Deterministisch, kein LLM nötig.

  Algorithmus (siehe README §2.4 Logik):
  1. Für jedes solution-Doc: extrahiere stem
  (klausur23ss_musterlösung → klausur23ss)
  2. Suche in role_map ein Dokument mit gleichem
  stem und Rolle exam oder exercise
  3. Wenn gefunden: erzeuge Eintrag in pair_map.json
   mit relation = exam_with_solution oder
  exercise_with_solution
  4. Wenn solution alleine steht ohne primary:
  behalte als standalone solution; dieses Doc wird
  in Phase 2B als eigene Klausur behandelt (typisch
  für WS17 Kurzklausuren wo nur Lösungs-PDFs
  vorliegen)
  5. Materialize test_corpus.json und
  source_corpus.json per Rollenfilter

  1.5d — Edge-Case-Handling und Eskalation

  Drei Eskalations-Pfade:

  Szenario: test_corpus ist leer
  Verhalten: Phase 2A/2B/3/5 werden übersprungen mit

    Warning. Pipeline degradiert zu reinem Build
    (Phase 1 + 4).
  ────────────────────────────────────────
  Szenario: Mehr als 5 Docs als unknown
  klassifiziert
  Verhalten: Pipeline pausiert vor Phase 2 mit
    Bericht; user muss role_map.json manuell
    editieren oder mit --super-lazy --skip-discovery

    skippen
  ────────────────────────────────────────
  Szenario: Pair-Conflict (3 Docs mit gleichem stem)
  Verhalten: Heuristik: kürzester Filename =
  primary,
    "_musterlösung" suffix = solution,
    "_loesungshinweise" = secondary solution.
    Konflikt protokollieren.
  ────────────────────────────────────────
  Szenario: Sprache nicht erkannt
  Verhalten: Kein Problem für 1.5b (LLM ist
    sprachagnostisch); nur 1.5a degradiert auf
    MEDIUM/LOW, was 1.5b einfach mehr arbeiten lässt
  ────────────────────────────────────────
  Szenario: Doc enthält alle Rollen-Signale (z.B.
    "klausurvorbereitung_uebung_loesung.pdf")
  Verhalten: LLM disambiguiert basierend auf Inhalt;

    Output mit subrole annotiert

  Audit & Resumability

  Wie bei --dedup:
  - Output in role_discovery_<timestamp>/
  - --from-phase 1.5b resumed direkt aus 1.5a-Output
  - role_map.json ist read-write: Studi kann
  manuelle Korrekturen einkippen, Phase 1.5c läuft
  danach idempotent
  - Metrics: discovery_summary.json mit Counter pro
  Rolle + Confidence-Verteilung

  Wie Phase 1.5 die nachfolgenden Phasen füttert

  Phase: 2A Cartographer-Lite
  Konsumiert: test_corpus.json
  Wofür: Token-Match jeder Test-Frage gegen
    Karten-Fronts
  ────────────────────────────────────────
  Phase: 2B LLM-Auditor
  Konsumiert: test_corpus.json (Test) +
    source_corpus.json (Quelle, gecached im
    Prompt-Prefix) + pair_map.json
    (Lösung-Bevorzugung)
  Wofür: Pro Klausur: LLM bekommt Klausurfragen +
    alle aktuellen Karten-Fronts → identifiziert
    echte Coverage-Lücken
  ────────────────────────────────────────
  Phase: 3 Surgeon
  Konsumiert: gap_matrix.json (aus 2B) +
    source_corpus.json (gewichtet:
    script>exercise>notes)
  Wofür: Generiert Karten, muss Source angeben aus
    der die Karte extrahiert wurde —
    Halluzinations-Bremse
  ────────────────────────────────────────
  Phase: 4 Re-Integrate
  Konsumiert: generated_cards.json
  Wofür: Existing pipeline, semantic dedup gegen
    aktuelles Deck
  ────────────────────────────────────────
  Phase: 5 Examiner (--validate)
  Konsumiert: test_corpus.json (gleicher Subkorpus
    wie 2B) + Final-Deck nach Phase 4
  Wofür: Operationaler Pass-Test: LLM löst Klausuren

    mit Deck als einzigem Hilfsmittel; Pass-Rate als

    Metrik

  ---
  Aktualisierte Kostenrechnung

  Phase: 1 (existing lazy mode)
  Kosten (Gemini 3 Flash $0.50/$2.00): ~$0.50
  Wann fällt es an: jedes Mal
  ────────────────────────────────────────
  Phase: 1.5a (deterministic)
  Kosten (Gemini 3 Flash $0.50/$2.00): $0.00
  Wann fällt es an: jedes Mal
  ────────────────────────────────────────
  Phase: 1.5b (LLM verify)
  Kosten (Gemini 3 Flash $0.50/$2.00): ~$0.10 (50k
    input + 5k output, single call)
  Wann fällt es an: nur wenn MEDIUM/LOW-Docs
    vorhanden
  ────────────────────────────────────────
  Phase: 1.5c (pairing)
  Kosten (Gemini 3 Flash $0.50/$2.00): $0.00
  Wann fällt es an: jedes Mal
  ────────────────────────────────────────
  Phase: 2A (Cartographer-Lite)
  Kosten (Gemini 3 Flash $0.50/$2.00): $0.00
  Wann fällt es an: nur wenn test_corpus ≠ ∅
  ────────────────────────────────────────
  Phase: 2B (Auditor)
  Kosten (Gemini 3 Flash $0.50/$2.00): ~$0.50–$2.00
    (skaliert mit residualen Lücken; 1M-Context
    erlaubt cached  source_corpus)
  Wann fällt es an: dito
  ────────────────────────────────────────
  Phase: 3 (Surgeon)
  Kosten (Gemini 3 Flash $0.50/$2.00): ~$0.20–$0.80
    (skaliert mit Lücken-Anzahl)
  Wann fällt es an: dito
  ────────────────────────────────────────
  Phase: 4 (existing integrate+dedup+export)
  Kosten (Gemini 3 Flash $0.50/$2.00): ~$0.30
  Wann fällt es an: jedes Mal
  ────────────────────────────────────────
  Phase: 5 (Examiner, optional via --validate)
  Kosten (Gemini 3 Flash $0.50/$2.00): ~$2.00–$3.50
  Wann fällt es an: nur wenn --validate

  Total --super-lazy ohne --validate:
  ~$1.10–$3.70/Run
  Total --super-lazy --validate: ~$3.10–$7.20/Run

  Vergleich zu vorherigen β-Schätzung ($5.20):
  Phase-2A-Pre-Filter und Caching des source_corpus
  im Prompt-Prefix senken Kosten signifikant. Die
  größte Variabilität kommt aus der Lücken-Menge:
  kleines Deck mit vielen Lücken → Surgeon teuer;
  reifes Deck mit wenigen Lücken → fast geschenkt.

  ---
  Offene Fragen vor Implementation

  1. role "exercise" — soll es als Test-Korpus
  zählen oder nur als Source? Argument pro Test:
  Übungsblätter sind klausurnah und bilden gute
  Ground-Truth. Argument contra: dann wird der
  Surgeon ihre Aufgaben in Karten umwandeln, die er
  dann gegen Übungs-Fragen testet → potenzielle
  Zirkularität. Mein Vorschlag: default Source-only,
   mit Flag --exercises-as-tests für strenges Audit.
  2. Phase 1.5 Position im Pipeline-Flow — sollte
  sie wirklich nach Phase 1 laufen oder sinnvoller
  vor? Argument für nach: Phase 1 hat schon OCR'd,
  also sind die .txt-Dateien für 1.5b verfügbar.
  Argument für vor: dann könnte Phase 1 selbst die
  Rolle nutzen (z.B. Klausuren nicht in den
  Card-Pool aufnehmen, was vermutlich richtiger ist
  als jetzt). Mein Vorschlag: Phase 1.5 läuft VOR
  Phase 1, Phase 1 wird angepasst sodass sie nur
  source_corpus ingestet, nicht test_corpus. Das
  räumt das Daten-Modell sauber auf.
  3. --validate als Loop oder Single-Shot? — wenn
  die Pass-Rate unter Schwelle liegt: nochmal Phase
  3+4 mit den neu identifizierten Lücken aus Phase
  5? Risk: Endlos-Schleife wenn das Modell die
  gleichen Lücken in jeder Runde wieder findet. Mein
   Vorschlag: max 2 Iterationen, danach hart
  abbrechen mit Warning.

  Bestätige (oder korrigiere) diese drei Punkte,
  dann implementiere ich Phase 1.5 als ersten
  Baustein. Sie ist eigenständig committbar und
  blockiert nicht — auch ohne β/γ ist ein sauberer
  role_map.json schon ein Wert für sich (z.B. um die
   existing --ingest-Logik zu verbessern, sodass
  Klausuren nicht mehr versehentlich als
  Karten-Quelle landen).

✻ Worked for 2m 55s

❯ passe deinen plan nochmal an. ich will keinen
  cartographer lite.(deterministic, no LLM) ist
  porblematisch bzgl universalisierungs approach
  des repos. Das schließt aber nicht aus, dass
  deterministische Heuristiken (Filename-Patterns,
    Verzeichnis-Tokens, Pdf-Metadaten) als günstige
   Pre-Filter genutzt werden — solange sie in einem
   klar
    getrennten Stage liegen - da stimme ich auch
  nicht richtig zu. pdf2anki soll keine guenstigen
  prefilter als dauerhafte heuristiken verwenden
  oder hardcoden. wenn heuristiken intra-korpus
  verwendet werden dann nur wenn sie von einem llm
  gesetzt werden. gib den angepassten plan
  vollstaendig aus. steelmanne meinen intent
  maximal und expliziere ihn als aufgabenstellung

● Steelmanned Intent

  Du erkennst eine Architektur-Hygiene-Frage, die
  ich zu locker behandelt habe: pdf2anki soll ein
  universelles Tool sein. Das heißt operational: ein
   Studi mit chinesischen Statistik-Skripten, ein
  französischer Biostudent, ein indischer
  Maschinenbau-Lehrling — alle sollten pdf2anki .
  benutzen können ohne dass das Tool
  kulturelle/linguistische/disziplinäre Annahmen
  mitbringt. Sobald irgendwo im Repo ein
  Token-Catalog {"klausur", "exam", "prüfung"} oder
  ein Topic-Match-Regex r"pumping[-_ ]lemma"
  einzieht, ist das Tool nicht mehr universell — es
  ist ein deutsches CS-Studi-Tool das in andere
  Kontexte schlecht generalisiert. Jede solche
  Heuristik ist eine embedded assumption, die in der
   Code-Review schwer auffällt aber in der nächsten
  Zielgruppe sofort bricht.

  Der saubere Pfad: das LLM ist die einzige
  semantische Schicht. pdf2anki ist Plumbing +
  LLM-Call-Orchestrierung + JSON-Manipulation. Wenn
  pro Korpus Heuristiken nötig sind, derived sie das
   LLM zur Laufzeit und legt sie in die
  Run-Artefakte — sie leben dort als beobachtete
  Eigenschaften des konkreten Korpus, nicht als
  hardcoded Code-Constants. Auch deterministische
  Stages bleiben erlaubt, aber nur wenn sie keine
  semantische Entscheidung treffen — z.B. JSON-Joins
   über bereits-vom-LLM-vergebene Schlüssel, Filter
  über LLM-vergebene Confidence-Levels,
  Materialization von Corpus-Views per Rolle. Das
  ist Plumbing, nicht Heuristik.

  Konsequenz: Phase 2A "Cartographer-Lite" fliegt
  komplett raus. Sie war eine Coverage-Heuristik mit
   eingebackener Topic-Ontologie, das ist exakt die
  Klasse Code die du nicht im Repo haben willst. Mit
   Gemini 3 Flash bei 1M Context und $0.50 / $2.00
  Pricing ist die Optimierung "spar dir den LLM-Call
   durch Regex-Match" nicht mehr nötig — die
  Mega-Call-Pattern aus dem --dedup-Detection-Stage
  skaliert direkt auf alle Audit-Stages. Eine
  700k-Token-Klausur-Audit-Mega-Call kostet $0.40.
  Das ist günstiger als die Komplexität eines
  deterministischen Pre-Filters wert ist.

  Damit reduziert sich der Plan auf weniger Stages,
  jede klar als "LLM-driven" oder "pure
  data-manipulation" markiert, mit explizitem Verbot
   hardcoded Vokabulare oder Patterns im Repo.

  Aufgabenstellung

  Skizziere den finalen --super-lazy Plan
  vollständig neu mit folgender Disziplin:

  1. Keine hardcoded semantischen Heuristiken im
  pdf2anki-Repo. Kein Token-Catalog für Rollen, kein
   Topic-Regex, keine Domain-Ontologie. Wenn eine
  Heuristik für einen konkreten Korpus nützlich
  wäre, erzeugt sie das LLM zur Laufzeit und legt
  sie als Run-Artefakt ab.
  2. Phase 2A entfernt. Nur noch Phase 2
  (LLM-Auditor) mit einem oder wenigen Mega-Calls.
  3. Phase 1.5 wird LLM-First: keine
  deterministische Filename-Token-Vorprüfung. Single
   LLM mega-call klassifiziert alle Dokumente auf
  einen Schlag mit dem 1M-Context-Fenster. Pairing
  und Materialization sind danach pure
  JSON-Transformationen über LLM-Output.
  4. Für jede Stage explizit annotieren:
  "LLM-driven" (semantische Entscheidung) oder
  "data-manipulation" (kein Wissen, nur
  Umstrukturierung). Mischformen sind nicht erlaubt.
  5. Cost-Recompute mit dem Mega-Call-Pattern.
  6. Edge-Cases dokumentieren ohne deterministische
  Sprach- oder Domain-Annahmen.

  ---
  Final Architecture — pdf2anki . --super-lazy
  [--validate]

                                    ┌───────────────
  ──────────────────────────────────┐
                                    │ Phase 1: Lazy
  Mode (existing)                   │
                                    │ DEFER
  ingest/integrate until role_map exists.   │
                                    │ This phase
  produces ONLY ocr'd .txt per pdf.    │
                                    └───────────────
  ─────────┬────────────────────────┘

           │

           ▼
                                    ┌───────────────
  ──────────────────────────────────┐
                                    │ Phase 1.5:
  Document Role Discovery [LLM-driven] │
                                    │ →
  role_map.json   pair_map.json                 │
                                    │ →
  test_corpus.json   source_corpus.json         │
                                    └───────────────
  ─────────┬────────────────────────┘

           │

           ▼
                                    ┌───────────────
  ──────────────────────────────────┐
                                    │ Phase 1.6:
  Resumed Lazy-Build [data-manipulation│
                                    │ + existing
  pipeline]                            │
                                    │ Ingest only
  documents in source_corpus.         │
                                    │ Existing
  --integrate (with semantic dedup)      │
                                    │ →
  card_database.json   collection_*.json        │
                                    └───────────────
  ─────────┬────────────────────────┘

           │
                                [test_corpus =
  ∅?]───────────┼────skip rest, warn user

           │

           ▼
                                    ┌───────────────
  ──────────────────────────────────┐
                                    │ Phase 2: Audit
   [LLM-driven, single mega-call]   │
                                    │ →
  gap_matrix.json                               │
                                    └───────────────
  ─────────┬────────────────────────┘

           │
                                              [no
  gaps?]─────┼────skip rest, exit ok

           │

           ▼
                                    ┌───────────────
  ──────────────────────────────────┐
                                    │ Phase 3:
  Surgeon [LLM-driven, single mega-call] │
                                    │ →
  generated_cards.json (with source citations)  │
                                    └───────────────
  ─────────┬────────────────────────┘

           │

           ▼
                                    ┌───────────────
  ──────────────────────────────────┐
                                    │ Phase 4:
  Re-Integrate [existing pipeline]       │
                                    │ --integrate +
  --dedup --apply + --export        │
                                    └───────────────
  ─────────┬────────────────────────┘

           │

  ────[--validate]───┐

           │   │

           ▼   ▼
                                    ┌───────────────
  ──────────────────────────────────┐
                                    │ Phase 5:
  Examiner [LLM-driven] (optional)       │
                                    │ Per-Exam
  simulation; pass-rate as metric        │
                                    │ pass-rate <
  threshold ∧ iter < 2  →  Phase 3    │
                                    │ →
  exam_results.json   verdict.json              │
                                    └───────────────
  ──────────────────────────────────┘

  Alle Phasen, die das Wort „LLM-driven" tragen,
  treffen semantische Entscheidungen — dort lebt das
   Wissen über Bedeutung. Alle Phasen, die
  „data-manipulation" tragen, nehmen LLM-Output als
  gegeben und transformieren ihn in Views, Joins,
  Filter. Mischformen sind verboten.

  ---
  Phase 1.5 — Document Role Discovery (revised)

  Was sich ändert ggü dem vorigen Plan

  Vorher: 1.5a deterministischer
  Filename-Token-Match
  Jetzt: gestrichen
  ────────────────────────────────────────
  Vorher: 1.5b LLM nur für residuale MEDIUM/LOW-Docs
  Jetzt: wird zu 1.5a, klassifiziert ALLE
  ────────────────────────────────────────
  Vorher: 1.5c Pairing per stem-Match
    (deterministisch, aber von LLM identifiziert)
  Jetzt: bleibt — pure JSON-Transformation über
    LLM-bestätigte Pärchen

  1.5a — LLM-Klassifikation (single mega-call)

  Eingabe (alles im 1M-Context):
  - Pfad jedes Dokuments
  - Erste ~3-5 Seiten OCR-Text jedes Dokuments
  (Budget dynamisch: total ≤ 800k Tokens)
  - Optional: PDF-Metadata (Title, Author) wenn
  vorhanden — aber kein Filename-Pattern-Matching

  Prompt-Skelett (vollständig generisch, kein
  institutional/Sprach-Bias):

  Analyze this corpus of educational documents.
  Classify each document by its
  didactic role using the role vocabulary below. The
   role of a document is its
  intended FUNCTION in a learning workflow, not its
  filename or title.

  Role vocabulary (open-ended, mutually exclusive
  within a single doc):
  - script:    Primary teaching material (textbook,
  lecture script, slides).
               Definitorial/expository style,
  structured by chapters or sections.
  - exam:      Summative assessment that was/will be
   graded. Time-limited, formal
               question format, typically with point
   distribution and identification
               fields.
  - exercise:  Practice problems, homework, tutorial
   assignments. Numbered tasks,
               often paired with submission
  deadline. May be graded or ungraded.
  - solution:  Reference answers paired with an exam
   or exercise. Contains both
               questions and worked-out solutions.
  - notes:     Secondary, often informal: personal
  transcripts, tutorial protocols,
               study summaries.
  - auxiliary: Supporting material: glossary,
  formula sheet, reading list, README.
  - unknown:   Insufficient context to classify.

  For each document, additionally report:
  - pairing: if this document references another
  document in the corpus as its
             companion (e.g., a solution paired with
   its exam), name the partner
             and the relation type.
  - confidence: HIGH / MEDIUM / LOW
  - rationale: 1-2 sentences referencing concrete
  textual or structural cues you
               observed (NOT the filename).

  CORPUS:
  [Doc A]
    path: ...
    first_pages: ...
  [Doc B]
    ...

  Output JSON:
  {"classifications": [
    {"path": "...", "role": "...", "subrole":
  "...|null",
     "pairing": {"partner_path": "...|null",
  "relation":
  "exam_with_solution|exercise_with_solution|null"},
     "confidence": "HIGH|MEDIUM|LOW",
     "rationale": "..."}
  ], "corpus_observations": "<freitext: was hat das
  modell ueber den korpus an strukturellen mustern
  beobachtet?>"}

  Wichtig: das corpus_observations Feld ist explizit
   ein freier Text-Output, in dem das Modell
  beobachtete Korpus-spezifische Patterns festhalten
   kann (z.B. "alle Dateien in Sortiert/ sind
  Klausuren" oder "Dateien mit Suffix _loesung sind
  Lösungen zu der gleichnamigen Klausur"). Das ist
  die einzige Stelle, an der der Plan
  korpus-spezifische Heuristiken duldet — sie sind
  LLM-derived, im Run-Artefakt persistiert, nicht im
   Code, und nur informativ.

  Kosten (~80 Docs × 5k Tokens Vorab-Sample + 20k
  Output): 400k input + 20k output ≈ $0.24

  1.5b — Re-Klassifikation für niedrigvertrauliche
  Dokumente

  Optional: für jedes Doc mit confidence ∈ {MEDIUM,
  LOW} — sende den vollen OCR-Text (statt nur die
  ersten Seiten) zurück ans LLM für eine zweite
  Klassifikation. Pure LLM-driven.

  Kosten (variabel; meist 0–10 Dokumente, ~$0.05
  maximal): ≤ $0.10

  1.5c — Pairing & Corpus-Materialization
  (data-manipulation, no semantic decision)

  Reine JSON-Transformation, kein LLM nötig:

  1. Aggregiere pairing-Felder aus 1.5a/b zu
  pair_map.json. Wenn ein Doc als Partner eines
  anderen referenziert wird, das aber nicht
  zurückreferenziert: einseitige Beziehung
  markieren, escalate wenn inconsistent.
  2. Projiziere role_map zu test_corpus.json: alle
  Docs mit role ∈ {exam}, plus standalone
  solution-Docs ohne Partner (das
  WS17-Kurzklausur-Szenario).
  3. Wenn ein Pair exam_with_solution existiert: in
  test_corpus.json wird die Solution-Version
  eingetragen (sie enthält Aufgaben + Antworten).
  4. Projiziere role_map zu source_corpus.json: alle
   Docs mit role ∈ {script, exercise, notes,
  auxiliary} plus Solutions die in test_corpus schon
   stehen (für Antwort-Referenzen).
  5. Optionaler User-Eingriff: role_map.json ist
  read-write; Re-run von 1.5c ist idempotent über
  manuelle Korrekturen.

  Diese Stage trifft keine semantische Entscheidung.
   Sie joint nur LLM-Output mit JSON-Schema.
  Erlaubt, weil Plumbing.

  Edge-Cases (alle ohne hardcoded Annahmen)

  Szenario: test_corpus = ∅
  Verhalten: Phasen 2/3/5 werden übersprungen,
    Pipeline degradiert zu Phase-1+4-Build mit
    Warning.
  ────────────────────────────────────────
  Szenario: > 5 Docs als unknown
  Verhalten: Pipeline pausiert, schreibt Bericht mit

    den unknowns + Re-Klassifikations-Hinweis, User
    kann manuell editieren oder --accept-unknowns
    setzen.
  ────────────────────────────────────────
  Szenario: Pair-Konflikt (3 Docs referenzieren sich

    gegenseitig)
  Verhalten: Der LLM-Output ist die Quelle der
    Wahrheit — wenn das LLM keine eindeutige
    Pairing-Aussage macht, behandelt 1.5c alle 3 als

    standalone. Audit-Eintrag in
  pair_conflicts.json.
  ────────────────────────────────────────
  Szenario: Mehrsprachigkeit
  Verhalten: Kein Spezialcode nötig; LLM
    klassifiziert sprachagnostisch. Wenn der Korpus
    ein Mix ist, wird das im
    corpus_observations-Freitext landen.
  ────────────────────────────────────────
  Szenario: Filename völlig generisch
  (Document1.pdf)
  Verhalten: LLM klassifiziert auf Basis von Inhalt
    allein; confidence darf MEDIUM/LOW sein.
  ────────────────────────────────────────
  Szenario: Korpus zu groß für 1M-Call (>2000 Docs)
  Verhalten: LLM-driven Chunking: erst kleine
    Stichprobe an LLM mit Frage "extract a
    corpus-classification scheme", dann Chunks gegen

    das LLM-erzeugte Schema. Heuristik wird LLM-set,

    nicht hardcoded.

  ---
  Phase 1.6 — Resumed Lazy-Build (data-manipulation
  + existing pipeline)

  Die existing lazy_runner wird so angepasst, dass
  sie nur Docs aus source_corpus.json ingestet.
  Klausuren landen nicht mehr im Card-Pool — heute
  schon ein latenter Bug, der sich aber durch die
  fehlende Rolle-Trennung tarnt.

  ┌───────────┬─────────────┬────────────────────┐
  │ Sub-Stage │ LLM-driven? │    Was passiert    │
  ├───────────┼─────────────┼────────────────────┤
  │           │             │ Filter PDFs nach   │
  │ 1.6a      │ data-manip  │ source_corpus;     │
  │           │             │ Phase-1-OCR-Output │
  │           │             │  wiederverwenden   │
  ├───────────┼─────────────┼────────────────────┤
  │ 1.6b      │ LLM-driven  │ workflow --ingest  │
  │           │ (existing)  │ auf source-Set     │
  ├───────────┼─────────────┼────────────────────┤
  │           │ LLM-driven  │ workflow           │
  │ 1.6c      │ (existing)  │ --integrate mit    │
  │           │             │ semantic-dedup     │
  ├───────────┼─────────────┼────────────────────┤
  │ 1.6d      │ data-manip  │ workflow --export  │
  │           │ (existing)  │                    │
  └───────────┴─────────────┴────────────────────┘

  Kostet ~$0.50 (entspricht heutigem Phase 1).

  ---
  Phase 2 — Audit (LLM-driven, single mega-call)

  Eingabe (im 1M-Context):
  - Vollständiger OCR-Text aller Klausuren aus
  test_corpus.json (~640k Tokens für 64 Klausuren)
  - Alle Karten-Fronts aus card_database.json (~18k
  Tokens)
  - Optional Karten-Backs (~100k Tokens) — falls
  Pass-Schätzung gemeinsam mit Audit gemacht werden
  soll, sonst weglassen

  Prompt:

  For each exam in the test corpus, identify the
  questions/tasks it poses.
  Then, for each question, decide whether the
  current Anki deck contains a card
  that would let a student answer it. If yes: cite
  the card front. If no:
  describe the missing concept/skill in 1 sentence.

  Output JSON:
  {"per_exam": [
    {"exam_path": "...",
     "questions": [
       {"question_id": "task_1a",
        "question_text": "...",
        "covered": true|false,
        "covering_card_fronts": ["..."],
        "gap_description": "...|null"}
     ],
     "exam_coverage_pct": 0.85}
  ]}

  Output: gap_matrix.json strukturiert per Klausur,
  per Frage. Jeder Gap ist atomic + actionable.

  Kosten: 700k input + 50k output ≈ $0.45

  ---
  Phase 3 — Surgeon (LLM-driven, single mega-call)

  Eingabe:
  - gap_matrix.json (alle Lücken)
  - source_corpus.json als materialisierten Volltext
   (~500k Tokens für GTI)
  - Aktuelles Deck card_database.json als
  Front-only-Index (zur Vermeidung von
  neu-erfundenen Duplikaten innerhalb des
  Surgeon-Outputs)

  Prompt:

  For each gap in the gap matrix, generate 1-3 Anki
  cards that fill the gap.
  You MUST cite the source_corpus passage from which
   each card is derived
  (quote ≥10 chars verbatim). If no source supports
  the gap, mark the gap
  as "unsourced" and skip card generation. Do NOT
  generate cards whose front
  is semantically equivalent to any front already in
   the existing deck.

  Output JSON:
  {"new_cards": [
    {"front": "...", "back": "...",
     "source_quote": "verbatim from source_corpus",
     "source_path": "...",
     "addresses_gap_id": "..."}
  ], "unsourced_gaps": ["gap_id_1", ...]}

  Output: generated_cards.json, jede Karte mit
  Quellen-Zitat (Halluzinations-Bremse).

  Kosten: 500k source + 50k matrix + 30k output ≈
  $0.31

  ---
  Phase 4 — Re-Integrate (existing pipeline,
  data-manipulation)

  generated_cards.json wandert via --integrate in
  den SSOT (mit semantic-dedup gegen bestehende
  Karten), dann --dedup --apply (3-pass
  cross-validation, mit dem in dieser Session
  implementierten Code), dann --export. Reuses alles
   bereits Gebaute.

  Kosten: ~$0.30

  ---
  Phase 5 — Examiner (--validate, LLM-driven,
  optional)

  Pro Klausur ein LLM-Call (Granularität für
  Audit-Trail):
  - Eingabe: Klausur-Text + Deck (Fronts+Backs als
  "Lernmaterial")
  - Aufgabe: LLM löst die Klausur, ausschließlich
  unter Verwendung des Decks. Pro Frage: Antwort,
  verwendete Karten-IDs, Confidence, eventuell
  ungelöste Lücken.

  Prompt-Pattern (per-Klausur):

  You are taking this exam. Your only allowed
  reference is the Anki deck below
  (no outside knowledge). For each task: (1) attempt
   an answer, (2) cite the
  card(s) you used, (3) report confidence, (4) if
  you cannot answer because the
  deck lacks specific information, describe what's
  missing.

  EXAM:
  [full text]

  DECK (your only allowed reference):
  [front+back of each card]

  Output JSON:
  {"exam_path": "...",
   "answers": [
     {"task_id": "...", "answer": "...",
      "cited_cards": [front_strings],
      "confidence": "HIGH|MEDIUM|LOW",
      "deck_gap": "...|null"}
   ],
   "estimated_pass": true|false,
   "score_estimate": 0.0-1.0}

  Output: exam_results.json per-Klausur +
  aggregierter verdict.json.

  Loop-Bedingung: Wenn
  verdict.json.aggregate_pass_rate < 0.8 UND
  iteration < 2 → identifizierte deck_gaps werden
  nach gap_matrix.json zurückgespeist und Phase 3+4
  läuft erneut. Hartes Cap auf 2 Iterationen.

  Kosten: 64 × (12k input + 2k output) ≈ 770k input
  + 130k output ≈ $0.65 pro Sweep, max. 2 Sweeps =
  $1.30

  ---
  Cost-Recap — Gemini 3 Flash bei $0.50/$2.00

  Phase: 1 (Lazy ohne Ingest)
  Wann: jeder Run
  Kosten/Run: ~$0.10 (nur OCR, kein ingest mehr in
    dieser Phase)
  ────────────────────────────────────────
  Phase: 1.5a Klassifikation (LLM)
  Wann: jeder Run
  Kosten/Run: ~$0.24
  ────────────────────────────────────────
  Phase: 1.5b Re-Klassifikation (LLM, optional)
  Wann: bei MEDIUM/LOW
  Kosten/Run: ≤ $0.10
  ────────────────────────────────────────
  Phase: 1.5c Materialization (data-manip)
  Wann: jeder Run
  Kosten/Run: $0
  ────────────────────────────────────────
  Phase: 1.6 Re-Lazy-Build (LLM ingest+integrate)
  Wann: jeder Run
  Kosten/Run: ~$0.50
  ────────────────────────────────────────
  Phase: 2 Audit (LLM mega-call)
  Wann: wenn test_corpus ≠ ∅
  Kosten/Run: ~$0.45
  ────────────────────────────────────────
  Phase: 3 Surgeon (LLM mega-call)
  Wann: wenn gaps > 0
  Kosten/Run: ~$0.31
  ────────────────────────────────────────
  Phase: 4 Re-Integrate (existing)
  Wann: jeder Run mit Phase-3
  Kosten/Run: ~$0.30
  ────────────────────────────────────────
  Phase: 5 Examiner (--validate, LLM)
  Wann: optional, max 2 Sweeps
  Kosten/Run: ~$1.30

  Total --super-lazy: ~$2.00
  Total --super-lazy --validate: ~$3.30

  ---
  Disziplin-Übersicht: was ist im Repo erlaubt

  ┌────────────────────────┬────────────────────┐
  │          Was           │  Im Code erlaubt?  │
  ├────────────────────────┼────────────────────┤
  │ Hardcoded              │                    │
  │ Token-Catalog für      │ ❌ Nein            │
  │ Rollen                 │                    │
  │ ({"klausur","exam"})   │                    │
  ├────────────────────────┼────────────────────┤
  │ Hardcoded Topic-Regex  │                    │
  │ für Coverage           │ ❌ Nein            │
  │ (r"pumping[-_ ]lemma") │                    │
  ├────────────────────────┼────────────────────┤
  │ Hardcoded              │                    │
  │ Sprach-Annahmen (if    │ ❌ Nein            │
  │ doc.lang == "de": ...) │                    │
  ├────────────────────────┼────────────────────┤
  │ Hardcoded Filename-Pat │                    │
  │ tern-Matching für      │ ❌ Nein            │
  │ Doc-Rollen             │                    │
  ├────────────────────────┼────────────────────┤
  │ LLM-Prompt mit         │ ✅ Ja (das ist     │
  │ Beschreibung des       │ Spec, nicht        │
  │ Rollen-Vokabulars      │ Heuristik)         │
  ├────────────────────────┼────────────────────┤
  │ LLM-Prompt der das     │ ✅ Ja (Output ist  │
  │ Modell fragt, ob es    │ Run-Artefakt)      │
  │ Korpus-Patterns sieht  │                    │
  ├────────────────────────┼────────────────────┤
  │ Run-Dir-Datei mit      │                    │
  │ korpus-spezifischen    │ ✅ Ja (corpus_obse │
  │ Patterns die das LLM   │ rvations)          │
  │ beobachtet hat         │                    │
  ├────────────────────────┼────────────────────┤
  │ JSON-Joins über        │ ✅ Ja (data-manipu │
  │ LLM-vergebene          │ lation)            │
  │ Schlüssel              │                    │
  ├────────────────────────┼────────────────────┤
  │ Filter/Projection über │ ✅ Ja (data-manipu │
  │  LLM-vergebene         │ lation)            │
  │ Confidence             │                    │
  ├────────────────────────┼────────────────────┤
  │ LLM-driven Chunking    │ ✅ Ja (LLM-set     │
  │ für überlange Korpora  │ Heuristik)         │
  └────────────────────────┴────────────────────┘

  ---
  Offene Punkte vor Implementation

  1. Phase 1 vor oder nach 1.5? — Ich hab oben Phase
   1 (OCR) vor 1.5 platziert, weil 1.5b den OCR-Text
  │ hat                                                                      │                                      │
  ├──────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┤
  │ JSON-Joins über LLM-vergebene Schlüssel                                  │ ✅ Ja (data-manipulation)            │
  ├──────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────┤
  │ Filter/Projection über LLM-vergebene Confidence                          │ ✅ Ja (data-manipulation)            │
  ├─────────────────────────────────────┼─────────────────────┼───────────────────────────────────────────┤
  │ 4 Re-Integrate (existing)           │ jeder Run mit       │ ~$0.30                                    │
  │                                     │ Phase-3             │                                           │
  ├─────────────────────────────────────┼─────────────────────┼───────────────────────────────────────────┤
  │ 5 Examiner (--validate, LLM)        │ optional, max 2     │ ~$1.30                                    │
  │                                     │ Sweeps              │                                           │
  └─────────────────────────────────────┴─────────────────────┴───────────────────────────────────────────┘

  Total --super-lazy: ~$2.00
  Total --super-lazy --validate: ~$3.30

  ---
  Disziplin-Übersicht: was ist im Repo erlaubt

  ┌──────────────────────────────────────────────────────────────────┬────────────────────────────────────┐
  │                               Was                                │          Im Code erlaubt?          │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ Hardcoded Token-Catalog für Rollen ({"klausur","exam"})          │ ❌ Nein                            │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ Hardcoded Topic-Regex für Coverage (r"pumping[-_ ]lemma")        │ ❌ Nein                            │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ Hardcoded Sprach-Annahmen (if doc.lang == "de": ...)             │ ❌ Nein                            │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ Hardcoded Filename-Pattern-Matching für Doc-Rollen               │ ❌ Nein                            │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ LLM-Prompt mit Beschreibung des Rollen-Vokabulars                │ ✅ Ja (das ist Spec, nicht         │
  │                                                                  │ Heuristik)                         │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ LLM-Prompt der das Modell fragt, ob es Korpus-Patterns sieht     │ ✅ Ja (Output ist Run-Artefakt)    │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ Run-Dir-Datei mit korpus-spezifischen Patterns die das LLM       │ ✅ Ja (corpus_observations)        │
  │ beobachtet hat                                                   │                                    │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ JSON-Joins über LLM-vergebene Schlüssel                          │ ✅ Ja (data-manipulation)          │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ Filter/Projection über LLM-vergebene Confidence                  │ ✅ Ja (data-manipulation)          │
  ├──────────────────────────────────────────────────────────────────┼────────────────────────────────────┤
  │ LLM-driven Chunking für überlange Korpora                        │ ✅ Ja (LLM-set Heuristik)          │
  └──────────────────────────────────────────────────────────────────┴────────────────────────────────────┘

  ---
  Offene Punkte vor Implementation

  1. Phase 1 vor oder nach 1.5? — Ich hab oben Phase 1 (OCR) vor 1.5 platziert, weil 1.5b den OCR-Text
  braucht. Phase-1-Ingest+Integrate aber NACH 1.5 (in Phase 1.6), damit Klausuren nicht versehentlich zu
  Karten werden. Sonst gleichbleibend.
  2. exercise als Test-Quelle? — meine Default-Empfehlung: als source-Material verwenden, nicht als Test.
  Optional --exercises-as-tests Flag falls User strenges Audit will.
  3. --validate Loop-Cap auf 2 — hart, kein Konfig-Override. Bestätige oder weiche das auf.

  Bestätige diese drei Punkte (oder korrigiere), dann implementiere ich Phase 1.5 als ersten committbaren
  Baustein. Sie ist eigenständig brauchbar — auch ohne Phase 2/3/5 ist role_map.json ein direkter Bugfix für
  die heutige Phase-1-Logik (Klausuren als Source zu behandeln war immer falsch).

✻ Churned for 3m 17s

❯ schon ganz gut aber phase 1 sollte trotzdem erstmal durchlaufen und ALLE dokuemtnte nehmen. nur das ganz
  danach das classifizieren und auditen und coveragen dass soll in spaeteren phasen passieren. passe den plan
   entsprechend an und restate nochmal die genauen strategien im detail die beta und gamma usw.  steelmanne
  meinen intent maximal und explizere ihn als aufgabenstellung

● Steelmanned Intent

  Du fixierst eine wichtige architektonische Trennung: Phase 1 ist Build, Phasen 2-5 sind Analyse. Phase 1 (=
  existing lazy mode) bleibt unverändert eine Black-Box "schmeiß alle Dokumente rein, baue ein Deck",
  inklusive Klausuren als Source. Das hat drei Begründungen:

  1. Architektur-Hygiene. Phase 1 ist gehärtet, getestet, semantisch-dedupiert. Sie zu schwächen indem man ihr
   Source-Material vorenthält bringt Risiken (was wenn die Klassifikation falsch ist?) ohne klaren Gewinn —
  das semantische Dedup im --integrate filtert ohnehin Redundanz, und Klausurfragen liefern wertvolle
  Anwendungs-Karten ("Konstruiere DEA für L=...") komplementär zu Skript-Definitionen ("Was ist ein DEA?").
  2. Backward-Compat. Heutige pdf2anki .-User bekommen genau das gleiche Resultat wie vorher. --super-lazy ist
   eine zusätzliche Schicht, kein Replacement. Wer den existing Flow gewohnt ist, muss nichts anders machen.
  3. Saubere Phasen-Semantik. Phase 1 antwortet auf "was ist im Korpus?" (Material → Karten). Phasen 2-5
  antworten auf "was sollte im Korpus sein, gemessen an den Lernzielen?" (Karten + Klausuren → Audit +
  Surgeon). Das sind zwei unterschiedliche Fragen, und sie verdienen unterschiedliche Pipelines.

  Konsequenz: Phase 1.5 wird rein informationell — sie liefert ein Rollen-Mapping über alle Dokumente, das die
   nachfolgenden Audit/Examiner-Phasen brauchen, modifiziert aber Phase 1 nicht. Klausuren wandern in Phase 1
  weiter ins Card-Pool (wie heute), und werden in Phase 1.5 zusätzlich als test_corpus markiert. Beide Sichten
   existieren parallel, ohne sich gegenseitig zu beschneiden.

  Die mögliche Sorge "wenn Klausuren ingestet wurden, sind Klausur-Fragen in Karten — dann sagt Audit immer
  ‚covered'" löst sich konzeptuell auf: das --integrate produziert konzept-orientierte Karten ("Was ist ein
  DEA?"), keine wörtlichen Klausur-Kopien — das ist die eigentliche Aufgabe des Ingest-LLM. Wenn Audit-Phase
  findet "Klausur 2024 fragt Spezifika die das Deck nicht hat", liegt das daran, dass die Klausur 2024 neue
  Anwendungen testet, nicht weil sie nicht ingestet war. Das Audit deckt also immer die Generalisierungs-Lücke
   auf — genau das was wir messen wollen.

  Aufgabenstellung

  Restatement des --super-lazy-Plans mit drei Korrekturen ggü. der Vorversion:
  1. Phase 1 bleibt unverändert — alle Dokumente werden ingestet, inklusive Klausuren. Kein "deferred ingest".
  2. Phase 1.5 ist rein informationell — produziert role_map.json für die Audit/Examiner-Phasen, ohne Phase 1
  zu beeinflussen.
  3. Phase 1.6 ("Resumed Lazy-Build") fliegt raus — sie war nur nötig wegen des deferred-ingest-Modells.

  Außerdem: detailliertes Restatement der Strategien β „Auditor + Surgeon" und γ „Examiner" im Kontext dieser
  Phasen-Anordnung — Schritt-für-Schritt, mit Eingabe/Ausgabe pro Stage und expliziter
  LLM/data-manipulation-Annotation.

  ---
  Final Architecture — pdf2anki . --super-lazy [--validate]

                                ┌──────────────────────────────────────────────────┐
                                │ Phase 1  (existing lazy mode, UNVERAENDERT)      │
                                │   alle Docs → OCR → ingest → integrate           │
                                │   (mit semantic dedup) → export                   │
                                │   → card_database.json                           │
                                │   → collection_*.{json,apkg}                     │
                                └────────────────────────┬─────────────────────────┘
                                                         │
                                                         ▼
                                ┌──────────────────────────────────────────────────┐
                                │ Phase 1.5  Document Role Discovery               │
                                │   [LLM-driven, informationell]                    │
                                │   → role_map.json                                │
                                │   → pair_map.json                                │
                                │   → test_corpus.json   source_corpus.json        │
                                └────────────────────────┬─────────────────────────┘
                                                         │
                                                         ▼
                            ┌────────────────────────────┴───────────────────────┐
                            │   [test_corpus = ∅?]                               │
                            │     ja  →  exit ok mit warning                     │
                            │     nein →  weiter                                 │
                            └────────────────────────────┬───────────────────────┘
                                                         │
                                                         ▼
                                ┌──────────────────────────────────────────────────┐
                                │ Phase 2  Audit  [LLM-driven, β-stage 1]          │
                                │   gegen test_corpus + bestehendes Deck            │
                                │   → gap_matrix.json                              │
                                └────────────────────────┬─────────────────────────┘
                                                         │
                            ┌────────────────────────────┴───────────────────────┐
                            │   [keine Lücken?]                                  │
                            │     ja → exit ok ohne weitere Aktion               │
                            │     nein → weiter                                  │
                            └────────────────────────────┬───────────────────────┘
                                                         │
                                                         ▼
                                ┌──────────────────────────────────────────────────┐
                                │ Phase 3  Surgeon  [LLM-driven, β-stage 2]        │
                                │   neue Karten für Lücken aus source_corpus       │
                                │   mit Source-Zitat als Halluzinations-Bremse     │
                                │   → generated_cards.json                         │
                                └────────────────────────┬─────────────────────────┘
                                                         │
                                                         ▼
                                ┌──────────────────────────────────────────────────┐
                                │ Phase 4  Re-Integrate  [existing pipeline]       │
                                │   --integrate (semantic dedup gegen Deck)        │
                                │   --dedup --apply (3-pass cross-validation)      │
                                │   --export                                       │
                                └────────────────────────┬─────────────────────────┘
                                                         │
                                            ─────[--validate]────┐
                                                         │       │
                                                         ▼       ▼
                                ┌──────────────────────────────────────────────────┐
                                │ Phase 5  Examiner  [LLM-driven, γ]               │
                                │   pro Klausur LLM-Simulation: löse die Klausur   │
                                │   AUSSCHLIESSLICH mit dem Deck als Hilfsmittel   │
                                │   → exam_results.json + verdict.json             │
                                │   pass-rate < threshold ∧ iter < 2               │
                                │       → loop zurück zu Phase 3 mit neuen Lücken  │
                                └──────────────────────────────────────────────────┘

  ---
  Strategie β „Auditor + Surgeon" — detaillierte Schritte

  β ist die Default-Implementation: nach Phase 1 misst sie wo das Deck Lücken gegenüber den Klausuren hat, und
   stopft sie. Sie ist konservativ (verschwendet keine Karten), inkrementell (nur Lücken werden bearbeitet)
  und nutzt das gehärtete --integrate und --dedup-Plumbing für die eigentliche Mutation. Sie besteht aus den
  Phasen 1.5 → 2 → 3 → 4 der obigen Architektur.

  β.0 (Voraussetzung): Phase 1 ist gelaufen

  Es existiert ein card_database.json mit Karten aus allen Dokumenten. Existiert es nicht, läuft --super-lazy
  zuerst Phase 1 an.

  β.1 = Phase 1.5 — Document Role Discovery (LLM-driven)

  Eingabe: alle PDFs/TXTs des Projekts (Pfade) plus erste ~3-5 OCR-Seiten pro Doc (Budget dynamisch, Limit
  800k Tokens für den 1M-Context).

  Sub-Stage 1.5a (LLM): ein einziger Mega-Call klassifiziert jedes Dokument auf einen Schlag.

  Prompt-Skelett (kein Filename- oder Sprachkatalog im Code):

  Analyze a corpus of educational documents. For each document, decide its
  didactic ROLE — what role does it play in a learning workflow?

  Role vocabulary (mutually exclusive per doc):
  - script:    primary teaching material (textbook, lecture notes, slides);
               definitorial style, structured by chapters
  - exam:      summative assessment that was/will be graded; formal question
               format, scoring table or time limit cues, identification fields
  - exercise:  practice problems / homework / tutorial sheets; numbered tasks,
               may be graded or ungraded
  - solution:  reference answers paired with an exam or exercise; questions
               plus worked-out solutions
  - notes:     secondary/informal: personal transcripts, tutorial protocols,
               study summaries
  - auxiliary: glossary, formula sheet, reading list, README
  - unknown:   insufficient context

  Pairing: if a doc references another doc as its companion (e.g., a solution
  paired with its exam), name the partner path and the relation type
  (exam_with_solution | exercise_with_solution).

  Confidence: HIGH | MEDIUM | LOW.

  Rationale: 1-2 sentences referring to STRUCTURAL/CONTENT cues, not filename.

  Optional: corpus_observations — a free-text field where you may note any
  recurring corpus-specific patterns you observe. These observations are run-
  local and will not be persisted as code.

  CORPUS:
  [for each doc: path + first_pages_text]

  Output JSON: {"classifications": [...], "corpus_observations": "..."}

  Kosten: ~80 Docs × ~5k Tokens Sample + ~20k Output ≈ $0.24

  Sub-Stage 1.5b (LLM, optional): für jedes Doc mit confidence ∈ {MEDIUM, LOW} aus 1.5a — schicke den vollen
  OCR-Text zur Re-Klassifikation.

  Kosten: variabel, meist ≤ $0.10

  Sub-Stage 1.5c (data-manipulation): pure JSON-Joins über LLM-Output:
  - Aggregiere pair_map.json aus den pairing-Feldern
  - Materialisiere test_corpus.json (Docs mit role ∈ {exam} + standalone solution-Docs)
  - Wenn ein Pair exam_with_solution existiert: in test_corpus wandert die Solution-Version (sie enthält
  Aufgaben + Antworten — wertvolleres Audit-Material)
  - Materialisiere source_corpus.json (Docs mit role ∈ {script, exercise, notes, auxiliary} + Solutions die im
   test_corpus stehen)

  Kosten: $0

  Output: role_discovery_<ts>/role_map.json, pair_map.json, test_corpus.json, source_corpus.json, optional
  corpus_observations.md.

  β.2 = Phase 2 — Audit (LLM-driven, single mega-call)

  Eingabe (alles im 1M-Context):
  - Voller OCR-Text aller Dokumente aus test_corpus.json (~640k Tokens für 64 GTI-Klausuren)
  - Alle Karten-Fronts aus card_database.json (~18k Tokens)

  LLM-Aufgabe: pro Klausur die Aufgaben extrahieren und prüfen ob das Deck sie abdeckt.

  For each exam in the test corpus:
  1. Extract every distinct task/question (note: a single exam may have multiple
     subtasks; each subtask is a separate item)
  2. For each task, decide: "does the current deck contain a card that lets a
     student answer this task?" Cite the card front if yes; describe the missing
     concept/skill in 1 sentence if no.

  A "covered" task is one where ANY card front in the deck (when its back is
  known) provides the conceptual machinery to solve the task. It does NOT need
  to match the task wording. Definition-cards count as coverage for application
  tasks if the application is direct.

  DECK FRONTS:
  [indexed list]

  EXAMS:
  [for each: path + full OCR text]

  Output JSON:
  {"per_exam": [
    {"exam_path": "...",
     "tasks": [
       {"task_id": "1", "task_text": "...",
        "covered": true|false,
        "covering_card_fronts": ["...", "..."],
        "gap_description": "...|null",
        "gap_severity": "CRITICAL|MAJOR|MINOR|null"}
     ],
     "exam_coverage_pct": 0.85}
  ]}

  gap_severity erlaubt Phase 3 später Priorisierung (CRITICAL = Konzept fehlt komplett, MINOR = nur
  Detail-Variante fehlt).

  Output: gap_matrix.json strukturiert per-Klausur-per-Task.

  Kosten: ~700k input + ~50k output ≈ $0.45

  β.3 = Phase 3 — Surgeon (LLM-driven, single mega-call)

  Eingabe:
  - gap_matrix.json (alle Lücken, nach Severity sortiert)
  - Voller Text aller Docs in source_corpus.json (~500k Tokens)
  - Aktuelles Deck (Fronts only, als Negativ-Liste gegen Selbst-Duplikation im Surgeon-Output)

  LLM-Aufgabe:

  For each gap in the gap matrix, generate 1-3 Anki cards that fill it. You MUST
  cite a verbatim ≥10-character quote from the source corpus for each card. If
  no source supports the gap, mark it "unsourced" and skip card generation. Do
  NOT generate fronts that are semantically equivalent to any front already in
  the existing deck (the deck fronts list is provided below).

  For high-severity gaps (CRITICAL, MAJOR), prioritize comprehensive coverage
  (2-3 cards: definition + property + application). For MINOR gaps, 1 card
  suffices.

  Output JSON:
  {"new_cards": [
    {"front": "...", "back": "...",
     "source_quote": "verbatim from source",
     "source_path": "...",
     "addresses_gap_id": "<exam>:<task>",
     "card_role": "definition|property|application"}
  ], "unsourced_gaps": ["gap_id_1", ...]}

  Output: generated_cards.json, jede Karte mit Quellen-Zitat.

  Kosten: ~500k input + ~30k output ≈ $0.31

  β.4 = Phase 4 — Re-Integrate (existing pipeline, data-manipulation)

  generated_cards.json wird so transformiert dass das --integrate damit umgehen kann (passt die Datei in das
  new_cards_output.json-Format an), dann:

  pdf2anki workflow --integrate              # semantic dedup gegen bestehende Karten
  pdf2anki workflow --dedup --passes 3 --apply   # cross-validation gegen Gesamt-Deck
  pdf2anki workflow --export                 # neue .apkg-Files

  Kosten: ~$0.30 (existing pipeline)

  β-Total: ~$1.40 pro Run (ohne Phase 1, nur Audit+Surgeon-Anteil)

  ---
  Strategie γ „Examiner" — detaillierte Schritte (--validate flag)

  γ ist optional. Während β Coverage als topic-match misst (Auditor sagt "Konzept X ist im Deck"), misst γ
  operational pass-rate — würde ein Studi mit nur dem Deck als Hilfsmittel die Klausur bestehen? Dies ist die
  einzige direkt-messbare Erfolgs-Metrik. γ läuft nach Phase 4 und kann eine zweite Surgeon-Runde triggern
  wenn die pass-rate unzureichend ist.

  γ.1 = Phase 5 — Examiner (LLM-driven, per-Klausur-Calls)

  Eingabe (per Klausur ein Call, 64 Calls für GTI-Korpus):
  - Vollständiger OCR-Text der Klausur (~10k Tokens)
  - Vollständiges Deck als "Lernmaterial" (Fronts+Backs aller Karten, ~120k Tokens)

  LLM-Aufgabe:

  You are a student taking the following exam. Your ONLY allowed reference is the
  Anki deck below. You may not use outside knowledge.

  For each task on the exam:
  1. Attempt an answer using only deck content
  2. Cite the card(s) you used (by front string)
  3. Report your confidence (HIGH | MEDIUM | LOW)
  4. If you cannot answer because the deck lacks specific information, describe
     what's missing as a precise, generative gap (e.g., "no card explains how
     to construct a DFA from a regular expression step-by-step")
  5. Estimate whether your answer would earn full / partial / no points

  EXAM:
  [full text]

  DECK (your only allowed reference):
  [front + back of each card, indexed]

  Output JSON:
  {"exam_path": "...",
   "tasks": [
     {"task_id": "...", "task_text": "...",
      "answer": "...",
      "cited_card_fronts": ["..."],
      "confidence": "HIGH|MEDIUM|LOW",
      "deck_gap": "...|null",
      "estimated_score": "full|partial|none"}
   ],
   "pass_estimate": true|false,
   "pass_rate_estimate": 0.0-1.0}

  Output: exam_results.json per Klausur + aggregierter verdict.json mit:
  - aggregate_pass_rate (Anteil der Klausuren mit pass_estimate=true)
  - aggregate_score_estimate (Mittelwert der pass_rate_estimate)
  - Liste aller deck_gap-Texte gruppiert nach Häufigkeit (häufige gaps = systematische Schwächen)

  Kosten: 64 × (~12k input + ~2k output) ≈ 770k input + 130k output ≈ $0.65 pro Sweep

  γ.2 — Loop-Bedingung

  Wenn verdict.json.aggregate_pass_rate < 0.8 UND iteration_count < 2:
  - Aggregierte deck_gap-Texte werden in eine neue gap_matrix.json umgewandelt (deterministische
  data-manipulation, nur JSON-Reformatierung)
  - Phase 3 + 4 + 5 laufen erneut mit dieser gap_matrix
  - Hartes Cap auf 2 Iterationen

  Wenn aggregate_pass_rate ≥ 0.8 ODER iteration_count = 2:
  - Pipeline endet
  - Final-Verdict wird in verdict.json geschrieben

  γ-Max-Kosten: 2 × ($0.65 Examiner + $0.31 Surgeon-Reentry + $0.30 Re-Integrate) = ~$2.50

  ---
  Cost-Recap

  ┌────────────────────────┬───────────────────┬──────────────────────┬────────────────────────────┐
  │         Phase          │     LLM/data      │         Wann         │           Kosten           │
  ├────────────────────────┼───────────────────┼──────────────────────┼────────────────────────────┤
  │ 1 (existing lazy mode) │ LLM (existing)    │ jeder Run            │ ~$0.50                     │
  ├────────────────────────┼───────────────────┼──────────────────────┼────────────────────────────┤
  │ 1.5a Klassifikation    │ LLM mega-call     │ jeder Run            │ ~$0.24                     │
  ├────────────────────────┼───────────────────┼──────────────────────┼────────────────────────────┤
  │ 1.5b Re-Klassifikation │ LLM, optional     │ bei MEDIUM/LOW       │ ≤$0.10                     │
  ├────────────────────────┼───────────────────┼──────────────────────┼────────────────────────────┤
  │ 1.5c Materialization   │ data-manipulation │ jeder Run            │ $0                         │
  ├────────────────────────┼───────────────────┼──────────────────────┼────────────────────────────┤
  │ 2 Audit                │ LLM mega-call     │ wenn test_corpus ≠ ∅ │ ~$0.45                     │
  ├────────────────────────┼───────────────────┼──────────────────────┼────────────────────────────┤
  │ 3 Surgeon              │ LLM mega-call     │ wenn gaps > 0        │ ~$0.31                     │
  ├────────────────────────┼───────────────────┼──────────────────────┼────────────────────────────┤
  │ 4 Re-Integrate         │ LLM (existing)    │ wenn Phase 3 lief    │ ~$0.30                     │
  ├────────────────────────┼───────────────────┼──────────────────────┼────────────────────────────┤
  │ 5 Examiner             │ LLM, optional     │ nur mit --validate   │ ~$0.65/sweep, max 2 sweeps │
  └────────────────────────┴───────────────────┴──────────────────────┴────────────────────────────┘

  --super-lazy (β allein): ~$1.90 pro Run
  --super-lazy --validate (β + γ): ~$3.20 pro Run (max ~$4.50 wenn γ-Loop voll ausgeschöpft)

  ---
  Disziplin-Übersicht (unverändert ggü. Vorversion)

  Im Repo erlaubt:
  - ✅ LLM-Prompts mit Spec-Beschreibungen (Rollen-Vokabular, Audit-Kriterien) — das ist Spec, nicht Heuristik
  - ✅ Run-Dir-Artefakte mit korpus-spezifischen Beobachtungen (corpus_observations)
  - ✅ JSON-Joins über LLM-vergebene Schlüssel
  - ✅ Filter/Projection über LLM-vergebene Confidence-Levels
  - ✅ LLM-driven Chunking für überlange Korpora

  Nicht erlaubt:
  - ❌ Hardcoded Token-Catalogs für Rollen
  - ❌ Hardcoded Topic-Regex für Coverage
  - ❌ Hardcoded Sprach-Annahmen
  - ❌ Hardcoded Filename-Pattern-Matching

  ---
  Drei offene Punkte vor Implementation

  1. β-Failure auf γ-Crash: wenn --validate aktiviert ist und Phase 5 Halluzinationen liefert (LLM behauptet
  eine Lücke zu sehen die keine ist), springt der Loop zurück zu Phase 3 und generiert unnötige Karten. Mein
  Vorschlag: vor Phase-3-Reentry läuft eine Mini-Verifikations-Stage die jede γ-identifizierte Lücke einzeln
  prüft (1 LLM-Call), erst dann wandert sie ins gap_matrix. Kostet ~$0.10 zusätzlich, schützt vor
  Karten-Inflation.
  2. Phase-1.5-vs-Phase-2-Granularität: soll gap_matrix.json per-Klausur oder per-Task strukturiert sein?
  Aktuell pro Task — das ermöglicht feine Severity-Wertung. Alternative: pro Klausur (gröber, aber stabilerer
  LLM-Output). Mein Vorschlag: per-Task bleibt, aber Phase 3 priorisiert nach Severity und cap't auf max 50
  neue Karten pro Run.
  3. exercise als Test- oder Source-Korpus? Die per-Korpus-Antwort darf das LLM in Phase 1.5 selbst geben —
  ich ergänze einen Output exercise_treatment_recommendation im 1.5a-Prompt: "for this corpus, should
  exercises be treated as test or source material?". Fallback: source wenn das LLM keine Empfehlung gibt.

  Bestätige diese drei Punkte, dann implementiere ich Phase 1.5 als ersten committbaren Baustein. Sie ist
  eigenständig brauchbar (auch ohne β/γ liefert role_map.json einen Klassifikations-Output, den ein Studi
  direkt für Inspektion nutzen kann), und sie blockiert die spätere β/γ-Implementierung nicht.

✻ Sautéed for 2m 35s