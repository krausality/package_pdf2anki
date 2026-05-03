"""
Post-hoc semantic deduplication for the SSOT card database.

4-stage pipeline. Each stage reads/writes JSON in a run-dir for resumability.

    stage1_detect_clusters   →  dedup_stage1_clusters.json
    stage2_cross_validate    →  dedup_stage2_votes.json
    stage3_resolve           →  dedup_stage3_actions.json
    stage4_apply             →  dedup_stage4_applied.json

Detection (stage 1+2) uses the LLM as the sole classifier — no Jaccard pre-filter.
Stage 1 sends the full indexed front list to the LLM and asks it to identify
clusters of semantic duplicates. Stage 2 re-runs detection N times with shuffled
order and varied prompts to vote per pair, producing HIGH/MEDIUM/LOW/NONE
confidence labels. Stage 3 picks an action per surviving cluster
(keep_oldest / keep_newest / keep_specific:<guid> / keep_all / skip / merge_backs).
Stage 4 applies actions atomically with backup.
"""

from __future__ import annotations

import json
import re
import sys
import random
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from .console_utils import safe_print
from .llm_helper import get_llm_decision
from .forensic_logger import log_event


# ─────────────────────────────────────────────────────────────────────────────
# Prompt variants for cross-validation (Stage 2)
# ─────────────────────────────────────────────────────────────────────────────

_DUP_CRITERIA = """\
Zwei Karten sind SEMANTISCHE DUPLIKATE, wenn:
- sie das gleiche Konzept testen UND
- eine korrekte Antwort auf Karte A waere auch korrekte Antwort auf Karte B (modulo Formulierung) UND
- ein Studi sie beim Lernen als redundant empfaende.

Sie sind KEINE Duplikate, wenn:
- verschiedene Mengen-/Operator-Bedingungen (=, <=, >=, <, >, mod-Restklassen)
- verschiedene mengen-theoretische Operationen (Schnitt vs Vereinigung, Komplement)
- verschiedene Richtungen einer Implikation/Aequivalenz (X -> Y vs Y -> X)
- verschiedene Quantifizierungen (alle vs es gibt, fuer ein vs fuer kein)
- eine Karte ist Definition, die andere konkrete Anwendung
- verschiedene Lerntiefen (Begriffsklaerung vs Beweisaufgabe vs Konstruktionsaufgabe)
- verschiedene konkrete Werte/Konstanten (genau 7 vs genau 42 vs genau 1000)
"""

_PROMPT_VARIANTS = [
    # Variant 0 — "duplicate detection" framing
    """\
Du bekommst eine indexierte Liste von Anki-Karten-Fronts. Identifiziere Cluster
von semantischen Duplikaten.

{criteria}

EINGABE (indexierte Fronts, je eine pro Zeile):
{cards}

AUFGABE: Gib alle Cluster zurueck, in denen 2+ Indizes semantische Duplikate sind.
Karten ohne Duplikat erwaehnst du nicht. Antworte NUR mit valid JSON:

{{"clusters": [
   {{"members": [<idx>, <idx>, ...], "rationale": "<kurze Begruendung>"}}
]}}

Wenn keine Duplikate vorhanden: {{"clusters": []}}.
""",
    # Variant 1 — "same-concept" framing
    """\
Untenstehend siehst du eine indizierte Liste von Karteikarten-Vorderseiten.
Gruppiere alle Vorderseiten, die DASSELBE KONZEPT testen.

{criteria}

INDEX:
{cards}

AUSGABE als striktes JSON:
{{"clusters": [
   {{"members": [i, j, k], "rationale": "Konzept das alle teilen"}}
]}}

Eine Karte gehoert in HOECHSTENS einen Cluster. Wenn alle Karten unique sind:
{{"clusters": []}}.
""",
    # Variant 2 — "would a student notice" framing
    """\
Aufgabe: Welche dieser Karteikarten-Vorderseiten wuerde ein Studi beim Lernen
als REDUNDANT empfinden — also so, dass das Beantworten der einen Karte das
Beantworten der anderen trivial macht?

{criteria}

KARTEN (Index: Vorderseite):
{cards}

JSON-Format:
{{"clusters": [
   {{"members": [<int>, ...], "rationale": "<warum redundant>"}}
]}}

Nur Cluster mit 2+ Mitgliedern angeben. {{"clusters": []}} wenn alles unique.
""",
]


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — LLM-First-Pass-Detection
# ─────────────────────────────────────────────────────────────────────────────

def stage1_detect_clusters(
    cards: list,
    run_dir: Path,
    model: str = "google/gemini-2.5-flash",
) -> dict:
    """Send full indexed front list to LLM, get back cluster proposals.

    For decks larger than ~3000 cards, the prompt may exceed sane limits — we
    chunk in that case (with overlap), but for typical SSOT decks one call suffices.
    """
    if len(cards) < 2:
        result = {"schema_version": 1, "total_cards": len(cards), "clusters": [], "model": model}
        _write_stage(run_dir, "stage1_clusters.json", result)
        return result

    indexed = "\n".join(f"{i}: {c.front!s}" for i, c in enumerate(cards))
    prompt = _PROMPT_VARIANTS[0].format(criteria=_DUP_CRITERIA, cards=indexed)

    safe_print(f"🔍 Stage 1: LLM-Detection auf {len(cards)} Karten (model={model})...")
    log_event("dedup_stage1_request", {
        "total_cards": len(cards),
        "prompt_length": len(prompt),
        "model": model,
    })

    response = get_llm_decision(
        header_context=None,
        prompt_body=prompt,
        model=model,
        json_mode=True,
    )
    clusters = _parse_clusters_response(response, len(cards))

    result = {
        "schema_version": 1,
        "total_cards": len(cards),
        "clusters": clusters,
        "model": model,
        "card_index": [{"idx": i, "guid": c.guid, "front": c.front} for i, c in enumerate(cards)],
    }
    _write_stage(run_dir, "stage1_clusters.json", result)
    safe_print(f"  → {len(clusters)} Cluster gefunden, "
               f"{sum(len(c['members']) for c in clusters)} betroffene Karten.")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Multi-Pass Cross-Validation
# ─────────────────────────────────────────────────────────────────────────────

def stage2_cross_validate(
    cards: list,
    stage1_result: dict,
    run_dir: Path,
    passes: int = 3,
    model: str = "google/gemini-2.5-flash",
) -> dict:
    """Re-run cluster detection N times with shuffled order and varied prompts.

    Aggregate per pair: pair (i, j) is a duplicate-vote if both are in a cluster
    of any pass. Confidence: HIGH = all passes, MEDIUM = majority, LOW = 1, NONE = 0.

    Pass 0 always uses the order and prompt variant of stage1 (so it is reused
    cost-free). Subsequent passes shuffle and vary.
    """
    n = len(cards)
    pair_votes: dict[tuple[int, int], list[bool]] = {}

    pass_results = []
    for pass_idx in range(passes):
        if pass_idx == 0 and stage1_result.get("clusters") is not None:
            clusters = stage1_result["clusters"]
            variant = 0
            order = list(range(n))
            safe_print(f"🔁 Stage 2 Pass {pass_idx + 1}/{passes}: re-using Stage 1 result (variant 0).")
        else:
            variant = pass_idx % len(_PROMPT_VARIANTS)
            rng = random.Random(pass_idx)
            order = list(range(n))
            rng.shuffle(order)
            indexed = "\n".join(f"{i}: {cards[order[i]].front!s}" for i in range(n))
            prompt = _PROMPT_VARIANTS[variant].format(criteria=_DUP_CRITERIA, cards=indexed)
            safe_print(f"🔁 Stage 2 Pass {pass_idx + 1}/{passes}: variant {variant}, shuffled order.")
            log_event("dedup_stage2_request", {
                "pass_idx": pass_idx,
                "variant": variant,
                "prompt_length": len(prompt),
            })
            response = get_llm_decision(
                header_context=None,
                prompt_body=prompt,
                model=model,
                json_mode=True,
            )
            raw_clusters = _parse_clusters_response(response, n)
            # Translate shuffled indices back to original indices
            clusters = [
                {"members": [order[i] for i in c["members"]],
                 "rationale": c.get("rationale", "")}
                for c in raw_clusters
            ]

        # Collect this pass's pairs
        pass_pairs = set()
        for cluster in clusters:
            for i, j in combinations(sorted(cluster["members"]), 2):
                pass_pairs.add((i, j))
        # Update votes for all pairs seen across all passes
        for pair in pass_pairs:
            pair_votes.setdefault(pair, [False] * passes)[pass_idx] = True
        # Backfill: pairs that appeared in earlier passes but not this one stay False
        for pair, votes in pair_votes.items():
            if len(votes) <= pass_idx:
                votes.extend([False] * (pass_idx + 1 - len(votes)))

        pass_results.append({"pass": pass_idx, "variant": variant, "clusters": clusters})

    # Build verdicts
    def _confidence(votes: list[bool]) -> str:
        n_yes = sum(1 for v in votes if v)
        if n_yes == passes:
            return "HIGH"
        if n_yes >= (passes // 2 + 1):
            return "MEDIUM"
        if n_yes >= 1:
            return "LOW"
        return "NONE"

    verdicts = [
        {"pair": list(pair), "votes": votes, "confidence": _confidence(votes)}
        for pair, votes in sorted(pair_votes.items())
    ]
    verdicts = [v for v in verdicts if v["confidence"] != "NONE"]

    # Transitive closure: build clusters from HIGH+MEDIUM pairs
    keep_levels = ("HIGH", "MEDIUM")
    parent = list(range(n))
    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def _union(a, b):
        ra, rb = _find(a), _find(b)
        if ra != rb: parent[ra] = rb

    for v in verdicts:
        if v["confidence"] in keep_levels:
            i, j = v["pair"]
            _union(i, j)

    cluster_groups: dict[int, list[int]] = {}
    for idx in range(n):
        root = _find(idx)
        cluster_groups.setdefault(root, []).append(idx)
    final_clusters = [
        {"members": members, "confidence": _cluster_confidence(members, verdicts)}
        for members in cluster_groups.values() if len(members) >= 2
    ]

    result = {
        "schema_version": 1,
        "passes": passes,
        "prompt_variants": list(range(len(_PROMPT_VARIANTS))),
        "verdicts": verdicts,
        "final_clusters": final_clusters,
        "pass_results": pass_results,
    }
    _write_stage(run_dir, "stage2_votes.json", result)
    safe_print(f"  → {len(verdicts)} Pärchen mit ≥1 Stimme, "
               f"{sum(1 for v in verdicts if v['confidence'] == 'HIGH')} HIGH, "
               f"{sum(1 for v in verdicts if v['confidence'] == 'MEDIUM')} MEDIUM, "
               f"{sum(1 for v in verdicts if v['confidence'] == 'LOW')} LOW.")
    safe_print(f"  → {len(final_clusters)} Cluster nach transitiver Schließung über HIGH+MEDIUM.")
    return result


def _cluster_confidence(members: list[int], verdicts: list[dict]) -> str:
    """Cluster confidence = lowest pair-confidence among its member-pairs."""
    member_set = set(members)
    levels = []
    for v in verdicts:
        i, j = v["pair"]
        if i in member_set and j in member_set:
            levels.append(v["confidence"])
    order = ["HIGH", "MEDIUM", "LOW", "NONE"]
    if not levels:
        return "NONE"
    return max(levels, key=order.index)


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Resolution (auto / manual / hybrid)
# ─────────────────────────────────────────────────────────────────────────────

def stage3_resolve(
    cards: list,
    stage2_result: dict,
    run_dir: Path,
    resolver: str = "hybrid",
    include_low: bool = False,
    allow_merge: bool = False,
    model: str = "google/gemini-2.5-flash",
) -> dict:
    """For each surviving cluster, pick an action.

    Actions: keep_oldest, keep_newest, keep_specific:<guid>, keep_all, skip, merge_backs.
    `merge_backs` is only emitted when `allow_merge=True` AND the LLM judges that
    a concrete piece of content lives in only one of the cards.
    """
    final_clusters = stage2_result.get("final_clusters", [])
    if not include_low:
        final_clusters = [c for c in final_clusters if c["confidence"] in ("HIGH", "MEDIUM")]

    actions: list[dict] = []
    for cluster_idx, cluster in enumerate(final_clusters):
        members = cluster["members"]
        confidence = cluster["confidence"]

        if resolver == "auto" or (resolver == "hybrid" and confidence == "HIGH"):
            action = _resolve_auto(cards, members, allow_merge=allow_merge, model=model)
            decided_by = "llm_auto"
        elif resolver == "manual" or (resolver == "hybrid" and confidence == "MEDIUM"):
            action = _resolve_manual(cards, members, allow_merge=allow_merge)
            decided_by = "human_manual"
        else:
            action = {"action": "skip", "rationale": f"unhandled confidence={confidence}"}
            decided_by = "fallback"

        actions.append({
            "cluster_id": cluster_idx,
            "members": members,
            "member_guids": [cards[i].guid for i in members],
            "confidence": confidence,
            "decided_by": decided_by,
            **action,
        })

    result = {
        "schema_version": 1,
        "resolver": resolver,
        "include_low": include_low,
        "allow_merge": allow_merge,
        "actions": actions,
    }
    _write_stage(run_dir, "stage3_actions.json", result)
    summary = {}
    for a in actions:
        summary[a["action"]] = summary.get(a["action"], 0) + 1
    safe_print(f"  → {len(actions)} Aktionen: " +
               ", ".join(f"{k}={v}" for k, v in summary.items()))
    return result


def _resolve_auto(cards: list, members: list[int], allow_merge: bool, model: str) -> dict:
    """LLM decides the action for a cluster."""
    member_data = [
        {"idx": i, "guid": cards[i].guid, "front": cards[i].front,
         "back": cards[i].back, "created_at": _ts_str(cards[i].created_at)}
        for i in members
    ]
    member_text = "\n\n".join(
        f"[{m['idx']}] (guid={m['guid'][:8]}, created={m['created_at'][:10]})\n"
        f"  Front: {m['front']}\n"
        f"  Back:  {m['back']}"
        for m in member_data
    )
    merge_hint = (
        "- merge_backs: NUR wenn ein konkreter Inhalt (Definition, Bedingung, "
        "Beispiel, Eigenschaft) in mindestens einer Karte fehlt, der in einer "
        "anderen vorhanden ist. Dann wird der Inhalt zusammengefuehrt.\n"
        if allow_merge else ""
    )
    prompt = (
        "Entscheide pro semantischem Duplikat-Cluster welche Aktion auszufuehren ist.\n\n"
        f"CLUSTER (alle Mitglieder testen dasselbe Konzept):\n{member_text}\n\n"
        "MOEGLICHE AKTIONEN:\n"
        "- keep_oldest: aelteste Karte bleibt, alle anderen werden geloescht\n"
        "- keep_newest: neueste Karte bleibt, alle anderen werden geloescht\n"
        "- keep_specific: eine spezifische Karte bleibt (Angabe der target_idx)\n"
        f"{merge_hint}"
        "- keep_all: Cluster ist eigentlich KEIN Duplikat, alle Karten behalten "
        "(Veto gegen Detection)\n"
        "- skip: Entscheidung verschieben\n\n"
        "Antwort NUR als JSON:\n"
        "{\"action\": \"<aktion>\", \"target_idx\": <int|null>, \"rationale\": \"<begruendung>\"}\n"
    )
    response = get_llm_decision(
        header_context=None,
        prompt_body=prompt,
        model=model,
        json_mode=True,
    )
    parsed = _parse_action_response(response, members)
    return parsed


def _resolve_manual(cards: list, members: list[int], allow_merge: bool) -> dict:
    """Interactive CLI: shows full card content, asks for action."""
    print("\n" + "=" * 70)
    print(f"CLUSTER mit {len(members)} Karten — bitte Aktion waehlen:")
    print("=" * 70)
    for i, idx in enumerate(members):
        c = cards[idx]
        print(f"\n[{i}] guid={c.guid[:8]}  created={_ts_str(c.created_at)[:10]}")
        print(f"    Front: {c.front}")
        print(f"    Back:  {(c.back or '')[:200]}")
    print("\nAktionen:")
    print("  o      = keep_oldest")
    print("  n      = keep_newest")
    print("  0..N   = keep_specific (Index oben)")
    if allow_merge:
        print("  m      = merge_backs")
    print("  k      = keep_all (kein Duplikat, Veto)")
    print("  s      = skip")
    while True:
        try:
            choice = input("Aktion> ").strip().lower()
        except EOFError:
            return {"action": "skip", "rationale": "EOF on stdin"}
        if choice == "o":
            return {"action": "keep_oldest", "target_idx": None,
                    "rationale": "manual: keep_oldest"}
        if choice == "n":
            return {"action": "keep_newest", "target_idx": None,
                    "rationale": "manual: keep_newest"}
        if choice == "k":
            return {"action": "keep_all", "target_idx": None,
                    "rationale": "manual: not a duplicate"}
        if choice == "s":
            return {"action": "skip", "target_idx": None, "rationale": "manual: skip"}
        if choice == "m" and allow_merge:
            return {"action": "merge_backs", "target_idx": None,
                    "rationale": "manual: merge_backs"}
        if choice.isdigit() and int(choice) < len(members):
            return {"action": "keep_specific",
                    "target_idx": members[int(choice)],
                    "rationale": f"manual: keep_specific[{choice}]"}
        print(f"Ungueltige Eingabe '{choice}'. Versuche erneut.")


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4 — Apply
# ─────────────────────────────────────────────────────────────────────────────

def stage4_apply(
    db_manager,
    stage3_result: dict,
    run_dir: Path,
    apply: bool = False,
) -> dict:
    """Execute actions on the database. Default dry-run.

    With apply=True: backup card_database.json, mutate, save_database, distribute_to_derived_files.
    On exception: restore backup.
    """
    actions = stage3_result.get("actions", [])
    guids_to_remove: set[str] = set()
    merges: list[tuple[str, str]] = []  # (keep_guid, merged_back) - applied via LLM merge

    for a in actions:
        action = a["action"]
        members = a["members"]
        member_guids = a["member_guids"]
        if action == "keep_oldest":
            kept = _oldest(db_manager, member_guids)
            guids_to_remove.update(g for g in member_guids if g != kept)
        elif action == "keep_newest":
            kept = _newest(db_manager, member_guids)
            guids_to_remove.update(g for g in member_guids if g != kept)
        elif action == "keep_specific":
            target_idx = a.get("target_idx")
            if target_idx is None or target_idx not in members:
                continue
            kept_guid = db_manager.cards[target_idx].guid
            guids_to_remove.update(g for g in member_guids if g != kept_guid)
        elif action == "merge_backs":
            kept_guid, merged_back = _llm_merge(db_manager, member_guids)
            if kept_guid:
                merges.append((kept_guid, merged_back))
                guids_to_remove.update(g for g in member_guids if g != kept_guid)
        # keep_all / skip → no-op

    summary = {
        "actions_total": len(actions),
        "guids_to_remove": list(guids_to_remove),
        "merges": [{"kept_guid": k, "new_back": b[:200] + ("..." if len(b) > 200 else "")}
                   for k, b in merges],
        "applied": apply,
        "backup_path": None,
    }

    if not apply:
        safe_print(f"🔍 dry_run: würde {len(guids_to_remove)} Karten entfernen, "
                   f"{len(merges)} Backs mergen. Verwende --apply zum Schreiben.")
        _write_stage(run_dir, "stage4_applied.json", summary)
        return summary

    # Apply: backup → mutate → save → distribute. Rollback on Exception.
    backup_path = f"{db_manager.db_path}.before_dedup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
    try:
        with open(db_manager.db_path, "r", encoding="utf-8") as src, \
             open(backup_path, "w", encoding="utf-8") as dst:
            dst.write(src.read())
        summary["backup_path"] = backup_path
        safe_print(f"💾 Backup geschrieben: {backup_path}")

        # Apply merges first (mutate kept card's back)
        for kept_guid, merged_back in merges:
            for c in db_manager.cards:
                if c.guid == kept_guid:
                    c.back = merged_back
                    c.updated_at = datetime.now().isoformat()
                    break

        original_count = len(db_manager.cards)
        db_manager.cards = [c for c in db_manager.cards if c.guid not in guids_to_remove]
        db_manager.save_database()

        safe_print(f"✅ {original_count - len(db_manager.cards)} Karten entfernt, "
                   f"{len(merges)} Backs gemerged. DB hat jetzt {len(db_manager.cards)} Karten.")

        # Auto-propagate to derived files (collection JSONs + markdown).
        # This keeps the SSOT and its derived artifacts in sync after dedup.
        # .apkg files still need an explicit `--export` afterwards.
        try:
            project_dir = str(Path(db_manager.db_path).parent)
            db_manager.distribute_to_derived_files(project_dir)
            summary["distributed"] = True
            safe_print("📤 Derived files (collection JSONs + markdown) aktualisiert. "
                       "Run `pdf2anki workflow --export` für .apkg-Update.")
        except Exception as dist_err:
            summary["distributed"] = False
            summary["distribute_error"] = str(dist_err)
            safe_print(f"⚠️ Distribute fehlgeschlagen: {dist_err} — "
                       f"DB-Mutation steht, derived files sind stale. "
                       f"Manuell: pdf2anki workflow --sync && pdf2anki workflow --export",
                       "WARNING")

    except Exception as e:
        safe_print(f"❌ Apply fehlgeschlagen: {e} — restore aus Backup.", "ERROR")
        try:
            with open(backup_path, "r", encoding="utf-8") as src, \
                 open(db_manager.db_path, "w", encoding="utf-8") as dst:
                dst.write(src.read())
            db_manager.load_database()
            safe_print("↩️ Backup wiederhergestellt.")
        except Exception as restore_err:
            safe_print(f"❌ ROLLBACK FEHLGESCHLAGEN: {restore_err} — DB könnte inkonsistent sein!", "ERROR")
        summary["error"] = str(e)
        _write_stage(run_dir, "stage4_applied.json", summary)
        return summary

    _write_stage(run_dir, "stage4_applied.json", summary)
    return summary


def _ts_str(ts) -> str:
    """Coerce a created_at value (datetime or str) to ISO-format string."""
    if ts is None:
        return ""
    if isinstance(ts, str):
        return ts
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


def _oldest(db_manager, guids: list[str]) -> str:
    cards = [c for c in db_manager.cards if c.guid in guids]
    return min(cards, key=lambda c: _ts_str(c.created_at)).guid


def _newest(db_manager, guids: list[str]) -> str:
    cards = [c for c in db_manager.cards if c.guid in guids]
    return max(cards, key=lambda c: _ts_str(c.created_at)).guid


def _llm_merge(db_manager, guids: list[str], model: str = "google/gemini-2.5-flash") -> tuple[str | None, str]:
    """LLM merges backs from multiple cards into one consolidated back.
    Returns (kept_guid, merged_back). kept_guid is the oldest card's guid.
    The LLM is instructed to ONLY combine content from the inputs, not invent."""
    cards = [c for c in db_manager.cards if c.guid in guids]
    if not cards:
        return None, ""
    cards.sort(key=lambda c: _ts_str(c.created_at))
    kept = cards[0]
    backs_text = "\n\n".join(f"BACK {i}:\n{c.back}" for i, c in enumerate(cards))
    prompt = (
        "Vereinige die folgenden Anki-Card-Backs zu EINER konsolidierten Antwort, die alle "
        "konkreten Inhalte (Definitionen, Bedingungen, Beispiele) aus den Eingaben enthaelt.\n"
        "REGELN:\n"
        "- Keine neuen Inhalte hinzufuegen (kein Wissen ausserhalb der Eingaben).\n"
        "- Doppelt vorhandene Inhalte einmal nennen.\n"
        "- Inhalte die nur in einem Back stehen, MUESSEN erhalten bleiben.\n"
        "- Format: kompakter Text wie eine normale Anki-Karten-Rueckseite.\n\n"
        f"FRONT (gleich für alle):\n{kept.front}\n\n"
        f"{backs_text}\n\n"
        "Antworte NUR mit JSON: {\"merged_back\": \"<kombinierter Text>\"}\n"
    )
    response = get_llm_decision(header_context=None, prompt_body=prompt, model=model, json_mode=True)
    try:
        cleaned = (response or "").strip()
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned, flags=re.MULTILINE)
        data = _robust_json_loads(cleaned.strip())
        return kept.guid, data.get("merged_back", kept.back)
    except (json.JSONDecodeError, AttributeError):
        safe_print(f"⚠️ Merge-LLM-Antwort nicht parsebar; behalte {kept.guid[:8]} ohne Merge.", "WARNING")
        return kept.guid, kept.back


# ─────────────────────────────────────────────────────────────────────────────
# Top-level entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_dedup(
    db_manager,
    run_dir: Path | None = None,
    passes: int = 3,
    resolver: str = "hybrid",
    from_stage: int = 1,
    apply: bool = False,
    include_low: bool = False,
    allow_merge: bool = False,
    model: str = "google/gemini-2.5-flash",
) -> dict:
    """Run the 4-stage dedup pipeline. Returns the final stage4_applied.json dict.

    run_dir defaults to <project>/dedup_run_<timestamp>/. If from_stage > 1, the
    most recent dedup_run_*/ in the project dir is used (resume mode).
    """
    project_dir = Path(db_manager.db_path).parent
    if run_dir is None:
        if from_stage > 1:
            existing = sorted(project_dir.glob("dedup_run_*"), key=lambda p: p.name, reverse=True)
            if not existing:
                raise FileNotFoundError(
                    f"--from-stage {from_stage} requested but no dedup_run_* found in {project_dir}"
                )
            run_dir = existing[0]
            safe_print(f"📂 Resume: nutze {run_dir.name}")
        else:
            run_dir = project_dir / f"dedup_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    safe_print(f"\n=== 🧹 Dedup-Pipeline (run_dir={run_dir.name}) ===")
    safe_print(f"  passes={passes}, resolver={resolver}, from_stage={from_stage}, "
               f"apply={apply}, allow_merge={allow_merge}")

    cards = db_manager.cards

    if from_stage <= 1:
        stage1 = stage1_detect_clusters(cards, run_dir, model=model)
    else:
        stage1 = _read_stage(run_dir, "stage1_clusters.json")
        safe_print(f"📂 Stage 1: skip (loaded {len(stage1.get('clusters', []))} clusters from disk)")

    if from_stage <= 2:
        stage2 = stage2_cross_validate(cards, stage1, run_dir, passes=passes, model=model)
    else:
        stage2 = _read_stage(run_dir, "stage2_votes.json")
        safe_print(f"📂 Stage 2: skip (loaded {len(stage2.get('verdicts', []))} verdicts from disk)")

    if from_stage <= 3:
        stage3 = stage3_resolve(cards, stage2, run_dir, resolver=resolver,
                                include_low=include_low, allow_merge=allow_merge, model=model)
    else:
        stage3 = _read_stage(run_dir, "stage3_actions.json")
        safe_print(f"📂 Stage 3: skip (loaded {len(stage3.get('actions', []))} actions from disk)")

    stage4 = stage4_apply(db_manager, stage3, run_dir, apply=apply)

    safe_print(f"\n=== ✨ Dedup-Pipeline abgeschlossen (run_dir={run_dir.name}) ===")
    return stage4


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _write_stage(run_dir: Path, name: str, data: dict) -> None:
    path = run_dir / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _read_stage(run_dir: Path, name: str) -> dict:
    path = run_dir / name
    if not path.exists():
        raise FileNotFoundError(f"Stage output {name} not found in {run_dir}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _robust_json_loads(text: str) -> dict:
    """Parse JSON from an LLM response, tolerating invalid backslash escapes.

    LLMs frequently emit text like \\Sigma or \\frac inside JSON strings without
    properly escaping the backslash, which json.loads rejects. We retry after
    converting any \\X (where X is not a valid JSON escape char) to \\\\X.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', text)
        return json.loads(fixed)


def _parse_clusters_response(response: Any, n_cards: int) -> list[dict]:
    """Parse LLM JSON response, validate cluster member indices."""
    if not response:
        safe_print("⚠️ Stage-Detection: LLM-Antwort leer", "WARNING")
        return []
    try:
        text = response if isinstance(response, str) else json.dumps(response)
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip(), flags=re.MULTILINE)
        data = _robust_json_loads(cleaned.strip())
    except (json.JSONDecodeError, TypeError) as e:
        safe_print(f"⚠️ Stage-Detection: JSON-Parse fehlgeschlagen: {e}", "WARNING")
        return []
    raw_clusters = data.get("clusters", []) if isinstance(data, dict) else []
    valid_clusters = []
    for c in raw_clusters:
        if not isinstance(c, dict):
            continue
        members = c.get("members", [])
        if not isinstance(members, list) or len(members) < 2:
            continue
        members = sorted({m for m in members if isinstance(m, int) and 0 <= m < n_cards})
        if len(members) >= 2:
            valid_clusters.append({"members": members, "rationale": c.get("rationale", "")})
    return valid_clusters


def _parse_action_response(response: Any, members: list[int]) -> dict:
    """Parse LLM action JSON, fallback to skip on failure."""
    if not response:
        return {"action": "skip", "target_idx": None, "rationale": "LLM-Antwort leer"}
    try:
        text = response if isinstance(response, str) else json.dumps(response)
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip(), flags=re.MULTILINE)
        data = _robust_json_loads(cleaned.strip())
    except (json.JSONDecodeError, TypeError) as e:
        return {"action": "skip", "target_idx": None,
                "rationale": f"JSON-Parse fehlgeschlagen: {e}"}
    action = data.get("action", "skip")
    valid_actions = {"keep_oldest", "keep_newest", "keep_specific",
                     "merge_backs", "keep_all", "skip"}
    if action not in valid_actions:
        return {"action": "skip", "target_idx": None,
                "rationale": f"Ungueltige Aktion: {action}"}
    target_idx = data.get("target_idx")
    if action == "keep_specific":
        if not isinstance(target_idx, int) or target_idx not in members:
            return {"action": "skip", "target_idx": None,
                    "rationale": f"keep_specific aber target_idx={target_idx} ungueltig"}
    return {"action": action, "target_idx": target_idx,
            "rationale": data.get("rationale", "")}
