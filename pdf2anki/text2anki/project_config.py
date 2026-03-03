#!/usr/bin/env python3
"""
project_config.py — ProjectConfig: Lädt und validiert project.json.

Ersetzt alle hardcoded PP25-spezifischen Werte in database_manager.py und
workflow_manager.py durch konfigurationsgesteuerte Werte.

Milestone 1 von text2anki (pdf2anki.text2anki).
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from .console_utils import safe_print


# ─────────────────────────────────────────────────────────────────────────────
# project.json Vollständiges Template
# ─────────────────────────────────────────────────────────────────────────────

PROJECT_JSON_TEMPLATE = {
    "_comment": (
        "text2anki Projektkonfiguration. "
        "Jedes Lernprojekt hat eine eigene project.json in seinem Verzeichnis."
    ),
    "project_name": "MeinProjekt",
    "tag_prefix": "MeinProjekt",
    "language": "de",
    "domain": "Beschreibe hier das Fachgebiet, z.B. 'Organische Chemie (Reaktionsmechanismen)'",
    "orphan_collection_name": "Unsortierte_Karten",

    "files": {
        "db_path": "card_database.json",
        "markdown_file": "All_fronts.md",
        "new_cards_file": "new_cards_output.json",
        "material_file": "course_material.txt"
    },

    "collections": {
        "collection_0_Kapitel1": {
            "display_name": "Kapitel 1: Grundlagen",
            "filename": "collection_0_Kapitel1.json",
            "description": "Einführende Konzepte und Grundbegriffe"
        },
        "collection_1_Kapitel2": {
            "display_name": "Kapitel 2: Vertiefung",
            "filename": "collection_1_Kapitel2.json",
            "description": "Weiterführende Themen"
        }
    },

    "llm": {
        "model": "google/gemini-2.5-flash",
        "temperature": 0.1
    }
}


# ─────────────────────────────────────────────────────────────────────────────
# ProjectConfig
# ─────────────────────────────────────────────────────────────────────────────

class ProjectConfig:
    """
    Lädt und kapselt die Konfiguration eines text2anki-Projekts aus project.json.

    Stellt alle projektspezifischen Werte bereit, die früher in database_manager.py
    und workflow_manager.py hardcoded waren (PP25-spezifische Kollektionsnamen,
    Tag-Prefix, LLM-Domain-Kontext, Dateinamen).

    Beispiel:
        config = ProjectConfig.from_file('/pfad/zu/meinem_kurs')
        db = DatabaseManager(config.get_db_path(), project_config=config)
    """

    def __init__(self, project_dir: str, data: dict):
        self.project_dir = Path(project_dir).resolve()
        self.project_name: str = data['project_name']
        self.tag_prefix: str = data['tag_prefix']
        self.language: str = data.get('language', 'de')
        self.domain: str = data.get('domain', 'Allgemeines Wissen')
        self.orphan_collection_name: str = data.get('orphan_collection_name', 'Unsortierte_Karten')

        self.files: dict = data.get('files', {})
        self.collections: Dict[str, dict] = data.get('collections', {})
        self.llm: dict = data.get('llm', {})

    # ── Klassenmethoden ──────────────────────────────────────────────────────

    @classmethod
    def from_file(cls, project_dir: str) -> 'ProjectConfig':
        """
        Lädt project.json aus project_dir und gibt eine validierte ProjectConfig zurück.

        Args:
            project_dir: Pfad zum Projektverzeichnis (muss project.json enthalten).

        Raises:
            FileNotFoundError: Wenn project.json nicht existiert.
            ValueError: Wenn Pflichtfelder fehlen oder ungültig sind.
            json.JSONDecodeError: Wenn project.json kein valides JSON ist.
        """
        path = Path(project_dir) / 'project.json'
        if not path.exists():
            raise FileNotFoundError(
                f"project.json nicht gefunden in: {project_dir}\n"
                f"Tipp: Mit --init ein neues Projekt erstellen."
            )
        with open(path, encoding='utf-8') as f:
            data = json.load(f)

        cls._validate(data, str(path))
        return cls(project_dir, data)

    @classmethod
    def create_template(cls, project_dir: str, project_name: str) -> 'ProjectConfig':
        """
        Erstellt ein vorausgefülltes project.json Template im Projektverzeichnis.

        Args:
            project_dir: Zielverzeichnis (wird erstellt wenn nicht vorhanden).
            project_name: Name des Projekts (wird ins Template eingesetzt).

        Returns:
            ProjectConfig: Die geladene Konfiguration aus dem erstellten Template.
        """
        os.makedirs(project_dir, exist_ok=True)
        path = Path(project_dir) / 'project.json'

        if path.exists():
            raise FileExistsError(
                f"project.json existiert bereits in: {project_dir}\n"
                f"Löschen Sie die Datei manuell, um ein neues Template zu erstellen."
            )

        template = dict(PROJECT_JSON_TEMPLATE)
        template['project_name'] = project_name
        template['tag_prefix'] = project_name.replace(' ', '_').upper()

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(template, f, indent=2, ensure_ascii=False)

        safe_print(f"Projekt '{project_name}' initialisiert: {path}")
        safe_print(f"   -> Bitte project.json editieren: domain, collections anpassen.")
        return cls.from_file(project_dir)

    @staticmethod
    def _validate(data: dict, source_path: str = 'project.json'):
        """Prüft Pflichtfelder und Konsistenz. Wirft ValueError bei Problemen."""
        required_top = ['project_name', 'tag_prefix', 'collections']
        for field in required_top:
            if field not in data:
                raise ValueError(
                    f"{source_path}: Pflichtfeld '{field}' fehlt."
                )

        if not isinstance(data['project_name'], str) or not data['project_name'].strip():
            raise ValueError(f"{source_path}: 'project_name' darf nicht leer sein.")

        if not isinstance(data['tag_prefix'], str) or not data['tag_prefix'].strip():
            raise ValueError(f"{source_path}: 'tag_prefix' darf nicht leer sein.")

        if not isinstance(data['collections'], dict) or len(data['collections']) == 0:
            raise ValueError(
                f"{source_path}: 'collections' muss ein nicht-leeres Objekt sein.\n"
                f"Beispiel: {{\"collection_0_Kapitel1\": {{\"display_name\": \"Kapitel 1\", "
                f"\"filename\": \"collection_0_Kapitel1.json\", \"description\": \"...\"}}}}"
            )

        for key, cfg in data['collections'].items():
            if not isinstance(cfg, dict):
                raise ValueError(f"{source_path}: collections['{key}'] muss ein Objekt sein.")
            if 'filename' not in cfg:
                raise ValueError(
                    f"{source_path}: collections['{key}'] fehlt Pflichtfeld 'filename'."
                )
            if not cfg['filename'].endswith('.json'):
                raise ValueError(
                    f"{source_path}: collections['{key}']['filename'] muss auf .json enden."
                )

    # ── Pfad-Hilfsmethoden ───────────────────────────────────────────────────

    def get_db_path(self) -> str:
        """Absoluter Pfad zur card_database.json."""
        return str(self.project_dir / self.files.get('db_path', 'card_database.json'))

    def get_markdown_path(self) -> str:
        """Absoluter Pfad zur All_fronts.md (SSOT Markdown)."""
        return str(self.project_dir / self.files.get('markdown_file', 'All_fronts.md'))

    def get_new_cards_path(self) -> str:
        """Absoluter Pfad zur new_cards_output.json."""
        return str(self.project_dir / self.files.get('new_cards_file', 'new_cards_output.json'))

    def get_material_path(self) -> Optional[str]:
        """Absoluter Pfad zur Kursmaterial-Datei (oder None wenn nicht konfiguriert)."""
        material = self.files.get('material_file')
        if not material:
            return None
        path = self.project_dir / material
        return str(path) if path.exists() else None

    # ── Collection-Mapping-Methoden ──────────────────────────────────────────

    def get_collection_filename_mapping(self) -> Dict[str, str]:
        """
        Gibt das Mapping von collection-key → filename zurück.
        Ersetzt die hardcoded collection_filename_mapping in database_manager.py.

        Returns:
            Dict wie {"collection_0_Kernbegriffe": "collection_0_Kernbegriffe.json", ...}
        """
        return {key: cfg['filename'] for key, cfg in self.collections.items()}

    def get_legacy_collection_files(self) -> List[str]:
        """
        Gibt die absoluten Pfade aller Collection-JSON-Dateien zurück.
        Für workflow_manager.legacy_collection_files.
        """
        return [
            str(self.project_dir / cfg['filename'])
            for cfg in self.collections.values()
        ]

    def get_collection_display_name(self, collection_key: str) -> str:
        """Gibt den Display-Namen einer Kollektion zurück (oder den Key als Fallback)."""
        cfg = self.collections.get(collection_key, {})
        return cfg.get('display_name', collection_key)

    def get_collection_description(self, collection_key: str) -> str:
        """Gibt die Beschreibung einer Kollektion zurück (oder '' als Fallback)."""
        cfg = self.collections.get(collection_key, {})
        return cfg.get('description', '')

    def get_orphan_collection_key(self) -> str:
        """
        Gibt den internen Key für die Orphan-Kollektion zurück.
        Format: collection_{N}_{name} wobei N = Anzahl der definierten Kollektionen.
        """
        n = len(self.collections)
        name = self.orphan_collection_name.replace(' ', '_')
        return f"collection_{n}_{name}"

    def get_orphan_collection_filename(self) -> str:
        """Gibt den Dateinamen für die Orphan-Kollektion zurück."""
        n = len(self.collections)
        name = self.orphan_collection_name.replace(' ', '_')
        return f"collection_{n}_{name}.json"

    # ── LLM-Hilfsmethoden ───────────────────────────────────────────────────

    def get_llm_model(self) -> str:
        return self.llm.get('model', 'google/gemini-2.5-flash')

    def get_llm_temperature(self) -> float:
        return float(self.llm.get('temperature', 0.1))

    # ── Dunder ──────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"ProjectConfig("
            f"project='{self.project_name}', "
            f"tag='{self.tag_prefix}', "
            f"lang='{self.language}', "
            f"collections={list(self.collections.keys())}"
            f")"
        )
