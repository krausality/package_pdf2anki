"""Tests for the post-hoc semantic dedup pipeline (real LLM, no mocks).

Skips when OPENROUTER_API_KEY is not set, to keep CI offline-safe.
"""

import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pdf2anki.text2anki.card import AnkiCard
from pdf2anki.text2anki.database_manager import DatabaseManager
from pdf2anki.text2anki.dedup import (
    run_dedup,
    stage1_detect_clusters,
    stage2_cross_validate,
    stage3_resolve,
    stage4_apply,
    _robust_json_loads,
)


pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="needs OPENROUTER_API_KEY for real LLM calls",
)


# ─────────────────────────────────────────────────────────────────────────────
# Test data: small crafted deck with 2 obvious dup pairs + 4 distinct cards
# ─────────────────────────────────────────────────────────────────────────────

def _make_test_cards():
    """6 cards: 2 pairs of obvious duplicates + 4 distinct concepts.

    Pair A: "Was ist ein Alphabet?" ≈ "Definiere ein Alphabet."
    Pair B: "Was ist ein DEA?" ≈ "Definiere einen deterministischen endlichen Automaten."
    Distinct: "Was ist ein NEA?", "Was ist eine Grammatik?",
              "Was ist eine kontextfreie Sprache?", "Was ist das Halteproblem?"
    """
    base = datetime(2026, 1, 1)
    return [
        AnkiCard(  # 0
            guid="aaaa-0",
            front="Was ist ein Alphabet?",
            back="Eine endliche, nichtleere Menge von Zeichen Σ.",
            collection="collection_0_basics", category="a_kern",
            sort_field="00_A_01", created_at=base + timedelta(days=1),
        ),
        AnkiCard(  # 1
            guid="bbbb-0",
            front="Definiere ein Alphabet.",
            back="Σ ist eine endliche, nichtleere Menge von Zeichen.",
            collection="collection_0_basics", category="a_kern",
            sort_field="00_A_02", created_at=base + timedelta(days=10),
        ),
        AnkiCard(  # 2
            guid="cccc-0",
            front="Was ist ein DEA?",
            back="Ein deterministischer endlicher Automat ist ein 5-Tupel (Q, Σ, δ, q₀, F) "
                 "mit δ: Q×Σ → Q total.",
            collection="collection_1_dea", category="a_kern",
            sort_field="01_A_01", created_at=base + timedelta(days=2),
        ),
        AnkiCard(  # 3
            guid="dddd-0",
            front="Definiere einen deterministischen endlichen Automaten.",
            back="DEA M = (Q, Σ, δ, q₀, F): Q endliche Zustandsmenge, δ totale "
                 "Übergangsfunktion, F ⊆ Q akzeptierende Zustände.",
            collection="collection_1_dea", category="a_kern",
            sort_field="01_A_02", created_at=base + timedelta(days=11),
        ),
        AnkiCard(  # 4
            guid="eeee-0",
            front="Was ist ein NEA?",
            back="Ein nichtdeterministischer endlicher Automat erlaubt mehrere "
                 "Folgezustände pro (Zustand, Eingabe).",
            collection="collection_1_dea", category="a_kern",
            sort_field="01_A_03", created_at=base + timedelta(days=3),
        ),
        AnkiCard(  # 5
            guid="ffff-0",
            front="Was ist das Halteproblem H?",
            back="H = {w | M_w hält auf w}. Klassisch unentscheidbar.",
            collection="collection_2_compute", category="a_kern",
            sort_field="02_A_01", created_at=base + timedelta(days=4),
        ),
    ]


def _make_db(tmp_path, cards) -> DatabaseManager:
    project_data = {
        "project_name": "DedupTest",
        "tag_prefix": "DT",
        "language": "de",
        "domain": "Theoretische Informatik",
        "orphan_collection_name": "Unsortiert",
        "files": {"db_path": "card_database.json",
                  "markdown_file": "fronts.md",
                  "new_cards_file": "new_cards.json"},
        "collections": {
            "collection_0_basics": {"display_name": "Basics",
                                    "filename": "collection_0_basics.json"},
            "collection_1_dea": {"display_name": "DEA/NEA",
                                 "filename": "collection_1_dea.json"},
            "collection_2_compute": {"display_name": "Berechenbarkeit",
                                     "filename": "collection_2_compute.json"},
        },
        "llm": {"model": "google/gemini-2.5-flash"},
    }
    (tmp_path / "project.json").write_text(json.dumps(project_data), encoding="utf-8")
    db_path = tmp_path / "card_database.json"
    db_path.write_text(
        json.dumps([c.to_dict() for c in cards], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    from pdf2anki.text2anki.project_config import ProjectConfig
    config = ProjectConfig.from_file(str(tmp_path))
    mock_mm = MagicMock()
    mock_mm.get_course_material.return_value = None
    return DatabaseManager(db_path=str(db_path), material_manager=mock_mm, project_config=config)


# ─────────────────────────────────────────────────────────────────────────────
# Robust JSON parser unit test (offline, no LLM)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(False, reason="offline unit test")
class TestRobustJsonLoads:
    def test_clean_json(self):
        assert _robust_json_loads('{"x": 1}') == {"x": 1}

    def test_invalid_backslash_escape_recovered(self):
        # \S is not a valid JSON escape; the parser should auto-fix it.
        bad = r'{"x": "hello \Sigma world"}'
        result = _robust_json_loads(bad)
        # The \\S becomes \S literal in the parsed string
        assert result == {"x": r"hello \Sigma world"}

    def test_valid_unicode_escape_preserved(self):
        # ä is valid; should not be doubled
        result = _robust_json_loads(r'{"x": "hällo"}')
        assert result == {"x": "hällo"}


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — real LLM detection
# ─────────────────────────────────────────────────────────────────────────────

class TestStage1Detection:
    def test_finds_obvious_duplicate_pairs(self, tmp_path):
        cards = _make_test_cards()
        db = _make_db(tmp_path, cards)
        run_dir = tmp_path / "dedup_run"
        run_dir.mkdir()

        result = stage1_detect_clusters(db.cards, run_dir)

        assert result["total_cards"] == 6
        # Must find at least one of the two known duplicate pairs
        clusters = result["clusters"]
        assert len(clusters) >= 1, f"Expected ≥1 cluster, got: {clusters}"

        # Check that at least one cluster contains the Alphabet pair (0, 1) OR DEA pair (2, 3)
        alphabet_pair = {0, 1}
        dea_pair = {2, 3}
        found_any = False
        for c in clusters:
            members = set(c["members"])
            if alphabet_pair.issubset(members) or dea_pair.issubset(members):
                found_any = True
                break
        assert found_any, f"Neither Alphabet nor DEA pair detected in clusters {clusters}"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — cross-validation aggregation
# ─────────────────────────────────────────────────────────────────────────────

class TestStage2CrossValidation:
    def test_3_pass_voting_produces_confidence_levels(self, tmp_path):
        cards = _make_test_cards()
        db = _make_db(tmp_path, cards)
        run_dir = tmp_path / "dedup_run"
        run_dir.mkdir()

        stage1 = stage1_detect_clusters(db.cards, run_dir)
        stage2 = stage2_cross_validate(db.cards, stage1, run_dir, passes=3)

        assert stage2["passes"] == 3
        # Verdicts must have valid confidence labels
        for v in stage2["verdicts"]:
            assert v["confidence"] in ("HIGH", "MEDIUM", "LOW")
            assert len(v["votes"]) == 3

        # We expect at least one HIGH-confidence pair (one of the 2 obvious dups
        # should survive all 3 passes).
        high_pairs = [v for v in stage2["verdicts"] if v["confidence"] == "HIGH"]
        assert len(high_pairs) >= 1, \
            f"Expected ≥1 HIGH pair from 2 known dups, got: {stage2['verdicts']}"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — auto-resolver action format
# ─────────────────────────────────────────────────────────────────────────────

class TestStage3AutoResolver:
    def test_auto_resolver_emits_valid_actions(self, tmp_path):
        cards = _make_test_cards()
        db = _make_db(tmp_path, cards)
        run_dir = tmp_path / "dedup_run"
        run_dir.mkdir()

        stage1 = stage1_detect_clusters(db.cards, run_dir)
        stage2 = stage2_cross_validate(db.cards, stage1, run_dir, passes=3)
        stage3 = stage3_resolve(db.cards, stage2, run_dir, resolver="auto")

        valid_actions = {"keep_oldest", "keep_newest", "keep_specific",
                         "merge_backs", "keep_all", "skip"}
        for action in stage3["actions"]:
            assert action["action"] in valid_actions
            assert "rationale" in action
            assert "confidence" in action
            assert "member_guids" in action


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4 — apply with backup + rollback
# ─────────────────────────────────────────────────────────────────────────────

class TestStage4Apply:
    def test_dry_run_writes_summary_does_not_modify_db(self, tmp_path):
        cards = _make_test_cards()
        db = _make_db(tmp_path, cards)
        run_dir = tmp_path / "dedup_run"
        run_dir.mkdir()

        original_count = len(db.cards)
        stage1 = stage1_detect_clusters(db.cards, run_dir)
        stage2 = stage2_cross_validate(db.cards, stage1, run_dir, passes=3)
        stage3 = stage3_resolve(db.cards, stage2, run_dir, resolver="auto")
        stage4 = stage4_apply(db, stage3, run_dir, apply=False)

        assert stage4["applied"] is False
        assert stage4["backup_path"] is None
        # DB must be untouched
        on_disk = json.loads(Path(db.db_path).read_text(encoding="utf-8"))
        assert len(on_disk) == original_count
        # stage4_applied.json was written
        assert (run_dir / "stage4_applied.json").exists()

    def test_apply_creates_backup_and_removes_duplicates(self, tmp_path):
        cards = _make_test_cards()
        db = _make_db(tmp_path, cards)
        run_dir = tmp_path / "dedup_run"
        run_dir.mkdir()

        original_count = len(db.cards)
        stage1 = stage1_detect_clusters(db.cards, run_dir)
        stage2 = stage2_cross_validate(db.cards, stage1, run_dir, passes=3)
        stage3 = stage3_resolve(db.cards, stage2, run_dir, resolver="auto")
        stage4 = stage4_apply(db, stage3, run_dir, apply=True)

        assert stage4["applied"] is True
        if stage4["guids_to_remove"]:
            assert stage4["backup_path"] is not None
            assert Path(stage4["backup_path"]).exists()
            # Backup should equal original card count
            backup_data = json.loads(Path(stage4["backup_path"]).read_text(encoding="utf-8"))
            assert len(backup_data) == original_count
            # Live DB should be smaller now
            live_data = json.loads(Path(db.db_path).read_text(encoding="utf-8"))
            assert len(live_data) == original_count - len(stage4["guids_to_remove"])
        # Distinct cards (NEA, Halteproblem) must always survive
        live_data = json.loads(Path(db.db_path).read_text(encoding="utf-8"))
        live_fronts = {c["front"] for c in live_data}
        assert "Was ist ein NEA?" in live_fronts
        assert "Was ist das Halteproblem H?" in live_fronts

    def test_apply_auto_distributes_to_derived_files(self, tmp_path):
        """After --apply, collection_*.json and the markdown index must reflect
        the new card count without a separate --sync invocation."""
        cards = _make_test_cards()
        db = _make_db(tmp_path, cards)
        run_dir = tmp_path / "dedup_run"
        run_dir.mkdir()

        stage1 = stage1_detect_clusters(db.cards, run_dir)
        stage2 = stage2_cross_validate(db.cards, stage1, run_dir, passes=3)
        stage3 = stage3_resolve(db.cards, stage2, run_dir, resolver="auto")
        stage4 = stage4_apply(db, stage3, run_dir, apply=True)

        if not stage4["guids_to_remove"]:
            pytest.skip("LLM didn't flag any duplicates this run; nothing to verify.")

        assert stage4.get("distributed") is True

        live_db = json.loads(Path(db.db_path).read_text(encoding="utf-8"))
        live_count = len(live_db)

        # Sum cards across all collection_*.json files; must equal live DB
        collection_files = list(tmp_path.glob("collection_*.json"))
        assert collection_files, "No derived collection files found after apply"
        total = sum(
            len(json.loads(f.read_text(encoding="utf-8")))
            for f in collection_files
        )
        assert total == live_count, (
            f"Derived collection files have {total} cards but live DB has {live_count}"
        )

        # Markdown index must exist and reference live cards (not stale ones).
        # Filename comes from distribute_to_derived_files (currently always
        # "All_collections_only_fronts.md" regardless of project_config).
        md_candidates = list(tmp_path.glob("*.md"))
        assert md_candidates, "No markdown file produced by distribute"
        md = md_candidates[0].read_text(encoding="utf-8")
        for c in live_db:
            assert c["front"] in md, f"Live card '{c['front']}' missing from markdown"


# ─────────────────────────────────────────────────────────────────────────────
# E2E: run_dedup top-level entry
# ─────────────────────────────────────────────────────────────────────────────

class TestRunDedupE2E:
    def test_full_pipeline_dry_run(self, tmp_path):
        cards = _make_test_cards()
        db = _make_db(tmp_path, cards)

        result = run_dedup(db, passes=3, resolver="auto", apply=False)

        # Find the run_dir that was created
        run_dirs = list(Path(db.db_path).parent.glob("dedup_run_*"))
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]
        # All 4 stage files exist
        for stage_file in ("stage1_clusters.json", "stage2_votes.json",
                           "stage3_actions.json", "stage4_applied.json"):
            assert (run_dir / stage_file).exists(), f"missing {stage_file}"
        # Dry-run did not modify DB
        on_disk = json.loads(Path(db.db_path).read_text(encoding="utf-8"))
        assert len(on_disk) == 6

    def test_resume_from_stage_3(self, tmp_path):
        """If stages 1+2 already produced output, --from-stage 3 reuses them."""
        cards = _make_test_cards()
        db = _make_db(tmp_path, cards)

        # First run: produces all 4 stages
        run_dedup(db, passes=3, resolver="auto", apply=False)
        run_dirs = list(Path(db.db_path).parent.glob("dedup_run_*"))
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]

        # Snapshot stage 1+2
        stage1_before = json.loads((run_dir / "stage1_clusters.json").read_text(encoding="utf-8"))
        stage2_before = json.loads((run_dir / "stage2_votes.json").read_text(encoding="utf-8"))

        # Resume from stage 3 — should NOT modify stages 1+2
        run_dedup(db, run_dir=run_dir, passes=3, resolver="auto",
                  from_stage=3, apply=False)

        stage1_after = json.loads((run_dir / "stage1_clusters.json").read_text(encoding="utf-8"))
        stage2_after = json.loads((run_dir / "stage2_votes.json").read_text(encoding="utf-8"))

        assert stage1_before == stage1_after
        assert stage2_before == stage2_after
