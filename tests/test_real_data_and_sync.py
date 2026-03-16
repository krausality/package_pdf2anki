"""
test_real_data_and_sync.py — Tests based on real GTI course material patterns
and missing workflow coverage.

Gaps addressed:
1. Real OCR content patterns extracted from actual GTI files
   (skript-1.txt, Uebungsblatt01.txt, mitschrift_tutorium01.txt)
2. sync_from_ssot() and run_sync_workflow() — not covered in other test files
3. run_smart_extract_workflow() routing logic
4. Temporal multi-ingestion simulation (student adds cards week-by-week)
5. collection=None assertion for ApkgExporter

Patterns found in real GTI OCR output:
- <math>...</math> tags with nested { } that look like JSON
- [Visual Description: ...] — image captions, 100-300 chars long
- Image: page_N.png — page markers
- LaTeX commands: \\vfill, \\hfil, \\begin{array}{lcl}...\\end{array}
- &nbsp; HTML entities
- --- page separators
- *Handwritten Comment:* mixed markdown
- Unicode: ε, Σ, ∈, ℕ, ℤ, ∅, →, ⊆, ⊇, ∪, ∩, Δ
- Formal grammar G = ({A, b, B}, {a,b}, {...}, S) — nested braces
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pdf2anki.text2anki.card import AnkiCard
from pdf2anki.text2anki.database_manager import DatabaseManager
from pdf2anki.text2anki.project_config import ProjectConfig
from pdf2anki.text2anki.text_ingester import TextFileIngestor, ingest_text
from pdf2anki.text2anki.apkg_exporter import ApkgExporter


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

GTI_PROJECT_DATA = {
    "project_name": "GTI_WiSe2526",
    "tag_prefix": "GTI",
    "language": "de",
    "domain": "Grundlagen der Theoretischen Informatik",
    "orphan_collection_name": "Unsortierte_Karten",
    "files": {
        "db_path": "card_database.json",
        "markdown_file": "All_fronts.md",
        "new_cards_file": "new_cards_output.json",
        "material_file": "course_material.txt",
    },
    "collections": {
        "collection_0_Sprachen": {
            "display_name": "Kapitel 1: Sprachen und Grammatiken",
            "filename": "collection_0_Sprachen.json",
        },
        "collection_1_RegEx": {
            "display_name": "Kapitel 3: Reguläre Sprachen",
            "filename": "collection_1_RegEx.json",
        },
        "collection_2_Turing": {
            "display_name": "Kapitel 7: Turingmaschinen",
            "filename": "collection_2_Turing.json",
        },
    },
    "llm": {"model": "google/gemini-2.5-flash", "temperature": 0.1},
}

# ── Verbatim snippets extracted from real GTI OCR files ──────────────────────
# From: skript-1.txt (LaTeX-typeset lecture script, OCR'd)
REAL_SKRIPT_SNIPPET = """\
Image: page_3.png
*Grundlagen der Theoretischen Informatik* \\hfill *1 Sprachen und Grammatiken*

---

# 1 Sprachen und Grammatiken

Ein *Alphabet* ist eine endliche, nichtleere Menge. Die Elemente eines Alphabets heißen auch *Zeichen* oder *Symbole*.

> **Beispiel 1.** <math>\\{0, 1\\}, \\{\\text{a, b, c, \\dots, z, A, \\dots, Z}\\}</math>

Sei <math>\\Sigma</math> ein Alphabet. Ein *Wort über* <math>\\Sigma</math> ist eine Folge von Symbolen.

Spezialfall: leeres Wort; Bezeichnung: <math>\\varepsilon</math>

Die Menge aller Wörter über dem Alphabet <math>\\Sigma</math> bezeichnen wir mit <math>\\Sigma^*</math>.

\\vfill
<center>3</center>
"""

# From: Uebungsblatt01.txt (exercise sheet, OCR'd)
REAL_UEBUNG_SNIPPET = """\
Image: page_1.png
# 1. Übungsblatt
Woche vom 20. Oktober 2025

**Aufgabe 1:**
a) Welche der folgenden Behauptungen sind korrekt?
- Die Menge der ganzen Zahlen <math>\\mathbb{Z}</math> ist ein Alphabet.
- <math>\\Sigma^+ \\cup \\{ \\varepsilon \\} = \\Sigma^*</math>, für jedes Alphabet <math>\\Sigma</math>.
- Sind <math>a, b \\in \\Sigma</math>, <math>w_1 = abba</math> und <math>w_2 = \\varepsilon</math>. Dann ist <math>|w_1 w_2| = 5</math>
- <math>G = (\\{A, b, B, c, S\\}, \\{a, b\\}, \\{S \\rightarrow AB, B \\rightarrow b\\}, S)</math> ist eine gültige Grammatik.
"""

# From: mitschrift_tutorium01.txt (handwritten solutions, OCR'd)
REAL_MITSCHRIFT_SNIPPET = """\
Image: page_1.png
# Aufgabe 1
[Visual Description: Header with the text "Aufgabe 1" on the left and a blue rectangular badge on the right containing "Skript Kapitel 1 und 2" in white text.]

[Visual Description: A checkbox marked with a large "X" to indicate it is incorrect.]
Die Menge der ganzen Zahlen <math>\\mathbb{Z}</math> ist ein Alphabet.
*Handwritten Comment:* Widerspruch zur Endlichkeit

[Visual Description: A checkbox marked with a tick/checkmark to indicate it is correct.]
<math>\\Sigma^+ \\cup \\{\\varepsilon\\} = \\Sigma^*</math> für jedes Alphabet <math>\\Sigma</math>.
*Handwritten Comment:* genau die Def. <math>\\Sigma^+ = \\Sigma^* \\setminus \\{\\varepsilon\\}</math>

<math>G = (\\{A, \\underline{b}, B, c, S\\}, \\{a, b\\}, \\{S \\to AB, B \\to b, B \\to AA, b \\to cc, A \\to ab\\}, S)</math>
*Handwritten Comment:* <math>V \\cap \\Sigma = \\{b\\} \\neq \\emptyset</math>

---

b) Sei <math>\\Delta</math> ein Alphabet. Wie viele Wörter <math>w \\in \\Delta^*</math> der Länge <math>|w| = k</math> gibt es?
<math>|\\Delta|^k</math>
"""


def make_gti_project(tmp_path) -> Path:
    project_dir = tmp_path / "gti_project"
    project_dir.mkdir()
    (project_dir / "project.json").write_text(
        json.dumps(GTI_PROJECT_DATA), encoding="utf-8"
    )
    return project_dir


def make_db(base_path, cards=None, config=None) -> DatabaseManager:
    mock_mm = MagicMock()
    mock_mm.get_course_material.return_value = None
    db_path = str(Path(base_path) / "card_database.json")
    if cards is not None:
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in cards], f)
    return DatabaseManager(db_path=db_path, material_manager=mock_mm, project_config=config)


def make_card(**kwargs) -> AnkiCard:
    defaults = dict(
        front="Was ist ein Alphabet?",
        back="Eine endliche, nichtleere Menge.",
        collection="collection_0_Sprachen",
        category="a_grundlagen",
        sort_field="00_A_01_was_ist_ein_alphabet",
    )
    defaults.update(kwargs)
    return AnkiCard(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 1: Real OCR Content Patterns
# ─────────────────────────────────────────────────────────────────────────────

class TestRealOcrContentPatterns:
    """
    Characterization tests for DatabaseManager transformation logic using real GTI
    OCR content patterns (skript-1.txt, Uebungsblatt01.txt, mitschrift_tutorium01.txt).

    Phase 1 observation methodology: each transformation was run interactively against
    actual GTI strings. The outputs recorded here ARE the observed behavior of the
    system. Docstrings follow the format "Input X → observed output Y".
    """

    # ─── _normalize_for_key ──────────────────────────────────────────────────

    def test_normalize_for_key_german_chapter_heading(self, tmp_path):
        """
        Input 'Kapitel 1: Sprachen und Grammatiken' → 'kapitel_1_sprachen_und_grammatiken'.
        Colons and spaces both become underscores after lowercasing.
        Observed: colon is stripped (not-alphanum), adjacent underscores remain.
        """
        db = make_db(tmp_path)
        result = db._normalize_for_key("Kapitel 1: Sprachen und Grammatiken")
        assert result == "kapitel_1_sprachen_und_grammatiken"

    def test_normalize_for_key_umlaut_expansion(self, tmp_path):
        """
        Input 'Reguläre Sprachen' → 'regulaere_sprachen'.
        'ä' is replaced by 'ae' (not deleted), then space → underscore.
        Observed: ä→ae, ö→oe, ü→ue, ß→ss (expansion, not deletion).
        """
        db = make_db(tmp_path)
        assert db._normalize_for_key("Reguläre Sprachen") == "regulaere_sprachen"
        assert db._normalize_for_key("Übungsblatt 1") == "uebungsblatt_1"
        assert db._normalize_for_key("Äquivalenzklassen") == "aequivalenzklassen"

    def test_normalize_for_key_ampersand_becomes_und(self, tmp_path):
        """
        Input 'Äquivalenz & Minimalautomaten' → 'aequivalenz_und_minimalautomaten'.
        '&' is replaced by 'und' (the German word), not 'and'.
        Observed: the umlaut_map contains '&': 'und'.
        """
        db = make_db(tmp_path)
        result = db._normalize_for_key("Äquivalenz & Minimalautomaten")
        assert result == "aequivalenz_und_minimalautomaten"

    def test_normalize_for_key_parens_stripped(self, tmp_path):
        """
        Input 'Kellerautomaten (PDA)' → 'kellerautomaten_pda'.
        Parentheses are stripped as illegal characters; content inside survives.
        Observed: ( and ) removed, space→_, PDA lowercased.
        """
        db = make_db(tmp_path)
        result = db._normalize_for_key("Kellerautomaten (PDA)")
        assert result == "kellerautomaten_pda"

    def test_normalize_for_key_math_notation_stripped_to_alphanum(self, tmp_path):
        """
        Input r'\\Sigma^* (Kleene-Stern)' → 'sigma_kleenestern'.
        Backslash, caret, hyphen are all non-alphanum → stripped.
        The 'Sigma' prefix survives as 'sigma'. The hyphen in 'Kleene-Stern' is
        stripped, merging the two words: 'kleene' + 'stern' → 'kleenestern'.
        Observed exact output: 'sigma_kleenestern'.
        """
        db = make_db(tmp_path)
        result = db._normalize_for_key(r"\Sigma^* (Kleene-Stern)")
        assert result == "sigma_kleenestern"

    def test_normalize_for_key_pure_unicode_math_symbols_produce_empty(self, tmp_path):
        """
        Input 'ε, Σ, ∈, ℕ, ∅' → ''.
        Unicode math symbols are stripped; stray underscores from commas/spaces are
        collapsed and stripped, yielding empty string.
        """
        db = make_db(tmp_path)
        result = db._normalize_for_key("ε, Σ, ∈, ℕ, ∅")
        assert result == ""

    def test_normalize_for_key_empty_and_whitespace_only_produce_empty_string(self, tmp_path):
        """
        Input '' → ''. Input '   ' → ''.
        Empty string and whitespace-only both produce empty string.
        Observed: strip().lower() removes whitespace; re.sub then yields ''.
        """
        db = make_db(tmp_path)
        assert db._normalize_for_key("") == ""
        assert db._normalize_for_key("   ") == ""

    def test_normalize_for_key_punctuation_only_produces_empty_string(self, tmp_path):
        """
        Input '!!!' → ''. Input '---' → ''. Input '...' → ''.
        OCR artifacts like page separators (---) or emphasis marks (!!!) produce
        empty keys — all characters are stripped as non-alphanum.
        Observed: all three inputs map to ''.
        """
        db = make_db(tmp_path)
        assert db._normalize_for_key("!!!") == ""
        assert db._normalize_for_key("---") == ""
        assert db._normalize_for_key("...") == ""

    def test_normalize_for_key_grammar_tuple_notation(self, tmp_path):
        """
        Input 'G = ({A, b, B}, {a,b}, {S->AB}, S)' → 'g_a_b_b_ab_sab_s'.
        From real GTI Uebungsblatt01.txt. Braces/arrows/commas stripped; consecutive
        underscores from adjacent removed chars are collapsed to single underscore.
        """
        db = make_db(tmp_path)
        result = db._normalize_for_key("G = ({A, b, B}, {a,b}, {S->AB}, S)")
        assert result == "g_a_b_b_ab_sab_s"

    # ─── _normalize_text ─────────────────────────────────────────────────────

    def test_normalize_text_collapses_whitespace_only(self, tmp_path):
        """
        Input 'Was  ist  ein  Alphabet?' → 'was ist ein alphabet?'.
        _normalize_text: only lowercases and collapses whitespace runs to single space.
        Observed: does NOT strip special chars, umlauts, or math tags.
        """
        db = make_db(tmp_path)
        result = db._normalize_text("Was  ist  ein  Alphabet?")
        assert result == "was ist ein alphabet?"

    def test_normalize_text_preserves_math_tags_and_backslashes(self, tmp_path):
        """
        Input r'Was ist <math>\\Sigma^*</math>?' → r'was ist <math>\\sigma^*</math>?'.
        _normalize_text lowercases everything including the S in \\Sigma → \\sigma.
        It does NOT strip <math> tags, backslashes, or carets.
        Observed: tags and special chars survive, only case is folded.
        """
        db = make_db(tmp_path)
        result = db._normalize_text(r"Was ist <math>\Sigma^*</math>?")
        assert result == r"was ist <math>\sigma^*</math>?"

    def test_normalize_text_preserves_german_umlauts(self, tmp_path):
        """
        Input 'Reguläre Sprachen' → 'reguläre sprachen'.
        Unlike _normalize_for_key, _normalize_text does NOT expand umlauts.
        ä stays as ä (just lowercased). ü stays as ü.
        Observed: umlauts are NOT transliterated by _normalize_text.
        """
        db = make_db(tmp_path)
        assert db._normalize_text("Reguläre Sprachen") == "reguläre sprachen"
        assert db._normalize_text("Übungsblatt 01") == "übungsblatt 01"

    def test_normalize_text_greek_uppercase_folds_to_lowercase(self, tmp_path):
        """
        Input 'Was ist Σ?' → 'was ist σ?'. Input 'Was ist σ?' → 'was ist σ?'.
        Python's str.lower() maps Σ (U+03A3) → σ (U+03C3).
        Both inputs produce the same normalized form — treated as duplicates.
        Observed: this is how integrate_new deduplication works for GTI Greek symbols.
        """
        db = make_db(tmp_path)
        assert db._normalize_text("Was ist Σ?") == "was ist σ?"
        assert db._normalize_text("Was ist σ?") == "was ist σ?"

    def test_normalize_text_grammar_case_collision(self, tmp_path):
        """
        Input r'G = (\\{A, b\\}, P, S)' and r'G = (\\{a, b\\}, P, S)'
        both normalize to r'g = (\\{a, b\\}, p, s)'.
        The uppercase 'A' in the grammar's variable set becomes lowercase 'a',
        colliding with a grammar that uses lowercase 'a' in the same position.
        Observed: integrate_new treats these as duplicates.
        """
        db = make_db(tmp_path)
        na = db._normalize_text(r"G = (\{A, b\}, P, S)")
        nb = db._normalize_text(r"G = (\{a, b\}, P, S)")
        assert na == nb
        assert na == r"g = (\{a, b\}, p, s)"

    # ─── _generate_sort_field ────────────────────────────────────────────────

    def test_generate_sort_field_plain_german_front(self, tmp_path):
        """
        sort_key='00_A_01', front='Was ist ein Alphabet?'
        → '00_A_01_was_ist_ein_alphabet'.
        The question mark is stripped as non-alphanum. Spaces become underscores.
        Observed exact output.
        """
        db = make_db(tmp_path)
        result = db._generate_sort_field("00_A_01", "Was ist ein Alphabet?")
        assert result == "00_A_01_was_ist_ein_alphabet"

    def test_generate_sort_field_math_tags_stripped_to_content(self, tmp_path):
        """
        sort_key='00_A_02', front=r'Was ist <math>\\Sigma^*</math>?'
        → '00_A_02_was_ist_mathsigmamath'.
        The < > / ^ * chars are all stripped; 'math' appears twice (opening+closing tag).
        'Sigma' from \\Sigma survives (backslash stripped), lowercased.
        Observed: angle brackets and backslash removed, tag text 'math' stays.
        """
        db = make_db(tmp_path)
        result = db._generate_sort_field("00_A_02", r"Was ist <math>\Sigma^*</math>?")
        assert result == "00_A_02_was_ist_mathsigmamath"

    def test_generate_sort_field_multiple_similar_math_fronts_stay_unique(self, tmp_path):
        """
        r'Was ist <math>\\Sigma^*</math>?', r'Was ist <math>|\\Sigma|</math>?',
        and r'Was ist <math>\\Sigma^+</math>?' all produce sort_field suffixes
        'was_ist_mathsigmamath' after stripping math/special chars.
        The sort_key prefix (00_A_01, 00_A_02, 00_A_03) keeps them globally unique.
        Observed: three cards with identical normalized front-suffixes but unique
        sort_fields due to different positional prefixes.
        """
        db = make_db(tmp_path)
        sf1 = db._generate_sort_field("00_A_01", r"Was ist <math>\Sigma^*</math>?")
        sf2 = db._generate_sort_field("00_A_02", r"Was ist <math>|\Sigma|</math>?")
        sf3 = db._generate_sort_field("00_A_03", r"Was ist <math>\Sigma^+</math>?")
        # All three have the same suffix (after stripping special chars)
        assert sf1.endswith("_was_ist_mathsigmamath")
        assert sf2.endswith("_was_ist_mathsigmamath")
        assert sf3.endswith("_was_ist_mathsigmamath")
        # But the full sort_fields are unique due to different prefixes
        assert len({sf1, sf2, sf3}) == 3

    def test_generate_sort_field_long_front_truncated_at_50_chars(self, tmp_path):
        """
        sort_key='00_A_04', front='Was ist die Kleene-Hülle eines Alphabets Σ und wie wird sie formal notiert?'
        Now uses _normalize_for_key: ü expands to 'ue' (kleenehuelle), Σ stripped then
        underscore cleaned (alphabets_und). Result truncated to 50 chars.
        """
        db = make_db(tmp_path)
        front = "Was ist die Kleene-Hülle eines Alphabets Σ und wie wird sie formal notiert?"
        result = db._generate_sort_field("00_A_04", front)
        assert result == "00_A_04_was_ist_die_kleenehuelle_eines_alphabets_und_wie_w"
        # Exactly 50 chars in the front portion after the sort_key prefix
        front_part = result[len("00_A_04_"):]
        assert len(front_part) == 50

    def test_generate_sort_field_grammar_tuple_front(self, tmp_path):
        """
        sort_key='01_B_02', front=r'G = (\\{A, b, B, c, S\\}, \\{a, b\\}, \\{S \\to AB, B \\to b\\}, S) — gültig?'
        Now uses _normalize_for_key: ü expands to 'ue' (gueltig), consecutive underscores
        from adjacent stripped chars are collapsed. Result: '01_B_02_g_a_b_b_c_s_a_b_s_to_ab_b_to_b_s_gueltig'.
        """
        db = make_db(tmp_path)
        front = r"G = (\{A, b, B, c, S\}, \{a, b\}, \{S \to AB, B \to b\}, S) — gültig?"
        result = db._generate_sort_field("01_B_02", front)
        assert result.startswith("01_B_02_g_a_b_b_c_s_a_b_s_to_ab_b_to_b_s_gueltig")

    def test_generate_sort_field_umlaut_in_front_expanded(self, tmp_path):
        """
        sort_key='02_A_02', front='Erkläre den Unterschied zwischen Σ+ und Σ*'
        → '02_A_02_erklaere_den_unterschied_zwischen_und'.
        _generate_sort_field now uses _normalize_for_key: ä expands to 'ae',
        Σ stripped and stray underscores cleaned.
        """
        db = make_db(tmp_path)
        result = db._generate_sort_field("02_A_02", "Erkläre den Unterschied zwischen Σ+ und Σ*")
        assert result == "02_A_02_erklaere_den_unterschied_zwischen_und"

    # ─── _generate_tags ──────────────────────────────────────────────────────

    def test_generate_tags_standard_gti_collection_and_category(self, tmp_path):
        """
        collection='collection_0_Sprachen', category='a_grundlagen'
        → tag uses all key parts capitalized.
        """
        db = make_db(tmp_path)
        db._tag_prefix = "GTI"
        result = db._generate_tags("collection_0_Sprachen", "a_grundlagen")
        assert result == ["GTI::Collection_0_Sprachen::A_Grundlagen"]

    def test_generate_tags_new_cards_collection_from_integrate_new(self, tmp_path):
        """
        After integrate_new() on an empty DB, collection='collection_0_Neue_Karten',
        category='a_Unsortiert' → all key parts capitalized.
        """
        db = make_db(tmp_path)
        db._tag_prefix = "GTI"
        result = db._generate_tags("collection_0_Neue_Karten", "a_Unsortiert")
        assert result == ["GTI::Collection_0_Neue_Karten::A_Unsortiert"]

    def test_generate_tags_multi_word_collection_and_category(self, tmp_path):
        """
        collection='collection_0_sprachen_und_grammatiken', category='c_normalformen'
        → all parts capitalized.
        """
        db = make_db(tmp_path)
        db._tag_prefix = "GTI"
        result = db._generate_tags("collection_0_sprachen_und_grammatiken", "c_normalformen")
        assert result == ["GTI::Collection_0_Sprachen_Und_Grammatiken::C_Normalformen"]

    def test_generate_tags_high_collection_number(self, tmp_path):
        """
        collection='collection_10_XYZ', category='z_last'
        → capitalize() lowercases all but first char — 'XYZ' → 'Xyz'.
        """
        db = make_db(tmp_path)
        db._tag_prefix = "GTI"
        result = db._generate_tags("collection_10_XYZ", "z_last")
        assert result == ["GTI::Collection_10_Xyz::Z_Last"]

    def test_generate_tags_nonstandard_key_produces_valid_tag(self, tmp_path):
        """
        Non-standard keys like 'Skript_ws_25' produce valid hierarchical tags
        instead of falling back to Unkategorisiert.
        """
        db = make_db(tmp_path)
        db._tag_prefix = "GTI"
        result = db._generate_tags("Skript_ws_25", "a_grundlagen")
        assert result == ["GTI::Skript_Ws_25::A_Grundlagen"]

    def test_generate_tags_single_part_key_produces_valid_tag(self, tmp_path):
        """
        Single-part key 'Sprachen' produces a valid tag, not Unkategorisiert.
        """
        db = make_db(tmp_path)
        db._tag_prefix = "GTI"
        result = db._generate_tags("Sprachen", "grundlagen")
        assert result == ["GTI::Sprachen::Grundlagen"]

    def test_generate_tags_anki_prefix_when_no_project_config(self, tmp_path):
        """
        Without a ProjectConfig, tag_prefix defaults to 'ANKI'.
        """
        db = make_db(tmp_path)
        # make_db creates DB without project_config → _tag_prefix = 'ANKI'
        result = db._generate_tags("collection_0_Neue_Karten", "a_Unsortiert")
        assert result == ["ANKI::Collection_0_Neue_Karten::A_Unsortiert"]

    # ─── integrate_new — collection assignment and numbering ─────────────────

    def test_integrate_new_empty_db_assigns_collection_0(self, tmp_path):
        """
        Integrating into an empty DB → all cards land in 'collection_0_Neue_Karten'.
        The collection number is max(existing_collection_nums) + 1. With no existing
        cards, max is -1, so new_coll_num = 0.
        Observed: collection_key = 'collection_0_Neue_Karten', category = 'a_Unsortiert'.
        """
        db = make_db(tmp_path)
        db.integrate_new([
            {"front": "Was ist ein Alphabet?", "back": "Endliche nichtleere Menge."},
        ])
        assert db.cards[0].collection == "collection_0_Neue_Karten"
        assert db.cards[0].category == "a_Unsortiert"

    def test_integrate_new_second_batch_increments_collection_number(self, tmp_path):
        """
        First batch → collection_0_Neue_Karten. Second batch → collection_1_Neue_Karten.
        Each call to integrate_new() computes max(existing collection numbers) + 1.
        Observed: second batch uses coll_num=1 because first batch cards have coll_num=0.
        """
        db = make_db(tmp_path)
        db.integrate_new([{"front": "Was ist ein Alphabet?", "back": "Endliche Menge."}])
        db.integrate_new([{"front": "Was ist eine formale Sprache?", "back": "Teilmenge von Σ*."}])
        colls = [c.collection for c in db.cards]
        assert "collection_0_Neue_Karten" in colls
        assert "collection_1_Neue_Karten" in colls

    def test_integrate_new_sort_field_uses_batch_index_as_position(self, tmp_path):
        """
        For 15 GTI cards in one batch, sort_fields are:
        '00_A_01_<front1_normalized>', '00_A_02_<front2_normalized>', etc.
        The batch index i (0-based) becomes i+1 in the sort_key: 'NN_A_{i+1:02d}'.
        Observed: first card → ...01..., fifteenth card → ...15...
        """
        db = make_db(tmp_path)
        gti_batch = [
            {"front": f"Was ist Begriff {i}?", "back": f"Antwort {i}."}
            for i in range(1, 16)
        ]
        db.integrate_new(gti_batch)
        assert len(db.cards) == 15
        assert db.cards[0].sort_field.startswith("00_A_01_")
        assert db.cards[14].sort_field.startswith("00_A_15_")

    def test_integrate_new_deduplication_uses_normalize_text_not_normalize_for_key(self, tmp_path):
        """
        Deduplication key = _normalize_text(front): lowercases + collapses whitespace.
        'Was ist <math>\\Sigma^*</math>?' (first batch) and
        'was ist <math>\\sigma^*</math>?' (second batch, already lowercase) both
        normalize to 'was ist <math>\\sigma^*</math>?' → treated as duplicate.
        Observed: second batch returns count=0.
        """
        db = make_db(tmp_path)
        db.integrate_new([{
            "front": r"Was ist <math>\Sigma^*</math>?",
            "back": "Kleene-Hülle.",
        }])
        count = db.integrate_new([{
            "front": r"Was ist <math>\Sigma^*</math>?",
            "back": "Alle Wörter über Sigma.",
        }])
        assert count == 0

    def test_integrate_new_whitespace_normalized_duplicate_rejected(self, tmp_path):
        """
        'Ist  <math>\\mathbb{Z}</math>  ein  Alphabet?' (extra spaces) normalizes
        to the same key as 'Ist <math>\\mathbb{Z}</math> ein Alphabet?' (single spaces).
        _normalize_text collapses all whitespace runs to single space.
        Observed: integrate_new returns 0 for the whitespace-variant.
        """
        db = make_db(tmp_path)
        db.integrate_new([{
            "front": r"Ist <math>\mathbb{Z}</math> ein Alphabet?",
            "back": "Nein, unendlich.",
        }])
        count = db.integrate_new([{
            "front": r"Ist  <math>\mathbb{Z}</math>  ein  Alphabet?",
            "back": "Nein.",
        }])
        assert count == 0
        assert len(db.cards) == 1

    def test_integrate_new_greek_uppercase_lowercase_collision(self, tmp_path):
        """
        'Was ist Σ?' and 'Was ist σ?' are treated as duplicates because
        Python's str.lower() maps Σ (U+03A3) → σ (U+03C3).
        Both normalize to 'was ist σ?'. The second card is silently rejected.
        Observed: integrate_new returns 0 for 'Was ist σ?' after 'Was ist Σ?' exists.
        A genuinely different Greek letter (δ) is NOT a duplicate.
        """
        db = make_db(tmp_path)
        db.integrate_new([{"front": "Was ist Σ?", "back": "Das Eingabealphabet."}])
        count_sigma_lower = db.integrate_new([{"front": "Was ist σ?", "back": "Kleines Sigma."}])
        count_delta = db.integrate_new([{"front": "Was ist δ?", "back": "Übergangsfunktion."}])
        assert count_sigma_lower == 0
        assert count_delta == 1

    def test_integrate_new_skips_cards_with_empty_front_or_back(self, tmp_path):
        """
        Cards with empty front or empty back are silently skipped.
        OCR can produce blank segments that become empty strings after strip().
        Observed: integrate_new returns 0 for {front='', back='...'} and
        {front='Was ist X?', back=''}, even if mixed with valid cards.
        """
        db = make_db(tmp_path)
        count = db.integrate_new([
            {"front": "", "back": "Eine Antwort."},
            {"front": "Was ist ein Alphabet?", "back": ""},
            {"front": "Was ist ein Alphabet?", "back": "Endliche Menge."},
        ])
        assert count == 1
        assert db.cards[0].front == "Was ist ein Alphabet?"

    # ─── _generate_markdown_card_list ────────────────────────────────────────

    def test_generate_markdown_card_list_structure_with_gti_cards(self, tmp_path):
        """
        After integrating 5 GTI cards into an empty DB, _generate_markdown_card_list()
        produces a markdown string with:
        - '<!-- COLLECTION_0_START -->' and '<!-- COLLECTION_0_END -->' markers
        - '<!-- CARDS_START -->' and '<!-- CARDS_END -->' markers
        - '**A. Unsortiert**' category header (category_key='a_Unsortiert')
        - Numbered card fronts: '1. <front>', '2. <front>', etc.
        Observed: the exact structure produced for a fresh integrate_new() batch.
        """
        db = make_db(tmp_path)
        db.integrate_new([
            {"front": "Was ist ein Alphabet?", "back": "Endliche nichtleere Menge."},
            {"front": r"Was ist <math>\Sigma^*</math>?", "back": "Kleene-Hülle."},
            {"front": r"Was ist <math>\varepsilon</math>?", "back": "Das leere Wort."},
        ])
        md = db._generate_markdown_card_list()
        assert "<!-- COLLECTION_0_START -->" in md
        assert "<!-- COLLECTION_0_END -->" in md
        assert "<!-- CARDS_START -->" in md
        assert "<!-- CARDS_END -->" in md
        assert "**A. Unsortiert**" in md
        assert "1. Was ist ein Alphabet?" in md
        assert r"2. Was ist <math>\Sigma^*</math>?" in md
        assert r"3. Was ist <math>\varepsilon</math>?" in md

    def test_generate_markdown_card_list_collection_header_uses_display_name(self, tmp_path):
        """
        The collection header line '**Neue Karten**' uses _get_collection_display_name().
        For collection_key='collection_0_Neue_Karten' with no ProjectConfig and no
        cached display name, the fallback reconstructs: parts[2:] = ['Neue', 'Karten'],
        each capitalize()-d and joined: 'Neue Karten'.
        Observed: '**Neue Karten**' appears in the generated markdown.
        """
        db = make_db(tmp_path)
        db.integrate_new([
            {"front": "Was ist eine formale Sprache?", "back": r"Teilmenge von \Sigma^*."},
        ])
        md = db._generate_markdown_card_list()
        assert "**Neue Karten**" in md

    def test_generate_markdown_card_list_math_fronts_appear_verbatim(self, tmp_path):
        """
        Card fronts containing <math> tags appear verbatim (unescaped) in the
        generated markdown numbered list. The markdown generator does NOT sanitize
        or escape content — what goes into integrate_new() comes out in the list.
        Observed: r'Was ist <math>\\mathbb{Z}</math>?' appears as-is in the output.
        """
        db = make_db(tmp_path)
        front = r"Ist <math>\mathbb{Z}</math> ein Alphabet?"
        db.integrate_new([{"front": front, "back": "Nein, unendlich."}])
        md = db._generate_markdown_card_list()
        assert f"1. {front}" in md

    def test_generate_markdown_card_list_empty_db_returns_empty_string(self, tmp_path):
        """
        _generate_markdown_card_list() on an empty card list returns ''.
        Observed: the early return 'if not self.cards: return \"\"' triggers.
        """
        db = make_db(tmp_path)
        assert db._generate_markdown_card_list() == ""

    def test_generate_markdown_card_list_sorted_by_sort_field(self, tmp_path):
        """
        Cards are sorted by sort_field before generating the markdown list.
        When integrating [C, A, B] in that order, the markdown lists them
        in sort_field order (alphabetical on the full sort_field string).
        For a single batch, cards are already in order because sort_key is
        00_A_{i+1:02d} where i is the batch index. Card 1 → '00_A_01_...'.
        Observed: the numbered list order matches the sort_field order.
        """
        db = make_db(tmp_path)
        db.integrate_new([
            {"front": "C: Was ist ein Kellerautomat?", "back": "Ein PDA."},
            {"front": "A: Was ist ein Alphabet?", "back": "Endliche Menge."},
            {"front": r"B: Was ist <math>\Sigma^*</math>?", "back": "Kleene-Hülle."},
        ])
        md = db._generate_markdown_card_list()
        lines = [l for l in md.split("\n") if l.startswith(("1.", "2.", "3."))]
        assert lines[0].startswith("1. C:")
        assert lines[1].startswith("2. A:")
        assert lines[2].startswith(r"3. B:")

    # ─── ingest_text — OCR content forwarding ────────────────────────────────

    def test_ingest_sends_image_markers_and_visual_descriptions_to_llm(self, tmp_path):
        """
        The full OCR text (including 'Image: page_N.png' markers and
        '[Visual Description: ...]' blocks) must be forwarded to the LLM intact.
        _load_texts() must not strip these markers.
        Observed: prompt_body contains 'Image: page_3.png' and r'\\Sigma'.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))

        ocr_file = tmp_path / "skript.txt"
        ocr_file.write_text(REAL_SKRIPT_SNIPPET, encoding="utf-8")

        captured = {}
        def capture_llm(header_context, prompt_body, model=None, **kwargs):
            captured["prompt"] = prompt_body
            return json.dumps({"new_cards": []})

        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   side_effect=capture_llm):
            ingest_text([str(ocr_file)], cfg, str(tmp_path / "out.json"))

        assert "Image: page_3.png" in captured["prompt"]
        assert r"\Sigma" in captured["prompt"]

    def test_ingest_mitschrift_with_visual_descriptions_does_not_crash(self, tmp_path):
        """
        Real mitschrift_tutorium01.txt contains '[Visual Description: ...]' blocks,
        '*Handwritten Comment:*' lines, and <math>...</math> tags.
        ingest_text() must forward all of this to the LLM without crashing.
        Observed: result is True; mock LLM returns one card; card appears in output.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))

        ocr_file = tmp_path / "mitschrift.txt"
        ocr_file.write_text(REAL_MITSCHRIFT_SNIPPET, encoding="utf-8")

        mock_card = {
            "front": r"Ist $\mathbb{Z}$ ein Alphabet?",
            "back": "Nein. Alphabete sind endlich, ℤ ist unendlich.",
            "collection": "collection_0_Sprachen",
            "category": "a_grundlagen",
        }
        output_path = str(tmp_path / "out.json")
        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value=json.dumps({"new_cards": [mock_card]})):
            result = ingest_text([str(ocr_file)], cfg, output_path)

        assert result is True
        data = json.loads(Path(output_path).read_text(encoding="utf-8"))
        assert len(data["new_cards"]) == 1

    def test_ingest_two_ocr_files_joined_does_not_crash(self, tmp_path):
        """
        Student ingests skript.txt and uebung.txt together (two lecture sources).
        Both are joined with '\\n\\n---\\n\\n'. The existing '---' separators in
        OCR output become part of a longer separator chain. Must not crash.
        Observed: result is True when both REAL_SKRIPT_SNIPPET and REAL_UEBUNG_SNIPPET
        are passed together.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))

        f1 = tmp_path / "skript.txt"
        f2 = tmp_path / "uebung.txt"
        f1.write_text(REAL_SKRIPT_SNIPPET, encoding="utf-8")
        f2.write_text(REAL_UEBUNG_SNIPPET, encoding="utf-8")

        with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                   return_value=json.dumps({"new_cards": []})):
            result = ingest_text([str(f1), str(f2)], cfg, str(tmp_path / "out.json"))

        assert result is True


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 2: sync_from_ssot and run_sync_workflow
# ─────────────────────────────────────────────────────────────────────────────

class TestSyncWorkflow:
    """
    run_sync_workflow() and sync_from_ssot() are the most common post-bootstrap
    operations. A student bootstraps once, then syncs after every integration.
    These were not covered in existing tests.
    """

    def _make_db_with_cards(self, tmp_path):
        """Creates a DB with 2 cards already persisted to disk."""
        cards = [
            make_card(front="Was ist ein Alphabet?",
                      sort_field="00_A_01_alphabet"),
            make_card(front=r"Was ist <math>\Sigma^*</math>?",
                      sort_field="00_A_02_sigma_stern"),
        ]
        db = make_db(tmp_path, cards=cards)
        return db

    def test_sync_from_ssot_generates_derived_files(self, tmp_path):
        """
        sync_from_ssot() calls distribute_to_derived_files with the directory of db_path,
        not with '.'. Derived files land next to the database, not in CWD.
        """
        import os
        db = self._make_db_with_cards(tmp_path)
        expected_dir = os.path.dirname(os.path.abspath(db.db_path))
        with patch.object(db, 'distribute_to_derived_files', return_value=True) as mock_dist:
            result = db.sync_from_ssot()
        assert result is True
        mock_dist.assert_called_once_with(expected_dir)

    def test_sync_from_ssot_loads_db_if_cards_empty(self, tmp_path):
        """
        sync_from_ssot() with empty in-memory cards loads from disk first.
        The DB file must exist — if not, returns False.
        """
        # DB file exists on disk
        cards = [make_card(sort_field="00_A_01_q")]
        db = make_db(tmp_path, cards=cards)
        db.cards = []  # simulate fresh DatabaseManager instance

        with patch.object(db, 'distribute_to_derived_files', return_value=True):
            result = db.sync_from_ssot()
        assert result is True
        assert len(db.cards) == 1  # loaded from disk

    def test_sync_from_ssot_returns_false_when_no_db_file(self, tmp_path):
        """
        sync_from_ssot() without any DB file (no bootstrap done yet) returns False.
        User must run --extract first.
        """
        db = make_db(tmp_path)  # no cards, no file
        result = db.sync_from_ssot()
        assert result is False

    def test_sync_from_ssot_returns_false_if_distribute_fails(self, tmp_path):
        """
        If distribute_to_derived_files fails, sync_from_ssot propagates the failure.
        """
        db = self._make_db_with_cards(tmp_path)
        with patch.object(db, 'distribute_to_derived_files', return_value=False):
            result = db.sync_from_ssot()
        assert result is False

    def test_sync_does_not_modify_card_database(self, tmp_path):
        """
        sync_from_ssot() must NOT modify card_database.json — SSOT is read-only here.
        The card count must be identical before and after sync.
        """
        cards = [
            make_card(front="Q1", sort_field="00_A_01_q1"),
            make_card(front="Q2", sort_field="00_A_02_q2"),
        ]
        db = make_db(tmp_path, cards=cards)

        with patch.object(db, 'distribute_to_derived_files', return_value=True):
            db.sync_from_ssot()

        # Re-load and verify unchanged
        db2 = make_db(tmp_path, cards=None)
        db2.load_database()
        assert len(db2.cards) == 2
        assert db2.cards[0].front == "Q1"

    def test_run_sync_workflow_end_to_end(self, tmp_path):
        """
        WorkflowManager.run_sync_workflow() calls sync_from_ssot → verify_integrity
        → TemplatePromptUpdater. All must succeed for result=True.
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))

        # Pre-seed the DB on disk
        db = make_db(project_dir, config=cfg)
        db.cards = [make_card(sort_field="00_A_01_q")]
        db.save_database()

        wm = WorkflowManager(project_dir=str(project_dir))

        with patch.object(wm.db_manager, 'sync_from_ssot', return_value=True), \
             patch.object(wm.db_manager, 'verify_integrity', return_value=(True, "OK")), \
             patch("pdf2anki.text2anki.workflow_manager.TemplatePromptUpdater") as mock_tpu:
            mock_tpu.return_value.run_full_update.return_value = None
            result = wm.run_sync_workflow()

        assert result is True

    def test_run_sync_workflow_returns_false_if_sync_fails(self, tmp_path):
        """If sync_from_ssot() fails, run_sync_workflow() immediately returns False."""
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = make_gti_project(tmp_path)
        wm = WorkflowManager(project_dir=str(project_dir))

        with patch.object(wm.db_manager, 'sync_from_ssot', return_value=False):
            result = wm.run_sync_workflow()

        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 3: run_smart_extract_workflow routing logic
# ─────────────────────────────────────────────────────────────────────────────

class TestSmartExtractRouting:
    """
    run_smart_extract_workflow() is the default --extract command.
    It routes to sync (if DB exists and is non-empty) or bootstrap (if not).
    """

    def test_routes_to_sync_when_db_exists_and_nonempty(self, tmp_path):
        """
        If card_database.json exists and has content (> 50 bytes), smart extract
        runs sync — NOT bootstrap. The SSOT is preserved.
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = make_gti_project(tmp_path)

        # Create a non-trivial DB file (>50 bytes)
        db_path = project_dir / "card_database.json"
        cards = [make_card(sort_field="00_A_01_q")]
        db_path.write_text(
            json.dumps([c.to_dict() for c in cards]), encoding="utf-8"
        )
        assert os.path.getsize(str(db_path)) > 50

        wm = WorkflowManager(project_dir=str(project_dir))
        with patch.object(wm, 'run_sync_workflow', return_value=True) as mock_sync, \
             patch.object(wm, 'run_extract_workflow', return_value=True) as mock_bootstrap:
            result = wm.run_smart_extract_workflow()

        assert result is True
        mock_sync.assert_called_once()
        mock_bootstrap.assert_not_called()

    def test_routes_to_bootstrap_when_no_db(self, tmp_path):
        """
        If card_database.json does not exist, smart extract runs full bootstrap.
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = make_gti_project(tmp_path)
        wm = WorkflowManager(project_dir=str(project_dir))

        with patch.object(wm, 'run_sync_workflow', return_value=True) as mock_sync, \
             patch.object(wm, 'run_extract_workflow', return_value=True) as mock_bootstrap:
            result = wm.run_smart_extract_workflow(force=True)

        assert result is True
        mock_bootstrap.assert_called_once()
        mock_sync.assert_not_called()

    def test_routes_to_bootstrap_when_db_too_small(self, tmp_path):
        """
        If card_database.json exists but is ≤50 bytes (empty/minimal), smart
        extract still runs bootstrap (with force=True to skip prompt).
        """
        from pdf2anki.text2anki.workflow_manager import WorkflowManager
        project_dir = make_gti_project(tmp_path)

        # Tiny file — below the 50-byte threshold
        db_path = project_dir / "card_database.json"
        db_path.write_text("[]", encoding="utf-8")
        assert os.path.getsize(str(db_path)) <= 50

        wm = WorkflowManager(project_dir=str(project_dir))
        with patch.object(wm, 'run_sync_workflow', return_value=True) as mock_sync, \
             patch.object(wm, 'run_extract_workflow', return_value=True) as mock_bootstrap:
            result = wm.run_smart_extract_workflow(force=True)

        assert result is True
        mock_bootstrap.assert_called_once()
        mock_sync.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 4: Temporal multi-ingestion (week-by-week student workflow)
# ─────────────────────────────────────────────────────────────────────────────

class TestTemporalMultiIngestion:
    """
    Simulates a GTI student adding cards week by week over a semester.
    This is the PRIMARY use case: run --ingest + --integrate each week.

    Week 1: Bootstrap from initial DFA cards
    Week 2: Ingest NFA lecture → 3 new cards, DFA cards preserved, no dups
    Week 3: Try to re-ingest DFA material → all rejected as duplicates
    Week 4: Ingest RegEx lecture → 2 new cards
    Final: Verify total card count and GUID stability
    """

    def _make_fresh_db(self, tmp_path):
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        db = make_db(project_dir, config=cfg)
        return db, cfg, project_dir

    def test_week1_bootstrap_dfa_cards(self, tmp_path):
        """Week 1: 3 DFA cards bootstrapped. GUID assigned to each."""
        db, cfg, _ = self._make_fresh_db(tmp_path)
        week1_cards = [
            {"front": "Was ist ein DFA?", "back": r"5-Tupel M = (Q, Σ, δ, q0, F)."},
            {"front": r"Was ist δ im DFA?", "back": r"δ: Q × Σ → Q, Übergangsfunktion."},
            {"front": "Was ist q0?", "back": "Der Startzustand."},
        ]
        count = db.integrate_new(week1_cards)
        assert count == 3
        guids_week1 = {c.guid for c in db.cards}
        assert len(guids_week1) == 3  # all unique
        db.save_database()

    def test_week2_nfa_cards_added_dfa_preserved(self, tmp_path):
        """
        Week 2: 3 NFA cards integrated. 3 existing DFA cards must be preserved.
        Total: 6 cards.
        """
        db, cfg, _ = self._make_fresh_db(tmp_path)
        week1 = [
            {"front": "Was ist ein DFA?", "back": r"5-Tupel M = (Q, Σ, δ, q0, F)."},
            {"front": r"Was ist δ im DFA?", "back": r"δ: Q × Σ → Q, Übergangsfunktion."},
            {"front": "Was ist q0?", "back": "Der Startzustand."},
        ]
        db.integrate_new(week1)
        week1_guids = {c.guid: c.front for c in db.cards}

        week2 = [
            {"front": "Was ist ein NFA?", "back": "Nichtdeterministischer endlicher Automat."},
            {"front": "Was akzeptiert ein NFA?", "back": "Wenn mind. eine Berechnung akzeptiert."},
            {"front": r"Was ist ε-Übergang?", "back": "Übergang ohne Eingabesymbol."},
        ]
        count = db.integrate_new(week2)
        assert count == 3
        assert len(db.cards) == 6

        # Verify DFA cards still present with original GUIDs
        for guid, front in week1_guids.items():
            card = next((c for c in db.cards if c.guid == guid), None)
            assert card is not None, f"Week-1 card '{front}' lost its GUID"
            assert card.front == front

    def test_week3_duplicate_dfa_material_all_rejected(self, tmp_path):
        """
        Week 3: Student accidentally re-ingests week 1 DFA material.
        All 3 cards must be rejected as duplicates (case-insensitive match).
        Card count stays at 6.
        """
        db, cfg, _ = self._make_fresh_db(tmp_path)
        week1 = [
            {"front": "Was ist ein DFA?", "back": r"5-Tupel M = (Q, Σ, δ, q0, F)."},
            {"front": r"Was ist δ im DFA?", "back": r"δ: Q × Σ → Q, Übergangsfunktion."},
            {"front": "Was ist q0?", "back": "Der Startzustand."},
        ]
        week2 = [
            {"front": "Was ist ein NFA?", "back": "Nichtdeterministischer endlicher Automat."},
            {"front": "Was akzeptiert ein NFA?", "back": "Wenn mind. eine Berechnung akzeptiert."},
        ]
        db.integrate_new(week1)
        db.integrate_new(week2)
        assert len(db.cards) == 5

        # Week 3: re-ingest week1 with slightly different casing
        week3_dupes = [
            {"front": "Was ist ein DFA?", "back": "Andere Erklärung"},     # exact dup
            {"front": "WAS IST EIN DFA?", "back": "Großschreibung"},        # case variant
            {"front": "was ist q0?", "back": "lowercase dup"},              # lowercase
        ]
        count = db.integrate_new(week3_dupes)
        assert count == 0, "All week-3 cards must be rejected as duplicates"
        assert len(db.cards) == 5, "Card count must not change"

    def test_week4_regex_cards_added_correctly(self, tmp_path):
        """
        Week 4: RegEx cards added. Previous 5 cards preserved. Total: 8.
        """
        db, cfg, _ = self._make_fresh_db(tmp_path)
        db.integrate_new([
            {"front": "Was ist ein DFA?", "back": "5-Tupel."},
            {"front": "Was ist ein NFA?", "back": "Nichtdeterministisch."},
            {"front": "Was ist q0?", "back": "Startzustand."},
            {"front": "Was akzeptiert ein NFA?", "back": "Mind. eine Berechnung."},
            {"front": r"Was ist ε-Übergang?", "back": "Übergang ohne Eingabe."},
        ])
        week4 = [
            {"front": r"Was matcht (a|b)*abb?", "back": r"Wörter über \{a,b\} die auf 'abb' enden."},
            {"front": r"Was ist $a^*$ als regulärer Ausdruck?", "back": r"Beliebig viele 'a': ε, a, aa, aaa, ..."},
            {"front": "Was sind Pumping-Lemma Bedingungen?",
             "back": r"∀ w ∈ L, |w| ≥ p: ∃ Zerlegung w=xyz mit |y|≥1, |xy|≤p, ∀i≥0: xy^iz ∈ L."},
        ]
        count = db.integrate_new(week4)
        assert count == 3
        assert len(db.cards) == 8

    def test_guid_stability_across_save_load_cycles(self, tmp_path):
        """
        After each week's save→load cycle, card GUIDs must be identical.
        Anki uses GUIDs for sync — changing them creates duplicates in the app.
        """
        db, cfg, project_dir = self._make_fresh_db(tmp_path)
        initial_cards = [
            {"front": "Was ist ein DFA?", "back": "5-Tupel."},
            {"front": r"Was ist δ?", "back": "Übergangsfunktion."},
        ]
        db.integrate_new(initial_cards)
        db.save_database()
        original_guids = {c.front: c.guid for c in db.cards}

        # Simulate week 2: load, add cards, save
        db2 = make_db(project_dir, config=cfg)
        db2.load_database()
        db2.integrate_new([{"front": "Was ist ein NFA?", "back": "Nichtdeterministisch."}])
        db2.save_database()

        # Verify week-1 GUIDs unchanged after week-2 save
        for front, original_guid in original_guids.items():
            card = next((c for c in db2.cards if c.front == front), None)
            assert card is not None
            assert card.guid == original_guid, \
                f"GUID changed for '{front}': was {original_guid}, now {card.guid}"

    def test_ingest_then_integrate_pipeline_week_over_week(self, tmp_path):
        """
        Full pipeline test: ingest (LLM mock) → write new_cards_output.json →
        integrate → repeat for 3 weeks. Verifies the fixed format mismatch bug.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        db = make_db(project_dir, config=cfg)

        weeks = [
            [{"front": "Was ist ein DFA?", "back": "5-Tupel.", "collection": "collection_0_Sprachen", "category": "a_grundlagen"}],
            [{"front": "Was ist ein NFA?", "back": "Nichtdeterministisch.", "collection": "collection_0_Sprachen", "category": "a_grundlagen"}],
            [{"front": r"Was ist $a^*$?", "back": "Kleene-Stern.", "collection": "collection_1_RegEx", "category": "a_grundlagen"}],
        ]

        total_expected = 0
        for week_num, week_cards in enumerate(weeks, 1):
            output_path = str(project_dir / "new_cards_output.json")
            ocr_file = tmp_path / f"vorlesung_{week_num:02d}.txt"
            ocr_file.write_text(f"Vorlesung {week_num} Inhalt", encoding="utf-8")

            with patch("pdf2anki.text2anki.text_ingester.get_llm_decision",
                       return_value=json.dumps({"new_cards": week_cards})):
                ingest_text([str(ocr_file)], cfg, output_path)

            data = json.loads(Path(output_path).read_text(encoding="utf-8"))
            # This uses the {"new_cards": [...]} format — fixed in run_integrate_workflow
            count = db.integrate_new(data["new_cards"])
            total_expected += len(week_cards)
            assert count == len(week_cards), f"Week {week_num}: expected {len(week_cards)} new cards"

        assert len(db.cards) == total_expected


# ─────────────────────────────────────────────────────────────────────────────
# CLASS 5: collection=None in ApkgExporter
# ─────────────────────────────────────────────────────────────────────────────

class TestExporterCollectionNone:
    """
    Verifies exact behavior when cards have collection=None.
    _group_by_collection uses `card.collection or 'collection_0_unsorted'`
    so these cards DO get exported — not silently dropped.
    """

    def test_collection_none_cards_exported_as_fallback_group(self, tmp_path):
        """
        Cards with collection=None are grouped under 'collection_0_unsorted'.
        Since this key is not in config.collections, display_name falls back
        to the key itself and filename becomes 'collection_0_unsorted.apkg'.
        Result: exactly 1 .apkg file.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        cards = [AnkiCard(front="Heimatlose Karte", back="Ohne Sammlung", collection=None)]
        exporter = ApkgExporter()

        with patch("pdf2anki.text2anki.apkg_exporter.genanki") as mock_genanki:
            mock_genanki.Package.return_value = MagicMock()
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Model.return_value = MagicMock()
            generated = exporter.export(cards, cfg, str(tmp_path))

        assert len(generated) == 1
        assert "collection_0_unsorted.apkg" in generated[0]

    def test_collection_none_and_real_collection_exported_separately(self, tmp_path):
        """
        Mix of collection=None and real collection → 2 separate .apkg files.
        None cards go to fallback, real cards go to their collection file.
        """
        project_dir = make_gti_project(tmp_path)
        cfg = ProjectConfig.from_file(str(project_dir))
        cards = [
            AnkiCard(front="Heimatlos", back="Kein Deck", collection=None),
            make_card(front="Bekannte Karte", sort_field="00_A_01_q"),
        ]
        exporter = ApkgExporter()

        with patch("pdf2anki.text2anki.apkg_exporter.genanki") as mock_genanki:
            mock_genanki.Package.return_value = MagicMock()
            mock_genanki.Deck.return_value = MagicMock()
            mock_genanki.Note.return_value = MagicMock()
            mock_genanki.Model.return_value = MagicMock()
            generated = exporter.export(cards, cfg, str(tmp_path))

        assert len(generated) == 2
        filenames = [os.path.basename(p) for p in generated]
        assert "collection_0_unsorted.apkg" in filenames
        assert "collection_0_Sprachen.apkg" in filenames
