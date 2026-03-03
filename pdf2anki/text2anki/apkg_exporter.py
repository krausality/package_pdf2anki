#!/usr/bin/env python3
"""
apkg_exporter.py — ExporterBase + ApkgExporter: Exportiert card_database → .apkg

Konvertiert die in-memory AnkiCard-Liste (aus DatabaseManager) in eine oder
mehrere Anki-Package-Dateien (.apkg), eine pro Kollektion.

Option-3-ready: ExporterBase definiert das Plugin-Interface für Milestone 3.
"""

import hashlib
import os
from typing import List

import genanki

from .card import AnkiCard
from .console_utils import safe_print
from .project_config import ProjectConfig


# ─────────────────────────────────────────────────────────────────────────────
# Abstract Base (Option 3 Plugin-Interface)
# ─────────────────────────────────────────────────────────────────────────────

class ExporterBase:
    """Abstrakte Basis für Anki-Export-Formate. Für Milestone 3 Plugin-System."""

    def export(self, cards: List[AnkiCard], config: ProjectConfig, output_dir: str) -> List[str]:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────
# ApkgExporter
# ─────────────────────────────────────────────────────────────────────────────

class ApkgExporter(ExporterBase):
    """Exportiert AnkiCard-Liste → .apkg Dateien, eine pro Kollektion."""

    def export(self, cards: List[AnkiCard], config: ProjectConfig, output_dir: str = '.') -> List[str]:
        """
        Erzeugt .apkg Dateien aus der Kartenliste.

        Args:
            cards: Liste aller AnkiCard-Objekte (aus DatabaseManager.cards).
            config: ProjectConfig des Projekts.
            output_dir: Zielverzeichnis für die .apkg Dateien.

        Returns:
            Liste der erzeugten .apkg Dateipfade.
        """
        cards_by_collection = self._group_by_collection(cards)
        generated = []

        for collection_key, coll_cards in sorted(cards_by_collection.items()):
            coll_cfg = config.collections.get(collection_key, {})
            display_name = coll_cfg.get('display_name', collection_key)
            deck_name = f"{config.tag_prefix}::{display_name}"
            deck_id = self._stable_id(f"deck_{collection_key}", config.project_name)
            model = self._create_model(config.project_name, collection_key)

            deck = genanki.Deck(deck_id, deck_name)
            for card in sorted(coll_cards, key=lambda c: c.sort_field or ''):
                note = genanki.Note(
                    model=model,
                    fields=[card.sort_field or '', card.front, card.back or ''],
                    guid=card.guid,
                    tags=card.tags,
                )
                deck.add_note(note)

            # Ausgabedateiname: collection_filename aus config oder Fallback
            json_filename = coll_cfg.get('filename', f'{collection_key}.json')
            apkg_filename = json_filename.replace('.json', '.apkg')
            out_path = os.path.join(output_dir, apkg_filename)

            genanki.Package(deck).write_to_file(out_path)
            safe_print(f"  ✅ Exportiert: {apkg_filename} ({len(coll_cards)} Karten)")
            generated.append(out_path)

        return generated

    # ── Hilfsmethoden ────────────────────────────────────────────────────────

    def _group_by_collection(self, cards: List[AnkiCard]):
        """Gruppiert Karten nach collection-Schlüssel."""
        groups = {}
        for card in cards:
            key = card.collection or 'collection_0_unsorted'
            groups.setdefault(key, []).append(card)
        return groups

    def _stable_id(self, key: str, project_name: str) -> int:
        """Deterministischer ID via MD5-Hash (verhindert Anki-Duplikate bei Re-Import)."""
        h = hashlib.md5(f"{project_name}_{key}".encode()).hexdigest()
        return int(h[:8], 16) % (2 ** 31)

    def _create_model(self, project_name: str, collection_key: str) -> genanki.Model:
        model_id = self._stable_id(f"model_{collection_key}", project_name)
        return genanki.Model(
            model_id,
            f'{project_name} Basic',
            fields=[
                {'name': 'SortField'},
                {'name': 'Front'},
                {'name': 'Back'},
            ],
            templates=[{
                'name': 'Card 1',
                'qfmt': '{{Front}}',
                'afmt': '{{FrontSide}}<hr id="answer">{{Back}}',
            }],
            sort_field_index=0,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Convenience-Wrapper
# ─────────────────────────────────────────────────────────────────────────────

def export_to_apkg(db_manager, config: ProjectConfig, output_dir: str = '.') -> List[str]:
    """
    Convenience-Wrapper: exportiert db_manager.cards nach .apkg.

    Args:
        db_manager: DatabaseManager-Instanz (muss .cards haben).
        config: ProjectConfig des Projekts.
        output_dir: Zielverzeichnis (default: aktuelles Verzeichnis).

    Returns:
        Liste der erzeugten .apkg Dateipfade.
    """
    exporter = ApkgExporter()
    return exporter.export(db_manager.cards, config, output_dir)
