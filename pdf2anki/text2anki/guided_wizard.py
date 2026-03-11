"""
guided_wizard.py — Interactive CLI wizard for project.json creation.

Used as the --no-llm fallback: guides the user through every required field
with prompts. Returns a dict matching the project.json schema.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .project_config import PROJECT_JSON_TEMPLATE


def _prompt(question: str, default: Optional[str] = None) -> str:
    """Print a prompt and return stripped input. Repeat until non-empty."""
    hint = f" [{default}]" if default else ""
    while True:
        raw = input(f"{question}{hint}: ").strip()
        if raw:
            return raw
        if default is not None:
            return default
        print("  (Pflichtfeld — bitte einen Wert eingeben)")


def _prompt_int(question: str, minimum: int = 1) -> int:
    while True:
        raw = input(f"{question}: ").strip()
        try:
            value = int(raw)
            if value >= minimum:
                return value
            print(f"  (Bitte eine ganze Zahl >= {minimum} eingeben)")
        except ValueError:
            print("  (Bitte eine ganze Zahl eingeben)")


def run_guided_wizard(base_dir: Path) -> dict:
    """
    Interactively collect all project.json fields from the user.

    Args:
        base_dir: Directory where the project will live (shown in prompts for context).

    Returns:
        A dict ready to pass to ProjectConfig.create_from_dict().
    """
    print()
    print("=" * 60)
    print("  pdf2anki — Projekt-Setup (manueller Modus)")
    print(f"  Zielordner: {base_dir}")
    print("=" * 60)
    print()

    project_name = _prompt("Projektname (z.B. GTI_WiSe2526)")
    tag_prefix = _prompt(
        "Tag-Präfix für Anki (z.B. GTI)",
        default=project_name.replace(" ", "_").upper(),
    )
    language = _prompt("Sprache (de / en / ...)", default="de")
    domain = _prompt(
        "Fachgebiet (z.B. 'Grundlagen der Theoretischen Informatik')"
    )
    orphan = _prompt(
        "Name der Sammel-Kollektion für nicht zugeordnete Karten",
        default="Unsortierte_Karten",
    )

    print()
    n_collections = _prompt_int("Anzahl der Kollektionen (Kapitel / Themenblöcke)", minimum=1)

    collections: dict = {}
    for i in range(n_collections):
        print(f"\n  --- Kollektion {i + 1} von {n_collections} ---")
        display_name = _prompt(f"  Anzeigename (z.B. 'Kapitel {i + 1}: Automaten')")
        description = _prompt(f"  Kurzbeschreibung", default="")
        # Derive a safe key and filename from the display name
        safe = display_name.replace(" ", "_").replace(":", "").replace("/", "_")
        # Remove any characters not suitable for a JSON key / filename
        import re
        safe = re.sub(r"[^\w]", "_", safe)
        key = f"collection_{i}_{safe}"
        filename = f"{key}.json"
        collections[key] = {
            "display_name": display_name,
            "filename": filename,
            "description": description,
        }

    # Build the final dict from the template, overriding with collected values
    data: dict = {
        **PROJECT_JSON_TEMPLATE,
        "project_name": project_name,
        "tag_prefix": tag_prefix,
        "language": language,
        "domain": domain,
        "orphan_collection_name": orphan,
        "collections": collections,
    }

    print()
    print("=" * 60)
    print("  Konfiguration abgeschlossen.")
    print("=" * 60)
    print()

    return data
