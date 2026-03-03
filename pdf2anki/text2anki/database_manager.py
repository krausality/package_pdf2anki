#!/usr/bin/env python3
"""
Database Manager for Anki Cards System (v4.1 - SSOT)

This class is the sole guardian of the card_database.json, which acts
as the Single Source of Truth (SSOT) for the entire system.
It handles bootstrapping from legacy files, integrating new cards,
distributing to derived files, and verifying system integrity.
"""
import json
import os
import uuid
import re
import shutil
from datetime import datetime
from typing import List, Dict, Any, Tuple

from .card import AnkiCard
from .console_utils import safe_print

# LLM Integration Imports
from .llm_helper import get_llm_decision, reset_llm_session
from .material_manager import MaterialManager


class DatabaseManager:
    """Manages all operations on the Anki card database (SSOT)."""

    def __init__(self, db_path: str = 'card_database.json', material_manager=None, project_config=None):
        """
        Initializes the DatabaseManager.
        Args:
            db_path: The path to the JSON file serving as the SSOT database.
            material_manager: Optional instance for dependency injection, used for testing.
            project_config: Optional ProjectConfig instance for project-specific settings.
        """
        self.db_path = db_path
        self.cards: List[AnkiCard] = []
        self._config = project_config

        # Dependency Injection: Wenn kein MaterialManager übergeben wird, erstelle einen neuen.
        # Das macht den Code testbar, ohne die normale Funktionalität zu brechen.
        self.material_manager = material_manager if material_manager is not None else MaterialManager()

        # ProjectConfig-gesteuerte Werte (oder Defaults ohne Config)
        if project_config:
            self.collection_filename_mapping = project_config.get_collection_filename_mapping()
            self._tag_prefix = project_config.tag_prefix
            self._domain = project_config.domain
            self._language = project_config.language
            self._orphan_collection = project_config.orphan_collection_name
        else:
            self.collection_filename_mapping = {}  # Auto-discovery aktiv
            self._tag_prefix = "ANKI"
            self._domain = "Allgemeines Wissen"
            self._language = "de"
            self._orphan_collection = "Gerettete_Karten"

        # Dynamic Display Name Cache
        self._collection_display_names: Dict[str, str] = {}
        self._category_display_names: Dict[str, str] = {}
        
        self.load_database()

    def load_database(self):
        """Loads the card database from the JSON file into memory."""
        # Only load from file if the in-memory list is empty
        if not self.cards and os.path.exists(self.db_path):
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.cards = [AnkiCard.from_dict(card_data) for card_data in data]
                safe_print(f"✅ Datenbank geladen. {len(self.cards)} Karten im Speicher.")
                
                # Load display name mappings from markdown file if it exists
                self._load_display_name_mappings()
                
            except (json.JSONDecodeError, TypeError) as e:
                safe_print(f"❌ Fehler beim Laden der Datenbank: {e}")
                self.cards = []
        elif not os.path.exists(self.db_path):
            # This branch is for when the object is initialized without a db file existing
            safe_print("ℹ️ Keine bestehende Datenbank gefunden. Starte mit leerem Kartensatz.")
            self.cards = []

    def save_database(self):
        """Saves the current in-memory card list to the JSON database file."""
        try:
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump([card.to_dict() for card in self.cards], f, indent=2, ensure_ascii=False)
            # This print can be noisy in tests, let's show it only when interactive
            safe_print(f"✅ Datenbank mit {len(self.cards)} Karten gespeichert in '{self.db_path}'.")
            return True
        except Exception as e:
            safe_print(f"❌ Fehler beim Speichern der Datenbank: {e}")
            return False

    def bootstrap_from_legacy(self, collection_files: List[str], markdown_file: str, 
                         auto_rescue_orphans: bool = False,
                         auto_skip_conflicts: bool = False, 
                         auto_create_missing: bool = False,
                         auto_ignore_orphans: bool = False,
                         llm_resolve_conflicts: bool = False,
                         llm_categorize_orphans: bool = False,
                         llm_complete_backs: bool = False) -> bool:
        """
        (Re-)Initializes the SSOT by reading all legacy source files.
        """
        safe_print("🚀 Starte Bootstrap-Prozess aus Legacy-Dateien...")
        
        llm_header_context = None
        if llm_resolve_conflicts or llm_categorize_orphans or llm_complete_backs:
            reset_llm_session()
            try:
                # Nutze die Instanz-Variable und ihre gekapselte Methode.
                llm_header_context = self.material_manager.get_course_material()
                if llm_header_context:
                    safe_print(f"✅ LLM-Kontextmaterial ({len(llm_header_context)} Zeichen) für Caching geladen.")
                else:
                    safe_print("⚠️ LLM-Kontextmaterial konnte nicht geladen werden.", "WARNING")
            except Exception as e:
                safe_print(f"❌ Fehler beim Laden des LLM-Kontextmaterials: {e}", "ERROR")
        # 1. Daten aus allen Quellen aggregieren
        aggregated_cards = self._aggregate_from_collections(collection_files)
        markdown_structure = self._parse_markdown_structure(markdown_file)

        if not aggregated_cards and not markdown_structure:
            safe_print("❌ Keine Daten in Collections oder Markdown gefunden. Bootstrap abgebrochen.")
            return False

        # 2. Alle bekannten Kartenvorderseiten (Fronts) sammeln
        all_fronts = set(aggregated_cards.keys()) | set(markdown_structure.keys())
        clean_cards_data = []

        # 3. Konflikte für jede Karte lösen
        # Hinzufügen einer Sitzungs-Cache, um wiederholte Entscheidungen zu vermeiden
        self._orphan_resolution_cache = {} 
        # Hinzufügen einer Struktur zum Speichern von geretteten Karten
        self._rescued_cards_data = []

        for front in sorted(list(all_fronts)):
            # Den originalen, nicht-normalisierten Front-Text finden
            if front in markdown_structure:
                original_front = markdown_structure[front]["original_front"]
            elif front in aggregated_cards:
                original_front = aggregated_cards[front]["original_front"]
            else:
                # Sollte nicht passieren, aber als Fallback
                original_front = front

            in_collections = front in aggregated_cards
            in_markdown = front in markdown_structure

            if in_collections and in_markdown:
                # Fall 1: Karte existiert in beiden Quellen -> potenzieller Back-Konflikt
                backs = aggregated_cards[front]["backs"]
                unique_backs = sorted(list(set(backs)))
                if len(unique_backs) == 1:
                    # Kein Konflikt
                    clean_cards_data.append({"front": original_front, "back": unique_backs[0]})
                else:
                    # Automatische oder interaktive Lösung für Back-Konflikt
                    chosen_back = None # Standardmäßig keinen Back wählen

                    # Priorität 1: Versuche LLM, wenn angefordert
                    if llm_resolve_conflicts:
                        chosen_back = self._prompt_resolve_back_conflict(original_front, unique_backs, llm_header_context)

                    # Priorität 2 (Fallback): Wenn LLM fehlgeschlagen ist ODER nicht angefordert wurde,
                    # prüfe auf auto_skip.
                    if chosen_back is None and auto_skip_conflicts:
                        safe_print(f"🤖 AUTO-KONFLIKT: Verwende ersten Back für '{original_front[:50]}...'")
                        chosen_back = unique_backs[0]
                    
                    # Priorität 3 (Letzter Fallback): Manuelle Eingabe
                    if chosen_back is None and not llm_resolve_conflicts and not auto_skip_conflicts:
                        chosen_back = self._prompt_resolve_back_conflict(original_front, unique_backs, None)

                    if chosen_back:
                        clean_cards_data.append({"front": original_front, "back": chosen_back})
                        
            elif in_collections and not in_markdown:
                # Fall 2: Verwaiste Karte (nur in Collection)
                if llm_categorize_orphans:
                    # Baue den Prompt EINMAL, wenn noch nicht geschehen.
                    if not hasattr(self, '_categorization_prompt'):
                        self._categorization_prompt, self._categorization_mapping = self._build_categorization_prompt(markdown_structure)
                    
                    if self._categorization_prompt:
                        # Verwende all_fronts.md als Kontext.
                        # Wir müssen es hier laden, da der Haupt-Header das Kursmaterial sein kann.
                        md_content = ""
                        try:
                            with open(markdown_file, 'r', encoding='utf-8') as f:
                                md_content = f.read()
                        except Exception as e:
                            safe_print(f"Konnte Markdown-Kontext für Kategorisierung nicht laden: {e}", "ERROR")

                        prompt_body = f"{self._categorization_prompt}\n\n--- ZU KLASSIFIZIERENDE KARTE ---\nKARTE: \"{original_front}\"\n\nDeine Wahl [ZAHL][BUCHSTABE]:"
                        response = get_llm_decision(md_content, prompt_body)
                        
                        result = self._parse_llm_categorization_response(response, self._categorization_mapping)
                        
                        if result:
                            # Erfolgreich zugeordnet! Behandle sie wie eine normale Karte.
                            collection_key, category_key = result
                            # Füge die Karte direkt den clean_cards hinzu, mit den neuen Metadaten
                            card_data = {"front": original_front, "back": aggregated_cards[front]["backs"][0]}
                            card_data['collection_key'] = collection_key
                            card_data['category_key'] = category_key
                            # Sortierschlüssel muss hier neu generiert werden, da wir die Position nicht kennen
                            card_data['sort_key'] = f"{collection_key.split('_')[1]}_{category_key.split('_')[0].upper()}_99"
                            clean_cards_data.append(card_data)
                            continue # Gehe zur nächsten Karte

                    # Fallback, wenn der Prompt nicht gebaut werden konnte oder LLM fehlschlägt
                    safe_print("LLM-Kategorisierung fehlgeschlagen, falle auf heuristische Rettung zurück.", "WARNING")
                    # Wenn wir hier landen, wird die Standard-auto_rescue-Logik unten ausgeführt.

                if auto_ignore_orphans:
                    safe_print(f"🤖 AUTO-IGNORE: Überspringe verwaiste Karte '{original_front[:50]}...'")
                    continue
                elif auto_rescue_orphans:
                    safe_print(f"🤖 AUTO-RESCUE: Rette verwaiste Karte '{original_front[:50]}...'")
                    self._rescued_cards_data.append({"front": original_front, "back": aggregated_cards[front]["backs"][0]})
                else:
                    # Interaktive Lösung
                    result = self._prompt_resolve_orphan(original_front, markdown_structure)
                    if result == ("__RESCUE__", "__RESCUE__"):
                        self._rescued_cards_data.append({"front": original_front, "back": aggregated_cards[front]["backs"][0]})
                    elif result is not None:
                        clean_cards_data.append({"front": original_front, "back": aggregated_cards[front]["backs"][0], "collection_key": result[0], "category_key": result[1]})
            elif not in_collections and in_markdown:
                # Fall 3: Fehlende Karte (nur in Markdown)
                if llm_complete_backs:
                    safe_print(f"🤖 Verwende LLM, um Back für '{original_front[:50]}...' zu vervollständigen.")
                    # Baue den spezifischen Prompt für diese Aufgabe
                    prompt_body = (
                        f"Du bist ein Experte für {self._domain}. Beantworte die folgende Frage präzise und "
                        f"umfassend, basierend auf dem bereitgestellten Kontextmaterial. Deine Antwort sollte "
                        f"direkt als Rückseite einer Anki-Karte dienen und entsprechende Guetekriterien einhalten.\n\n"
                        f"FRAGE: {original_front}\n\n"
                        f"ANTWORT:"
                    )
                    # Rufe das LLM auf. Der `llm_header_context` wurde bereits am Anfang geladen.
                    new_back = get_llm_decision(llm_header_context, prompt_body)
                    if new_back:
                        clean_cards_data.append({"front": original_front, "back": new_back})
                    else:
                        # Fallback, falls LLM fehlschlägt
                        safe_print(f"⚠️ LLM konnte keinen Back generieren. Setze auf 'TODO'.", "WARNING")
                        clean_cards_data.append({"front": original_front, "back": "TODO: LLM-Fehler."})

                elif auto_create_missing:
                    # Automatisch: Erstelle fehlende Karten mit "TODO" Back
                    safe_print(f"🤖 AUTO-CREATE: Erstelle TODO-Karte für '{original_front[:50]}...'")
                    clean_cards_data.append({"front": original_front, "back": "TODO: Antwort hinzufügen"})
                else:
                    # Interaktive Lösung
                    new_back = self._prompt_create_missing(original_front)
                    if new_back:
                        clean_cards_data.append({"front": original_front, "back": new_back})
        # 4. Verarbeite die geretteten Karten, falls vorhanden
        if self._rescued_cards_data:
            # Finde die höchste Collection-Nummer, um eine neue zu erstellen
            max_coll_num = -1
            for card in self.cards: # Bestehende Karten aus vorherigen Schritten
                try:
                    num = int(card.collection.split('_')[1])
                    if num > max_coll_num:
                        max_coll_num = num
                except (IndexError, ValueError):
                    continue
            
            # Extrahiere auch Nummern aus der Markdown-Struktur
            for meta in markdown_structure.values():
                try:
                    num = int(meta['collection'].split('_')[1])
                    if num > max_coll_num:
                        max_coll_num = num
                except (IndexError, ValueError, KeyError):
                    continue

            rescued_coll_num = max_coll_num + 1
            orphan_name = self._orphan_collection.replace(' ', '_')
            rescued_collection_key = f"collection_{rescued_coll_num}_{orphan_name}"
            rescued_category_key = "a_Unsortiert"
            
            for i, card_data in enumerate(self._rescued_cards_data):
                # Füge die geretteten Karten den clean_cards_data hinzu
                # damit sie im nächsten Schritt zu AnkiCard-Objekten werden
                card_data['collection_key'] = rescued_collection_key
                card_data['category_key'] = rescued_category_key
                card_data['sort_key'] = f"{rescued_coll_num:02d}_A_{i+1:02d}"
                clean_cards_data.append(card_data)


        # 5. Finale AnkiCard-Objekte erstellen und Metadaten generieren
        self.cards = []
        for card_data in clean_cards_data:
            normalized_front = self._normalize_text(card_data["front"])
            
            # Metadaten können aus der Markdown-Struktur oder aus der Zuordnung kommen
            meta = markdown_structure.get(normalized_front, {})
            
            collection_name = card_data.get('collection_key') or meta.get("collection", "unbekannt")
            category_name = card_data.get('category_key') or meta.get("category", "unbekannt")
            sort_key = card_data.get('sort_key') or meta.get("sort_key", "99_Z_99")

            new_card = AnkiCard(
                guid=str(uuid.uuid4()),
                front=card_data["front"],
                back=card_data["back"],
                collection=collection_name,
                category=category_name,
                sort_field=self._generate_sort_field(sort_key, card_data["front"]),
                tags=self._generate_tags(collection_name, category_name),
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            self.cards.append(new_card)

        safe_print(f"\n✅ Bootstrap abgeschlossen. {len(self.cards)} saubere Karten erstellt.")
        

        self._collection_display_names: Dict[str, str] = {}
        self._category_display_names: Dict[str, str] = {}

        # 6. Save the database
        self.save_database()
        return True

    # sollte vllcht nicht nur fronttext sondern auch guid unetrstuetzen fuer spaeter
    def find_card_by_front(self, front_text: str) -> 'AnkiCard' or None:
        """
        Findet eine Karte anhand ihres exakten Front-Textes.

        Args:
            front_text (str): Der exakte Text der Kartenvorderseite.
        
        Returns:
            AnkiCard: Das gefundene Kartenobjekt oder None, wenn nichts gefunden wurde.
        """
        # Durchsuche alle Karten in der aktuellen Datenbank-Instanz
        for card in self.cards:
            if card.front == front_text:
                return card
        return None

    def _aggregate_from_collections(self, collection_files: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Liest alle collection.json-Dateien und aggregiert die Karten.
        Speichert den normalisierten Front, den originalen Front und eine Liste von Backs.
        """
        aggregated: Dict[str, Dict[str, Any]] = {}
        for file_path in collection_files:
            if not os.path.exists(file_path):
                continue
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    cards = json.load(f)
                for card in cards:
                    front = card.get("front", "").strip()
                    back = card.get("back", "").strip()
                    if not front or not back:
                        continue
                    
                    normalized_front = self._normalize_text(front)
                    if normalized_front not in aggregated:
                        aggregated[normalized_front] = {
                            "original_front": front,  # Speichere die erste gefundene Original-Großschreibung
                            "backs": []
                        }
                    aggregated[normalized_front]["backs"].append(back)
            except (json.JSONDecodeError, TypeError) as e:
                safe_print(f"⚠️ Warnung: Konnte Datei {file_path} nicht lesen. Fehler: {e}")
        return aggregated

    def _parse_markdown_structure(self, markdown_file: str) -> Dict[str, Dict[str, str]]:
        """
        Parses the markdown file using context-aware block parsing to extract
        the desired structure and card order.
        """
        structure = {}
        if not os.path.exists(markdown_file):
            return structure

        with open(markdown_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find all collection blocks using the specified markers
        collection_blocks = re.findall(r'<!-- COLLECTION_(\d+)_START -->(.*?)<!-- COLLECTION_\1_END -->', content, re.DOTALL)

        all_cards = []
        for collection_id_str, block_content in collection_blocks:
            collection_id = int(collection_id_str)
            parsed_cards = self._parse_collection_block(block_content, collection_id)
            all_cards.extend(parsed_cards)

        # Convert the list of card dicts into the required structure format
        for card_data in all_cards:
            # The key for the structure dict is the normalized front
            structure[self._normalize_text(card_data["original_front"])] = card_data
            
        return structure

    def _parse_collection_block(self, block_content: str, collection_id: int) -> List[Dict[str, str]]:
        """
        Parses a single collection block to extract collection name, categories, and cards.
        WICHTIG: Extrahiert auch die originalen Display-Namen für Mapping.
        """
        parsed_cards = []
        
        # 1. Extract Collection Name
        # Updated regex to be more specific to the header format
        collection_name_match = re.search(r'# Sammlung \d+\s*\n\*\*(.+?)\*\*', block_content)
        if not collection_name_match:
             # Fallback for a simpler format, e.g., just **Name**
            collection_name_match = re.search(r'\*\*(.+?)\*\*', block_content)

        collection_name = collection_name_match.group(1).strip() if collection_name_match else f"Unbenannte_Sammlung_{collection_id}"
        
        # Create canonical collection key
        normalized_coll_name = self._normalize_for_key(collection_name)
        collection_key = f"collection_{collection_id}_{normalized_coll_name}"

        # WICHTIG: Speichere das Display-Name-Mapping für diese Collection
        self._collection_display_names[collection_key] = collection_name

        # 2. Isolate card area and parse categories and cards
        card_area_match = re.search(r'<!-- CARDS_START -->(.*?)<!-- CARDS_END -->', block_content, re.DOTALL)
        if not card_area_match:
            return [] # No cards in this block
            
        card_content = card_area_match.group(1)
        lines = card_content.split('\n')
        
        current_category_name = "unbekannt"
        current_category_key = "unbekannt"
        
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 3. Parse Category
            cat_match = re.search(r'^\*\*([A-Z])\.\s+([^\*]+)\*\*$', line)
            if cat_match:
                letter = cat_match.group(1)
                current_category_name = cat_match.group(2).strip()
                normalized_cat_name = self._normalize_for_key(current_category_name)
                # Erweitere das Längen-Limit für deutsche Namen
                current_category_key = f"{letter.lower()}_{normalized_cat_name[:50]}"
                
                # WICHTIG: Speichere das Display-Name-Mapping für diese Kategorie
                self._category_display_names[current_category_key] = current_category_name
                continue

            # 4. Parse Card
            card_match = re.search(r'^(\d+)\.\s+(.+)', line)
            if card_match:
                num = int(card_match.group(1))
                front = card_match.group(2).strip()
                
                if not front: # Skip empty card fronts
                    continue

                cat_letter = current_category_key.split('_')[0] if '_' in current_category_key else 'z'
                
                card_data = {
                    "original_front": front,
                    "collection": collection_key,
                    "category": current_category_key,
                    "sort_key": f"{collection_id:02d}_{cat_letter.upper()}_{num:02d}"
                }
                parsed_cards.append(card_data)
                
        return parsed_cards

    def _get_collection_display_name(self, collection_key: str) -> str:
        """
        Liefert den korrekten Display-Namen für eine Collection.
        Verwendet die gecachten originalen Namen oder fällt auf Rekonstruktion zurück.
        """
        if collection_key in self._collection_display_names:
            return self._collection_display_names[collection_key]

        # Fallback über ProjectConfig
        if self._config:
            cfg = self._config.collections.get(collection_key, {})
            if 'display_name' in cfg:
                return cfg['display_name']

        # Letzter Fallback: Rekonstruiere aus dem Schlüssel (ohne Sonderzeichen)
        parts = collection_key.split('_')
        if len(parts) >= 3:
            return ' '.join([p.capitalize() for p in parts[2:]])
        return collection_key

    def _get_collection_section_header(self, collection_key: str, coll_num: str) -> str:
        """Erzeugt die optionale Beschreibungsüberschrift für eine Collection im Markdown."""
        if self._config:
            cfg = self._config.collections.get(collection_key, {})
            display_name = cfg.get('display_name', self._get_collection_display_name(collection_key))
            description = cfg.get('description', '')
            header = f"### Liste aller Kartenvorderseiten (Fronts) für Deck {coll_num}: {display_name}"
            return f"{header}\n\n{description}\n" if description else f"{header}\n"
        name = self._get_collection_display_name(collection_key)
        return f"### Liste aller Kartenvorderseiten (Fronts) für Deck {coll_num}: {name}\n"

    def _get_category_display_name(self, category_key: str) -> str:
        """
        Liefert den korrekten Display-Namen für eine Kategorie.
        Verwendet die gecachten originalen Namen oder fällt auf Rekonstruktion zurück.
        """
        if category_key in self._category_display_names:
            return self._category_display_names[category_key]
        
        # Fallback: Rekonstruiere aus dem Schlüssel (ohne Sonderzeichen)
        parts = category_key.split('_')
        if len(parts) >= 2:
            return ' '.join([p.capitalize() for p in parts[1:]]).replace('_', ' ')
        return category_key



    def _prompt_resolve_back_conflict(self, front: str, backs: List[str], header_context: str | None) -> str | None:
        """
        Löst Back-Konflikte. Verwendet den übergebenen `header_context` für den LLM-Aufruf.
        """
        if header_context and len(backs) == 2:
            try:
                safe_print(f"🤖 Verwende LLM zur Lösung des Back-Konflikts für Karte: '{front}'")
                
                prompt_body = (
                    f"Aufgabe: Wähle die inhaltlich bessere und detailliertere Antwort für die folgende Anki-Karte. "
                    f"Antworte NUR mit der Ziffer der besten Option (z.B. '1' oder '2').\n\n"
                    f'KARTE: "{front}"\n\n'
                    f"OPTIONEN:\n"
                    f"[1] {backs[0]}\n"
                    f"[2] {backs[1]}\n\n"
                    f"Deine Wahl:"
                )
                
                decision = get_llm_decision(header_context, prompt_body)
                
                if decision and decision.strip() in ['1', '2']:
                    chosen_index = int(decision.strip()) - 1
                    safe_print(f"✅ LLM wählte Option {decision}: {backs[chosen_index][:100]}...")
                    return backs[chosen_index]
                else:
                    safe_print(f"⚠️ LLM gab ungültige Antwort '{decision}', falle auf manuelle Eingabe zurück.")
                    
            except Exception as e:
                safe_print(f"❌ LLM-Konfliktlösung fehlgeschlagen: {e}, falle auf manuelle Eingabe zurück.")
        
        # Manuelle Konfliktlösung als Fallback
        safe_print(f"\nKONFLIKT für Karte: '{front}'")
        safe_print("Mehrere unterschiedliche Antworten gefunden:")
        for i, back in enumerate(backs):
            # Zeige die vollständige Antwort oder maximal 1500 Zeichen
            display_back = back if len(back) <= 1500 else back[:1500] + "..."
            safe_print(f"  [{i+1}] {display_back}")
        
        while True:
            choice = input(f"Welche Version soll verwendet werden? [1-{len(backs)} / (s)kip]: ").lower()
            if choice == 's':
                return None
            if choice.isdigit() and 1 <= int(choice) <= len(backs):
                return backs[int(choice) - 1]

    def _prompt_resolve_orphan(self, front: str, markdown_structure: Dict) -> Tuple[str, str] | None:
        """
        Startet eine interaktive CLI zur Lösung von verwaisten Karten mit erweiterten Optionen.
        Gibt ein Tupel aus (collection_key, category_key) oder None zurück.
        """
        # Cache-Schlüssel ist der normalisierte Front
        cache_key = self._normalize_text(front)
        if cache_key in self._orphan_resolution_cache:
            return self._orphan_resolution_cache[cache_key]

        safe_print(f"\n{'='*20} VERWAISTE KARTE GEFUNDEN {'='*20}")
        safe_print(f"KARTE: '{front}'")
        safe_print("Diese Karte existiert in einer alten Collection, aber nicht im zentralen Review-Dokument.")
        
        while True:
            choice = input(
                "\nWas möchten Sie tun?\n"
                "  [z] Zuordnen:   Weisen Sie die Karte einer existierenden Kategorie zu.\n"
                "  [r] Retten:     Speichern Sie die Karte in einer separaten 'Gerettet'-Sammlung.\n"
                "  [i] Ignorieren: Verwerfen Sie diese einzelne Karte.\n"
                "  [a] Alle ignorieren: Verwerfen Sie diese und alle weiteren verwaisten Karten.\n"
                "Ihre Wahl: "
            ).lower()

            if choice == 'z':
                result = self._prompt_assign_to_category(markdown_structure)
                self._orphan_resolution_cache[cache_key] = result
                return result
            elif choice == 'r':
                # Signal zum Retten der Karte. Die Daten werden zwischengespeichert.
                # Wir geben hier ein spezielles Signal-Tupel zurück.
                result = ("__RESCUE__", "__RESCUE__")
                self._orphan_resolution_cache[cache_key] = result
                return result
            elif choice == 'i':
                result = None
                self._orphan_resolution_cache[cache_key] = result
                return result
            elif choice == 'a':
                # Setze den Cache für alle zukünftigen Anfragen auf "ignorieren"
                self._orphan_resolution_cache['__ALL__'] = None
                result = None
                self._orphan_resolution_cache[cache_key] = result
                return result
            else:
                safe_print("Ungültige Eingabe, bitte erneut versuchen.")

    def _prompt_assign_to_category(self, markdown_structure: Dict) -> Tuple[str, str] | None:
        """Zeigt eine Auswahl zur Zuordnung zu Collection/Kategorie."""
        # 1. Baue eine Struktur aus den Markdown-Daten: {collection_key: {category_key: name}}
        structure = {}
        for meta in markdown_structure.values():
            coll_key = meta.get('collection')
            cat_key = meta.get('category')
            if not coll_key or not cat_key:
                continue
            if coll_key not in structure:
                structure[coll_key] = {}
            if cat_key not in structure[coll_key]:
                # Wir brauchen einen menschenlesbaren Namen
                # z.B. aus a_grundlagen -> A. Grundlagen
                cat_parts = cat_key.split('_')
                cat_letter = cat_parts[0].upper()
                cat_name = ' '.join([p.capitalize() for p in cat_parts[1:]]).replace('_', ' ')
                structure[coll_key][cat_key] = f"{cat_letter}. {cat_name}"

        if not structure:
            safe_print("Keine Collections/Kategorien im Markdown-Dokument gefunden. Zuordnung nicht möglich.")
            return None

        # 2. Lasse den Benutzer eine Collection wählen
        sorted_collections = sorted(structure.keys(), key=lambda k: int(k.split('_')[1]))
        safe_print("\n--- Wählen Sie eine Sammlung ---")
        for i, coll_key in enumerate(sorted_collections):
            coll_parts = coll_key.split('_')
            coll_name = ' '.join([p.capitalize() for p in coll_parts[2:]])
            safe_print(f"  [{i+1}] {coll_name}")
        
        try:
            coll_choice_idx = int(input(f"Ihre Wahl [1-{len(sorted_collections)}]: ")) - 1
            if not 0 <= coll_choice_idx < len(sorted_collections):
                raise ValueError
            chosen_coll_key = sorted_collections[coll_choice_idx]
        except (ValueError, IndexError):
            safe_print("Ungültige Eingabe. Abbruch.")
            return None

        # 3. Lasse den Benutzer eine Kategorie wählen
        sorted_categories = sorted(structure[chosen_coll_key].keys())
        safe_print(f"\n--- Wählen Sie eine Kategorie für '{chosen_coll_key}' ---")
        for i, cat_key in enumerate(sorted_categories):
            safe_print(f"  [{i+1}] {structure[chosen_coll_key][cat_key]}")

        try:
            cat_choice_idx = int(input(f"Ihre Wahl [1-{len(sorted_categories)}]: ")) - 1
            if not 0 <= cat_choice_idx < len(sorted_categories):
                raise ValueError
            chosen_cat_key = sorted_categories[cat_choice_idx]
        except (ValueError, IndexError):
            safe_print("Ungültige Eingabe. Abbruch.")
            return None
            
        return chosen_coll_key, chosen_cat_key

    def _prompt_create_missing(self, front: str) -> str | None:
        """Fragt den Benutzer nach dem Inhalt für eine fehlende Karte."""
        safe_print(f"\nHINWEIS: Fehlende Karte: '{front}'")
        safe_print("Diese Karte ist im Review-Dokument gelistet, hat aber keinen Inhalt.")
        back = input("Bitte Antworttext eingeben (oder leer lassen zum Überspringen):\n> ")
        return back if back.strip() else None

    def _normalize_text(self, text: str) -> str:
        """Normalisiert Text für Vergleiche."""
        return re.sub(r'\s+', ' ', text).strip().lower()

    def _normalize_for_key(self, text: str) -> str:
        """
        Normalisiert Text für interne Schlüssel mit korrekter Umlaut-Ersetzung.
        Ersetzt deutsche Sonderzeichen anstatt sie zu löschen.
        """
        # Erst zu lowercase und Leerzeichen normalisieren
        normalized = re.sub(r'\s+', ' ', text).strip().lower()
        
        # Deutsche Umlaute und Sonderzeichen ersetzen (nicht löschen!)
        umlaut_map = {
            'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
            '&': 'und', 'é': 'e', 'è': 'e', 'à': 'a', 'á': 'a'
        }
        
        for umlaut, replacement in umlaut_map.items():
            normalized = normalized.replace(umlaut, replacement)
        
        # Leerzeichen durch Unterstriche ersetzen
        normalized = normalized.replace(' ', '_')
        
        # Nur illegale Zeichen entfernen (nach Ersetzung)
        normalized = re.sub(r'[^a-z0-9_]', '', normalized)
        
        return normalized

    def _generate_sort_field(self, sort_key: str, front: str) -> str:
        """Generiert ein standardisiertes Sortierfeld."""
        normalized_front = self._normalize_text(front).replace(' ', '_')
        return f"{sort_key}_{re.sub(r'[^a-z0-9_]', '', normalized_front)[:50]}"

    def _generate_tags(self, collection: str, category: str) -> List[str]:
        """Generiert hierarchische Tags."""
        try:
            # collection_0_coll_a -> C0_Coll_A
            coll_parts = collection.split('_')
            coll_name = '_'.join([p.capitalize() for p in coll_parts[2:]])
            coll_tag = f"C{coll_parts[1]}_{coll_name}"
            
            # a_cat_x -> A_Cat_X
            cat_parts = category.split('_')
            cat_name = '_'.join([p.capitalize() for p in cat_parts[1:]])
            cat_tag = f"{cat_parts[0].upper()}_{cat_name}"

            return [f"{self._tag_prefix}::{coll_tag}::{cat_tag}"]
        except IndexError:
            return [f"{self._tag_prefix}::Unkategorisiert"]

    def _build_categorization_prompt(self, markdown_structure: dict) -> tuple[str, dict] | tuple[None, None]:
        """Baut den "aufgeklappten" Prompt für die LLM-Kategorisierung und eine Mapping-Struktur."""
        prompt_lines = ["Aufgabe: Ordne die folgende Karte der am besten passenden Kategorie zu. Antworte NUR mit dem Code (z.B. '3C').\n"]
        
        # Baue eine Struktur, um die Keys den Nummern/Buchstaben zuzuordnen
        mapping = {"collections": {}, "categories": {}}

        # Gruppiere Kategorien nach Collection
        structure_by_collection = {}
        for meta in markdown_structure.values():
            coll_key, cat_key = meta.get('collection'), meta.get('category')
            if not coll_key or not cat_key: continue
            if coll_key not in structure_by_collection:
                structure_by_collection[coll_key] = set()
            structure_by_collection[coll_key].add(cat_key)

        if not structure_by_collection: return None, None

        # Baue den Collection-Teil des Prompts
        prompt_lines.append("--- WÄHLE EINE SAMMLUNG ---")
        sorted_collections = sorted(structure_by_collection.keys(), key=lambda k: int(k.split('_')[1]))
        for i, coll_key in enumerate(sorted_collections):
            coll_num = i + 1
            mapping["collections"][str(coll_num)] = coll_key
            prompt_lines.append(f"  [{coll_num}] {self._get_collection_display_name(coll_key)}")
        
        # Baue den Kategorie-Teil des Prompts
        for i, coll_key in enumerate(sorted_collections):
            coll_num = i + 1
            prompt_lines.append(f"\n--- KATEGORIEN FÜR SAMMLUNG [{coll_num}] ---")
            mapping["categories"][coll_key] = {}
            # Sortiere Kategorien alphabetisch nach ihrem Key (a_..., b_...)
            sorted_categories = sorted(list(structure_by_collection[coll_key]))
            for j, cat_key in enumerate(sorted_categories):
                letter = chr(ord('A') + j)
                mapping["categories"][coll_key][letter] = cat_key
                prompt_lines.append(f"  [{letter}] {self._get_category_display_name(cat_key)}")

        return "\n".join(prompt_lines), mapping

    def _parse_llm_categorization_response(self, response: str, mapping: dict) -> tuple[str, str] | None:
        """Parst die LLM-Antwort (z.B. '3C') und übersetzt sie in Collection/Category-Keys."""
        if not response or not mapping: return None
        
        # Einfache Regex, um einen Code wie '3C' oder '1A' zu finden.
        match = re.search(r'\b([1-9]\d*)([A-Z])\b', response.upper())
        if not match:
            safe_print(f"⚠️ LLM-Kategorisierungs-Antwort ('{response}') konnte nicht geparst werden.", "WARNING")
            return None
        
        coll_num_str, cat_letter = match.groups()
        
        # Übersetze die Nummer in den Collection-Key
        collection_key = mapping.get("collections", {}).get(coll_num_str)
        if not collection_key:
            safe_print(f"⚠️ Ungültige Collection-Nummer '{coll_num_str}' vom LLM erhalten.", "WARNING")
            return None
        
        # Übersetze den Buchstaben in den Category-Key
        category_key = mapping.get("categories", {}).get(collection_key, {}).get(cat_letter)
        if not category_key:
            safe_print(f"⚠️ Ungültiger Kategorie-Buchstabe '{cat_letter}' für Collection '{collection_key}' vom LLM erhalten.", "WARNING")
            return None
            
        safe_print(f"✅ LLM hat Karte erfolgreich zugeordnet: {collection_key} -> {category_key}", "SUCCESS")
        return collection_key, category_key

    def integrate_new(self, new_cards_data: List[Dict[str, Any]]) -> int:
        """
        Integrates new cards from a list of dictionaries into the database,
        handling duplicates and assigning them to a default new-card category.
        """
        safe_print(f"🚀 Integriere {len(new_cards_data)} neue Karten...")
        # This check is important. If cards are set manually in a test
        # but the file doesn't exist, load_database() would overwrite the test data.
        if not self.cards and os.path.exists(self.db_path):
            self.load_database()

        existing_fronts = {self._normalize_text(card.front) for card in self.cards}
        added_count = 0
        now = datetime.now()

        # Finde die höchste Collection-Nummer, um eine neue zu erstellen
        max_coll_num = -1
        for card in self.cards:
            try:
                num = int(card.collection.split('_')[1])
                if num > max_coll_num:
                    max_coll_num = num
            except (IndexError, ValueError):
                continue
        
        new_coll_num = max_coll_num + 1
        new_collection_key = f"collection_{new_coll_num}_Neue_Karten"
        new_category_key = "a_Unsortiert"

        for i, card_data in enumerate(new_cards_data):
            front = card_data.get("front", "").strip()
            back = card_data.get("back", "").strip()

            if not front or not back:
                safe_print(f" überspringe Karte ohne Front oder Back: {card_data}")
                continue

            normalized_front = self._normalize_text(front)
            if normalized_front in existing_fronts:
                safe_print(f" überspringe doppelte Karte: '{front}'")
                continue

            sort_key = f"{new_coll_num:02d}_A_{i+1:02d}"
            new_card = AnkiCard(
                guid=str(uuid.uuid4()),
                front=front,
                back=back,
                collection=new_collection_key,
                category=new_category_key,
                sort_field=self._generate_sort_field(sort_key, front),
                tags=self._generate_tags(new_collection_key, new_category_key),
                created_at=now,
                updated_at=now
            )
            self.cards.append(new_card)
            existing_fronts.add(normalized_front)
            added_count += 1

        if added_count > 0:
            self.save_database()
            safe_print(f"✅ {added_count} neue Karten erfolgreich integriert.")
        else:
            safe_print("ℹ️ Keine neuen Karten hinzugefügt.")
        
        return added_count

    def distribute_to_derived_files(self, output_dir: str):
        """
        Generates all derived files (collection_*.json, All_collections_only_fronts.md)
        from the SSOT. This overwrites existing files.
        """
        if not self.cards:
            safe_print("⚠️ Datenbank ist leer. Es werden keine Dateien verteilt.")
            return False

        os.makedirs(output_dir, exist_ok=True)
        safe_print(f"""🚀 Verteile Karten aus der SSOT in den Ordner '{output_dir}'...""")

        # 1. Karten nach Collection für JSON-Dateien gruppieren
        collections: Dict[str, List[Dict[str, str]]] = {}
        for card in self.cards:
            if card.collection not in collections:
                collections[card.collection] = []
            # Export mit allen Metadaten-Feldern
            card_data = {
                "front": card.front,
                "back": card.back,
                "tags": card.tags,
                "guid": card.guid,
                "sort_field": card.sort_field
            }
            collections[card.collection].append(card_data)

        # Schreibe die collection_*.json Dateien mit Legacy-Namen
        for collection_name, cards_data in collections.items():
            # Verwende Mapping für Legacy-Dateinamen
            if collection_name in self.collection_filename_mapping:
                filename = self.collection_filename_mapping[collection_name]
            else:
                # Fallback für neue Collections ohne Mapping
                filename = f"{collection_name}.json"
            
            file_path = os.path.join(output_dir, filename)
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(cards_data, f, indent=2, ensure_ascii=False)
                safe_print(f"  -> ✅ Datei '{file_path}' geschrieben.")
            except Exception as e:
                safe_print(f"""  -> ❌ Fehler beim Schreiben von '{file_path}': {e}""")

        # 2. Generiere die All_collections_only_fronts.md Datei
        self._update_markdown_file(output_dir)

        # 3. Generiere frische Template-JSON für LLM
        self.generate_fresh_template_json(output_dir)

        safe_print("✅ Verteilung abgeschlossen.")
        return True

    def _update_markdown_file(self, output_dir: str):
        """
        Updates the markdown file with the current card list, preserving the header.
        """
        md_file_path = os.path.join(output_dir, "All_collections_only_fronts.md")
        marker = "<!-- ANKI_CARD_LIST_START -->"
        
        header_content = ""
        if os.path.exists(md_file_path):
            with open(md_file_path, 'r', encoding='utf-8') as f:
                full_content = f.read()
            
            marker_pos = full_content.find(marker)
            if marker_pos != -1:
                header_content = full_content[:marker_pos]
            else:
                # If marker not found, preserve the whole file as header and add marker
                header_content = full_content + "\n\n"
        
        # Generate the new card list content
        card_list_content = self._generate_markdown_card_list()

        # Write back to the file
        try:
            with open(md_file_path, 'w', encoding='utf-8') as f:
                f.write(header_content)
                f.write(marker + "\n\n")
                f.write(card_list_content)
            safe_print(f"""  -> ✅ Datei '{md_file_path}' geschrieben.""")
        except Exception as e:
            safe_print(f"""  -> ❌ Fehler beim Schreiben von '{md_file_path}': {e}""")

    def _generate_markdown_card_list(self) -> str:
        """
        Generates the markdown string for the list of card fronts with proper marker structure.
        """
        if not self.cards:
            return ""

        # Sortiere alle Karten nach ihrem Sortierfeld für die korrekte Reihenfolge
        sorted_cards = sorted(self.cards, key=lambda c: c.sort_field)

        # Gruppiere nach Collection und dann nach Kategorie
        structure: Dict[str, Dict[str, List[AnkiCard]]] = {}
        for card in sorted_cards:
            if card.collection not in structure:
                structure[card.collection] = {}
            if card.category not in structure[card.collection]:
                structure[card.collection][card.category] = []
            structure[card.collection][card.category].append(card)

        # Baue den Markdown-Inhalt mit korrekter Marker-Struktur
        md_content = []
        # Extrahiere und sortiere die Collections-Schlüssel numerisch
        sorted_collection_keys = sorted(structure.keys(), key=lambda k: int(k.split('_')[1]))

        for collection_key in sorted_collection_keys:
            collection_data = structure[collection_key]
            # Extrahiere Nummer aus dem Schlüssel und verwende originalen Display-Namen
            coll_parts = collection_key.split('_')
            coll_num = coll_parts[1]
            coll_name = self._get_collection_display_name(collection_key)
            
            # Collection Start Marker
            md_content.append(f"<!-- COLLECTION_{coll_num}_START -->")
            md_content.append(f"# Sammlung {coll_num}")
            md_content.append("")
            md_content.append(f"**{coll_name}**")
            md_content.append("")
            
            # Cards Start Marker
            md_content.append("<!-- CARDS_START -->")
            md_content.append("***")
            md_content.append("")

            # Beschreibungstext für die Collection hinzufügen (optional)
            coll_header = self._get_collection_section_header(collection_key, coll_num)
            if coll_header:
                md_content.append(coll_header)

            # Extrahiere und sortiere die Kategorie-Schlüssel alphabetisch
            sorted_category_keys_inner = sorted(collection_data.keys(), key=lambda k: k.split('_')[0])

            for category_key_inner in sorted_category_keys_inner:
                cards_in_cat = collection_data[category_key_inner]
                # Verwende originalen Display-Namen für die Kategorie
                cat_parts = category_key_inner.split('_')
                cat_letter = cat_parts[0].upper()
                cat_display_name = self._get_category_display_name(category_key_inner)
                md_content.append(f"**{cat_letter}. {cat_display_name}**")

                # Sort cards within a category by their sort_field to ensure consistent numbering
                sorted_cards_in_cat = sorted(cards_in_cat, key=lambda c: c.sort_field)
                for i, card in enumerate(sorted_cards_in_cat):
                    md_content.append(f"{i+1}. {card.front}")
                md_content.append("") # Leerzeile nach jeder Kategorie
            
            # Cards End Marker
            md_content.append("<!-- CARDS_END -->")
            # Collection End Marker  
            md_content.append(f"<!-- COLLECTION_{coll_num}_END -->")
            md_content.append("")
            md_content.append("---") # Trennlinie zwischen Collections

        return '\n'.join(md_content)

    def verify_integrity(self, derived_files_dir: str, pending_new_cards: List[dict] = None) -> Tuple[bool, str]:
        """
        Verifies the integrity of the system.
        1. Internal check: GUID uniqueness in the database.
        2. External check: Compares on-disk derived files with freshly
           generated ones from the SSOT.
        
        Args:
            derived_files_dir: Directory containing derived files to verify against
            pending_new_cards: Optional list of new cards that will be integrated.
                              If provided, the integrity check will account for these
                              cards when comparing against new_cards_output.json.
        """
        safe_print("🔍 Überprüfe Integrität des Systems...")

        # 1. Interne Prüfung: GUID-Eindeutigkeit
        guids = [card.guid for card in self.cards]
        if len(guids) != len(set(guids)):
            from collections import Counter
            counts = Counter(guids)
            dupes = {guid for guid, count in counts.items() if count > 1}
            message = f"Doppelte GUIDs gefunden: {dupes}"
            safe_print(f"❌ Integritätsfehler: {message}")
            return False, message
        safe_print("  -> ✅ Interne GUID-Prüfung erfolgreich.")

        # 2. Externe Prüfung: Vergleich mit abgeleiteten Dateien
        temp_dir = derived_files_dir + "_temp_verify"
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        
        integrity_ok = True
        try:
            # Generiere frische Dateien an einem temporären Ort
            if not self.distribute_to_derived_files(temp_dir):
                # This can happen if the DB is empty. Check if the original is also empty.
                if not os.path.exists(derived_files_dir) or not os.listdir(derived_files_dir):
                    message = "Externe Prüfung erfolgreich. Quelldatenbank und Zielverzeichnis sind beide leer."
                    safe_print(f"✅ {message}")
                    return True, message
                else:
                    message = "Integritätsfehler: Quelldatenbank ist leer, aber das Zielverzeichnis nicht."
                    safe_print(f"❌ {message}")
                    return False, message

            safe_print(f"  -> Vergleiche abgeleitete Dateien in '{derived_files_dir}' mit der SSOT...")

            # Vergleiche nur die relevanten Collection-Dateien (nicht alle Dateien im Verzeichnis)
            # Definiere welche Dateien relevant sind
            relevant_files = set()
            
            # Sammle alle collection_*.json Dateien aus der SSOT mit Legacy-Namen
            collections_in_ssot = set(card.collection for card in self.cards)
            for collection_name in collections_in_ssot:
                # Verwende Mapping für Legacy-Dateinamen
                if collection_name in self.collection_filename_mapping:
                    filename = self.collection_filename_mapping[collection_name]
                else:
                    # Fallback für neue Collections ohne Mapping
                    filename = f"{collection_name}.json"
                relevant_files.add(filename)
            
            # Füge die Markdown-Datei und Template-JSON hinzu
            relevant_files.add("All_collections_only_fronts.md")
            relevant_files.add("new_cards_output.json")
            
            # Filtere die Dateien auf relevante
            temp_files = set(os.listdir(temp_dir)) & relevant_files
            live_files = set(os.listdir(derived_files_dir) if os.path.exists(derived_files_dir) else []) & relevant_files

            integrity_ok = True
            error_messages = []

            if temp_files != live_files:
                integrity_ok = False
                sot_only = sorted(list(temp_files - live_files))
                target_only = sorted(list(live_files - temp_files))
                message = "Diskrepanz in den Collection-Dateien."
                if sot_only: message += f" Dateien nur in SSOT: {sot_only}"
                if target_only: message += f" Dateien nur im Ziel: {target_only}"
                error_messages.append(message)

            # Check content of common files
            common_files = sorted(list(temp_files & live_files))
            for filename in common_files:
                temp_path = os.path.join(temp_dir, filename)
                live_path = os.path.join(derived_files_dir, filename)
                
                with open(temp_path, 'r', encoding='utf-8') as f1, open(live_path, 'r', encoding='utf-8') as f2:
                    # Special handling for new_cards_output.json when pending cards are expected
                    if filename == "new_cards_output.json" and pending_new_cards is not None:
                        # Parse the fresh template
                        try:
                            content1 = f1.read()
                            temp_data = json.loads(content1)
                            
                            # Simulate what the template would look like with pending cards
                            expected_data = self._simulate_integrated_template(temp_data, pending_new_cards)
                            
                            # Re-read the live file and reconstruct its structure with pending cards
                            # This simulates what the workflow_manager does: parse + add metadata
                            f2.seek(0)
                            content2 = f2.read()
                            live_data_raw = json.loads(content2)
                            
                            # Reconstruct the live data as the workflow_manager would see it
                            reconstructed_live_data = self._reconstruct_live_data_with_metadata(live_data_raw)
                            
                            # Compare the simulated data with the reconstructed live data
                            expected_json = json.dumps(expected_data, sort_keys=True)
                            live_json = json.dumps(reconstructed_live_data, sort_keys=True)
                            
                            if expected_json != live_json:
                                # Debug output for troubleshooting
                                safe_print(f"    DEBUG: {filename} mismatch detected:")
                                safe_print(f"    Expected length: {len(expected_json)}, Live length: {len(live_json)}")
                                
                                # Save debug files for comparison
                                debug_expected_path = f"debug_expected_{filename}"
                                debug_live_path = f"debug_live_{filename}"
                                with open(debug_expected_path, 'w', encoding='utf-8') as debug_f:
                                    debug_f.write(json.dumps(expected_data, sort_keys=True, indent=2))
                                with open(debug_live_path, 'w', encoding='utf-8') as debug_f:
                                    debug_f.write(json.dumps(reconstructed_live_data, sort_keys=True, indent=2))
                                safe_print(f"    Debug files saved: {debug_expected_path}, {debug_live_path}")
                                
                                error_messages.append(f"Inhalt von '{filename}' stimmt nicht mit erwartetem Zustand (inklusive pending cards) überein.")
                                integrity_ok = False
                            # Skip the regular file comparison for this file since we handled it specially
                            continue
                        except json.JSONDecodeError:
                            # Fall back to regular text comparison if JSON parsing fails
                            if content1 != content2:
                                error_messages.append(f"Inhalt von '{filename}' stimmt nicht überein (JSON-Parsing fehlgeschlagen).")
                                integrity_ok = False
                            continue
                    # For markdown, only compare content after the marker
                    elif filename == "All_collections_only_fronts.md":
                        marker = "<!-- ANKI_CARD_LIST_START -->"
                        
                        content1_full = f1.read()
                        content2_full = f2.read()

                        pos1 = content1_full.find(marker)
                        pos2 = content2_full.find(marker)

                        content1 = content1_full[pos1:] if pos1 != -1 else content1_full
                        content2 = content2_full[pos2:] if pos2 != -1 else content2_full
                    else:
                        content1 = f1.read()
                        content2 = f2.read()

                    # Normalize content for comparison (line endings)
                    content1 = content1.strip().replace('\r\n', '\n')
                    content2 = content2.strip().replace('\r\n', '\n')
                
                if content1 != content2:
                    error_messages.append(f"""Inhalt von '{filename}' stimmt nicht überein.""")
                    # Debug: Show first differences for markdown files
                    if filename == "All_collections_only_fronts.md":
                        lines1 = content1.split('\n')
                        lines2 = content2.split('\n')
                        safe_print(f"    DEBUG: Markdown differences detected:")
                        safe_print(f"    Fresh content has {len(lines1)} lines")
                        safe_print(f"    Existing content has {len(lines2)} lines")
                        found_diff = False
                        for i, (line1, line2) in enumerate(zip(lines1, lines2)):
                            if line1 != line2:
                                safe_print(f"    Line {i+1} differs:")
                                safe_print(f"      Fresh:    '{line1[:100]}'")
                                safe_print(f"      Existing: '{line2[:100]}'")
                                found_diff = True
                                break
                        if not found_diff and len(lines1) != len(lines2):
                            safe_print(f"    Files have different line counts but common lines are identical")
                    integrity_ok = False
            
            if integrity_ok:
                final_message = "Integrität erfolgreich überprüft. Alle Dateien sind synchron."
                safe_print(f"✅ {final_message}")
                return True, final_message
            else:
                final_message = "Externe Prüfung fehlgeschlagen. " + " ".join(error_messages)
                safe_print(f"❌ {final_message}")
                return False, final_message

        except Exception as e:
            message = f"Ein Fehler ist während der Integritätsprüfung aufgetreten: {e}"
            safe_print(f"❌ {message}")
            return False, message
        finally:
            # Bereinige das temporäre Verzeichnis
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    def reconstruct_from_collections(self, force: bool = False) -> bool:
        """
        Rekonstruiert die card_database.json aus vorhandenen collection_*.json Dateien.
        Diese Methode behandelt Collections als neue Single Source of Truth.
        
        Args:
            force: Wenn True, überschreibt bestehende card_database.json
            
        Returns:
            bool: True wenn erfolgreich rekonstruiert, False bei Fehlern
        """
        # Prüfe ob Rekonstruktion nötig ist
        if os.path.exists(self.db_path) and not force:
            file_size = os.path.getsize(self.db_path)
            if file_size > 10:  # Nicht leer (mehr als nur "[]")
                safe_print(f"⚠️ card_database.json existiert bereits ({file_size} bytes). Nutze force=True zum Überschreiben.")
                return False
        
        # Finde alle collection_*.json Dateien
        import glob
        collection_files = glob.glob("collection_*.json")
        
        if not collection_files:
            safe_print("❌ Keine collection_*.json Dateien gefunden.")
            return False
            
        safe_print(f"🔄 Rekonstruiere Datenbank aus {len(collection_files)} Collections...")
        
        # Sammle alle Karten aus Collections
        all_cards = []
        for collection_file in sorted(collection_files):
            # Extrahiere Collection-Name aus Dateiname
            match = re.match(r'collection_(\d+)_(.+)\.json', collection_file)
            if not match:
                safe_print(f"⚠️ Unbekanntes Dateiformat: {collection_file}")
                continue
                
            collection_id, collection_name = match.groups()
            collection_name = collection_name.replace('_', ' ')
            
            try:
                with open(collection_file, 'r', encoding='utf-8') as f:
                    cards_data = json.load(f)
                    
                for card_data in cards_data:
                    # Legacy Format: nur front/back -> erweitere zu vollem Format
                    if isinstance(card_data, dict) and 'front' in card_data and 'back' in card_data:
                        anki_card = AnkiCard(
                            front=card_data['front'],
                            back=card_data['back'],
                            collection=collection_name,
                            tags=[collection_name.lower().replace(' ', '_')],
                            guid=str(uuid.uuid4()),
                            sort_field=card_data['front']
                        )
                        all_cards.append(anki_card)
                    else:
                        # Bereits vollständiges Format
                        all_cards.append(AnkiCard.from_dict(card_data))
                        
                safe_print(f"✅ {len(cards_data)} Karten aus {collection_name} geladen")
                
            except Exception as e:
                safe_print(f"❌ Fehler beim Laden von {collection_file}: {e}")
                return False
        
        # Speichere rekonstruierte Datenbank
        self.cards = all_cards
        success = self.save_database()
        
        if success:
            safe_print(f"✅ Datenbank erfolgreich rekonstruiert: {len(all_cards)} Karten")
            # Regeneriere auch das Markdown
            self._update_markdown_file(".")
            return True
        else:
            safe_print("❌ Fehler beim Speichern der rekonstruierten Datenbank")
            return False

    def run_post_extract_tests(self, output_dir: str) -> Tuple[bool, List[str]]:
        """
        Runs comprehensive post-extract validation tests to ensure the system is working correctly.
        
        These are additional tests beyond the standard integrity check, focusing on 
        marker structure, file consistency, and data quality.
        
        Returns:
            Tuple[bool, List[str]]: (success, list_of_messages)
        """
        safe_print("🧪 Führe Post-Extract-Validierungstests durch...")
        
        test_results = []
        all_passed = True
        
        # Test 1: Marker-Struktur Validation
        safe_print("  -> Test 1: Marker-Struktur in All_collections_only_fronts.md")
        marker_test_passed, marker_message = self._test_marker_structure(output_dir)
        test_results.append(f"Marker-Test: {'✅ PASS' if marker_test_passed else '❌ FAIL'} - {marker_message}")
        if not marker_test_passed:
            all_passed = False
        
        # Test 2: Collection File Names Mapping
        safe_print("  -> Test 2: Collection-Dateinamen-Mapping")
        filename_test_passed, filename_message = self._test_collection_filenames(output_dir)
        test_results.append(f"Filename-Test: {'✅ PASS' if filename_test_passed else '❌ FAIL'} - {filename_message}")
        if not filename_test_passed:
            all_passed = False
        
        # Test 3: Card Count Consistency 
        safe_print("  -> Test 3: Karten-Anzahl-Konsistenz")
        count_test_passed, count_message = self._test_card_count_consistency(output_dir)
        test_results.append(f"Count-Test: {'✅ PASS' if count_test_passed else '❌ FAIL'} - {count_message}")
        if not count_test_passed:
            all_passed = False
        
        # Test 4: JSON Structure Validation
        safe_print("  -> Test 4: JSON-Struktur-Validierung")
        json_test_passed, json_message = self._test_json_structure(output_dir)
        test_results.append(f"JSON-Test: {'✅ PASS' if json_test_passed else '❌ FAIL'} - {json_message}")
        if not json_test_passed:
            all_passed = False
        
        # Test 5: Collection-Kategorie-Hierarchie
        safe_print("  -> Test 5: Collection-Kategorie-Hierarchie")
        hierarchy_test_passed, hierarchy_message = self._test_collection_hierarchy()
        test_results.append(f"Hierarchy-Test: {'✅ PASS' if hierarchy_test_passed else '❌ FAIL'} - {hierarchy_message}")
        if not hierarchy_test_passed:
            all_passed = False
        
        # Test 6: GUID Uniqueness (redundant mit verify_integrity, aber explizit)
        safe_print("  -> Test 6: GUID-Eindeutigkeit")
        guid_test_passed, guid_message = self._test_guid_uniqueness()
        test_results.append(f"GUID-Test: {'✅ PASS' if guid_test_passed else '❌ FAIL'} - {guid_message}")
        if not guid_test_passed:
            all_passed = False
        
        # Zusammenfassung
        status_icon = "✅" if all_passed else "❌"
        safe_print(f"\n{status_icon} Post-Extract-Tests: {'ALLE BESTANDEN' if all_passed else 'FEHLER GEFUNDEN'}")
        
        return all_passed, test_results

    def _test_marker_structure(self, output_dir: str) -> Tuple[bool, str]:
        """Test: Validates that All_collections_only_fronts.md has correct marker structure."""
        md_file_path = os.path.join(output_dir, "All_collections_only_fronts.md")
        
        if not os.path.exists(md_file_path):
            return False, "All_collections_only_fronts.md nicht gefunden"
        
        try:
            with open(md_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for ANKI_CARD_LIST_START marker
            if "<!-- ANKI_CARD_LIST_START -->" not in content:
                return False, "ANKI_CARD_LIST_START Marker fehlt"
            
            # Count collection markers
            collection_start_markers = len(re.findall(r'<!-- COLLECTION_(\d+)_START -->', content))
            collection_end_markers = len(re.findall(r'<!-- COLLECTION_(\d+)_END -->', content))
            
            if collection_start_markers != collection_end_markers:
                return False, f"Ungleiche Collection-Marker: {collection_start_markers} START vs {collection_end_markers} END"
            
            # Count cards markers
            cards_start_markers = content.count("<!-- CARDS_START -->")
            cards_end_markers = content.count("<!-- CARDS_END -->")
            
            if cards_start_markers != cards_end_markers:
                return False, f"Ungleiche Cards-Marker: {cards_start_markers} START vs {cards_end_markers} END"
            
            if collection_start_markers != cards_start_markers:
                return False, f"Collection- und Cards-Marker stimmen nicht überein: {collection_start_markers} vs {cards_start_markers}"
            
            # Check for expected collections (0-6)
            collections_in_ssot = set(card.collection for card in self.cards)
            expected_collection_count = len(collections_in_ssot)
            
            if collection_start_markers != expected_collection_count:
                return False, f"Marker-Anzahl stimmt nicht mit SSOT überein: {collection_start_markers} Marker vs {expected_collection_count} Collections"
            
            return True, f"{collection_start_markers} Collections mit korrekter Marker-Struktur"
            
        except Exception as e:
            return False, f"Fehler beim Lesen der Markdown-Datei: {e}"

    def _test_collection_filenames(self, output_dir: str) -> Tuple[bool, str]:
        """Test: Validates that collection files use correct legacy naming."""
        expected_files = set()
        
        # Build expected filenames using mapping
        collections_in_ssot = set(card.collection for card in self.cards)
        for collection_name in collections_in_ssot:
            if collection_name in self.collection_filename_mapping:
                expected_files.add(self.collection_filename_mapping[collection_name])
            else:
                expected_files.add(f"{collection_name}.json")
        
        # Check which files actually exist
        actual_files = set()
        for filename in os.listdir(output_dir):
            if filename.startswith('collection_') and filename.endswith('.json'):
                actual_files.add(filename)
        
        missing_files = expected_files - actual_files
        extra_files = actual_files - expected_files

        # Toleriere stale Rescue-Collection-Dateien (entstehen nach Bootstrap mit Orphan-Rettung,
        # wenn die geretteten Karten später in andere Collections verschoben wurden)
        orphan_pattern = self._orphan_collection.replace(' ', '_')
        extra_files = {f for f in extra_files if orphan_pattern.lower() not in f.lower()}

        if missing_files or extra_files:
            message = ""
            if missing_files:
                message += f"Fehlende Dateien: {sorted(missing_files)} "
            if extra_files:
                message += f"Unerwartete Dateien: {sorted(extra_files)}"
            return False, message.strip()

        return True, f"{len(expected_files)} Collection-Dateien mit korrekten Legacy-Namen"

    def _test_card_count_consistency(self, output_dir: str) -> Tuple[bool, str]:
        """Test: Validates card counts between SSOT and generated files."""
        total_cards_in_ssot = len(self.cards)
        
        # Count cards in collection JSON files
        total_cards_in_files = 0
        collections_in_ssot = set(card.collection for card in self.cards)
        
        for collection_name in collections_in_ssot:
            if collection_name in self.collection_filename_mapping:
                filename = self.collection_filename_mapping[collection_name]
            else:
                filename = f"{collection_name}.json"
            
            file_path = os.path.join(output_dir, filename)
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        cards_data = json.load(f)
                        total_cards_in_files += len(cards_data)
                except Exception as e:
                    return False, f"Fehler beim Lesen von {filename}: {e}"
            else:
                return False, f"Collection-Datei {filename} nicht gefunden"
        
        if total_cards_in_ssot != total_cards_in_files:
            return False, f"Karten-Anzahl stimmt nicht überein: SSOT={total_cards_in_ssot}, Dateien={total_cards_in_files}"
        
        return True, f"{total_cards_in_ssot} Karten konsistent zwischen SSOT und Dateien"

    def _test_json_structure(self, output_dir: str) -> Tuple[bool, str]:
        """Test: Validates JSON structure of collection files."""
        collections_in_ssot = set(card.collection for card in self.cards)
        required_fields = {"front", "back", "tags", "guid", "sort_field"}
        
        for collection_name in collections_in_ssot:
            if collection_name in self.collection_filename_mapping:
                filename = self.collection_filename_mapping[collection_name]
            else:
                filename = f"{collection_name}.json"
            
            file_path = os.path.join(output_dir, filename)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    cards_data = json.load(f)
                
                if not isinstance(cards_data, list):
                    return False, f"{filename}: JSON ist keine Liste"
                
                for i, card in enumerate(cards_data):
                    if not isinstance(card, dict):
                        return False, f"{filename}: Karte {i} ist kein Dictionary"
                    
                    missing_fields = required_fields - set(card.keys())
                    if missing_fields:
                        return False, f"{filename}: Karte {i} fehlen Felder: {missing_fields}"
                    
                    # Check for empty required fields
                    if not card.get("front", "").strip():
                        return False, f"{filename}: Karte {i} hat leeren Front"
                    if not card.get("back", "").strip():
                        return False, f"{filename}: Karte {i} hat leeren Back"
                    if not card.get("guid", "").strip():
                        return False, f"{filename}: Karte {i} hat leere GUID"
                        
            except json.JSONDecodeError as e:
                return False, f"{filename}: JSON-Parsing-Fehler: {e}"
            except Exception as e:
                return False, f"{filename}: Allgemeiner Fehler: {e}"
        
        return True, f"{len(collections_in_ssot)} JSON-Dateien haben korrekte Struktur"

    def _test_collection_hierarchy(self) -> Tuple[bool, str]:
        """Test: Validates collection-category hierarchy in SSOT."""
        collections = {}
        
        for card in self.cards:
            if card.collection not in collections:
                collections[card.collection] = set()
            collections[card.collection].add(card.category)
        
        # Check collection naming convention
        for collection_name in collections.keys():
            if not re.match(r'^collection_\d+_[a-z_]+$', collection_name):
                return False, f"Ungültiger Collection-Name: {collection_name}"
        
        # Check category naming convention
        for collection_name, categories in collections.items():
            for category in categories:
                if not re.match(r'^[a-z]_[a-z0-9_]+$', category):
                    return False, f"Ungültige Kategorie in {collection_name}: {category}"
        
        total_categories = sum(len(cats) for cats in collections.values())
        return True, f"{len(collections)} Collections mit {total_categories} Kategorien in korrekter Hierarchie"

    def _test_guid_uniqueness(self) -> Tuple[bool, str]:
        """Test: Validates GUID uniqueness in SSOT."""
        guids = [card.guid for card in self.cards]
        unique_guids = set(guids)
        
        if len(guids) != len(unique_guids):
            from collections import Counter
            counts = Counter(guids)
            dupes = [guid for guid, count in counts.items() if count > 1]
            return False, f"Doppelte GUIDs gefunden: {len(dupes)} Duplikate"
        
        return True, f"{len(guids)} GUIDs sind alle eindeutig"

    def generate_fresh_template_json(self, output_dir: str):
        """
        Generates a fresh new_cards_output.json template with current category structure
        """
        template_data = {
            "instructions": "Dieses ist die Output-Datei für neue Anki-Karten. Das LLM soll hier die generierten Karten im JSON-Format ablegen.",
            "subcategories_reference": {},
            "format_example": {
                "collection_0_kernbegriffe": {
                    "a_grundlagen_metaethik": [
                        {
                            "front": "Beispiel-Frage für diese Subkategorie",
                            "back": "Beispiel-Antwort mit präziser Erklärung in 1-3 Sätzen."
                        }
                    ]
                }
            },
            "generated_cards": {},
            "instructions_for_new_categories": {
                "naming_convention": "Neue Kategorien sollten mit dem nächsten Buchstaben beginnen (z.B. 'g_', 'h_', etc.) und einen aussagekräftigen Namen haben",
                "format": "{buchstabe}_{beschreibung_mit_unterstrichen}",
                "examples": [
                    "g_moderne_entwicklungen",
                    "h_kritische_perspektiven",
                    "g_interdisziplinäre_ansätze",
                    "h_praktische_anwendungen"
                ],
                "guidelines": "Erstelle nur neue Kategorien, wenn das Material wirklich nicht in bestehende Kategorien passt. Bevorzuge die Verwendung bestehender Kategorien."
            }
        }
        
        # Build category structure from current cards
        if not self.cards:
            safe_print("⚠️ Keine Karten verfügbar für Template-Generierung.")
            return False
            
        # Group cards by collection and category
        structure = {}
        for card in self.cards:
            if card.collection not in structure:
                structure[card.collection] = set()
            structure[card.collection].add(card.category)
        
        # Generate subcategories_reference and generated_cards structure
        for collection_key in sorted(structure.keys(), key=lambda k: int(k.split('_')[1])):
            categories = sorted(list(structure[collection_key]))
            
            # For subcategories_reference - create human-readable names
            ref_dict = {}
            cards_dict = {}
            
            for category_key in categories:
                # Verwende die originalen Display-Namen aus dem Cache
                human_name = self._get_category_display_name(category_key)
                ref_dict[category_key] = human_name
                
                # Empty array for generated_cards
                cards_dict[category_key] = []
            
            template_data["subcategories_reference"][collection_key] = ref_dict
            template_data["generated_cards"][collection_key] = cards_dict
        
        # Write the template file
        template_path = os.path.join(output_dir, "new_cards_output.json")
        try:
            with open(template_path, 'w', encoding='utf-8') as f:
                json.dump(template_data, f, indent=2, ensure_ascii=False)
            safe_print(f"  -> ✅ Template '{template_path}' generiert.")
            return True
        except Exception as e:
            safe_print(f"  -> ❌ Fehler beim Generieren von '{template_path}': {e}")
            return False

    def _simulate_integrated_template(self, template_data: dict, pending_cards: List[dict]) -> dict:
        """
        Simulates what the new_cards_output.json template would look like
        BEFORE integration (i.e. with pending cards present).
        
        This is used for pre-integration integrity checking when there are pending new cards.
        The logic is: live_data (with cards) should match simulated_data (template + cards).
        
        Args:
            template_data: The fresh empty template generated from SSOT
            pending_cards: List of cards that are currently in the live file
            
        Returns:
            dict: Template data with pending cards added to simulate pre-integration state
        """
        if not pending_cards:
            return template_data
            
        # Create a deep copy to avoid modifying the original
        import copy
        simulated_data = copy.deepcopy(template_data)
        
        # Group pending cards by collection and category
        from collections import defaultdict
        pending_by_collection = defaultdict(lambda: defaultdict(list))
        
        for card in pending_cards:
            collection = card.get('collection', 'Unbekannte_Sammlung')
            category = card.get('category', 'Unbekannte_Kategorie')
            
            # Create simplified card data (only front/back like in the JSON)
            card_data = {
                'front': card.get('front', ''),
                'back': card.get('back', '')
            }
            
            # Preserve collection and category metadata if present (like in workflow_manager)
            if 'collection' in card:
                card_data['collection'] = card['collection']
            if 'category' in card:
                card_data['category'] = card['category']
            pending_by_collection[collection][category].append(card_data)
        
        # Add pending cards to the template structure
        if 'generated_cards' not in simulated_data:
            simulated_data['generated_cards'] = {}
            
        for collection, categories in pending_by_collection.items():
            # Handle collection mapping: Try to find matching collection in template
            # The pending cards might use old collection names
            matching_collection = self._find_matching_collection(collection, simulated_data['generated_cards'])
            
            if matching_collection:
                target_collection = matching_collection
            else:
                # If no match found, use the original collection name
                target_collection = collection
                if target_collection not in simulated_data['generated_cards']:
                    simulated_data['generated_cards'][target_collection] = {}
                
            for category, cards in categories.items():
                # Handle category mapping: Try to find matching category in template
                matching_category = self._find_matching_category(
                    category, 
                    simulated_data['generated_cards'].get(target_collection, {})
                )
                
                if matching_category:
                    target_category = matching_category
                else:
                    # If no match found, use the original category name
                    target_category = category
                    if target_category not in simulated_data['generated_cards'][target_collection]:
                        simulated_data['generated_cards'][target_collection][target_category] = []
                    
                # Add the pending cards to this category
                simulated_data['generated_cards'][target_collection][target_category].extend(cards)
        
        return simulated_data

    def _find_matching_collection(self, old_collection: str, template_collections: dict) -> str:
        """
        Finds a matching collection key in the template for an old collection name.
        
        This handles cases where collection names have changed between old and new structure.
        """
        # Direct match
        if old_collection in template_collections:
            return old_collection
            
        # Try to find by collection number
        try:
            old_parts = old_collection.split('_')
            if len(old_parts) >= 2:
                old_num = old_parts[1]
                for template_key in template_collections.keys():
                    template_parts = template_key.split('_')
                    if len(template_parts) >= 2 and template_parts[1] == old_num:
                        return template_key
        except (IndexError, ValueError):
            pass
            
        return None

    def _find_matching_category(self, old_category: str, template_categories: dict) -> str:
        """
        Finds a matching category key in the template for an old category name.
        
        This handles cases where category names have changed between old and new structure.
        """
        # Direct match
        if old_category in template_categories:
            return old_category
            
        # Try to find by category letter
        try:
            old_parts = old_category.split('_')
            if len(old_parts) >= 1:
                old_letter = old_parts[0]
                for template_key in template_categories.keys():
                    template_parts = template_key.split('_')
                    if len(template_parts) >= 1 and template_parts[0] == old_letter:
                        return template_key
        except (IndexError, ValueError):
            pass
            
        return None

    def _load_display_name_mappings(self):
        """
        Lädt die Display-Namen-Mappings aus der bestehenden Markdown-Datei.
        Dies ist wichtig für die Konsistenz beim Laden einer bestehenden Datenbank.
        """
        markdown_file = 'All_collections_only_fronts.md'
        if os.path.exists(markdown_file):
            try:
                structure = self._parse_markdown_structure(markdown_file)
                safe_print(f"✅ Display-Namen-Mappings aus '{markdown_file}' geladen.")
            except Exception as e:
                safe_print(f"⚠️ Warnung: Konnte Display-Namen nicht laden: {e}")

    def sync_structure_from_markdown(self, markdown_file: str) -> bool:
        """
        Synchronisiert die Struktur (Kategorien, Sortierung) aus dem Markdown,
        aber BEHÄLT alle bestehenden Karten in der SSOT bei.
        
        Dies ist die korrekte Methode für Extract nach Integration,
        da sie die vorhandenen Karten respektiert.
        
        Args:
            markdown_file: Pfad zur Markdown-Datei mit der aktuellen Struktur
            
        Returns:
            bool: True wenn erfolgreich
        """
        safe_print("🔄 Starte Struktur-Sync aus Markdown (ohne Datenverlust)...")
        
        if not os.path.exists(markdown_file):
            safe_print(f"❌ Markdown-Datei {markdown_file} nicht gefunden.")
            return False
            
        # Parse aktuelle Markdown-Struktur
        markdown_structure = self._parse_markdown_structure(markdown_file)
        if not markdown_structure:
            safe_print("❌ Keine Struktur im Markdown gefunden.")
            return False
            
        # Erstelle Mapping von normalisierten Fronts zu bestehenden Karten
        existing_cards_map = {}
        for card in self.cards:
            normalized_front = self._normalize_text(card.front)
            existing_cards_map[normalized_front] = card
            
        updated_cards = []
        missing_fronts = []
        
        # Durchlaufe alle Fronts im Markdown
        for normalized_front, structure_data in markdown_structure.items():
            if normalized_front in existing_cards_map:
                # Karte existiert -> aktualisiere nur Metadaten aus Markdown
                existing_card = existing_cards_map[normalized_front]
                
                # Aktualisiere Sortierung und Kategorisierung aus Markdown
                collection_key = structure_data.get("collection", existing_card.collection)
                category_key = structure_data.get("category", existing_card.category)
                sort_key = structure_data.get("sort_key", existing_card.sort_field)
                
                updated_card = AnkiCard(
                    guid=existing_card.guid,  # GUID bleibt gleich
                    front=existing_card.front,
                    back=existing_card.back,
                    collection=collection_key,
                    category=category_key,
                    sort_field=self._generate_sort_field(sort_key, existing_card.front),
                    tags=self._generate_tags(collection_key, category_key),
                    created_at=existing_card.created_at,
                    updated_at=datetime.now()  # Nur das Update-Datum ändern
                )
                updated_cards.append(updated_card)
            else:
                # Fehlende Karte im SSOT -> je nach Einstellung neu erstellen oder ignorieren
                if not self._handle_missing_card(normalized_front, structure_data, existing_cards_map):
                    missing_fronts.append(normalized_front)
        
        # Überprüfe ob alle fehlenden Karten behandelt wurden
        if missing_fronts:
            safe_print(f"⚠️ Einige Karten konnten nicht automatisch zugeordnet werden: {len(missing_fronts)}")
            for front in missing_fronts:
                safe_print(f"  - {front}")
        
        # Speichere die aktualisierten Karten in die Datenbank
        self.cards = updated_cards
        self.save_database()
        
        # Markdown-Datei aktualisieren
        self._update_markdown_file(".")
        
        safe_print(f"✅ Struktur-Sync abgeschlossen. {len(updated_cards)} Karten aktualisiert.")
        return True

    def _handle_missing_card(self, normalized_front: str, structure_data: Dict, existing_cards_map: Dict) -> bool:
        """
        Behandelt eine fehlende Karte im SSOT.
        
        Args:
           :
            normalized_front: Der normalisierte Front-Text der Karte
            structure_data: Die Struktur-Daten der Karte aus dem Markdown
            existing_cards_map: Das Mapping von normalisierten Fronts zu bestehenden Karten
            
        Returns:
            bool: True wenn die Karte erfolgreich behandelt wurde, sonst False
        """
        # Interaktive Aufforderung zur Behandlung der fehlenden Karte
        safe_print(f"\n⚠️ Fehlende Karte entdeckt: '{normalized_front}'")
        safe_print("Diese Karte ist im SSOT nicht vorhanden. Bitte wählen Sie eine Option:")
        
        while True:
            choice = input(
                "  [z] Zuordnen:   Karte einer bestehenden Kategorie zuordnen\n"
                "  [i] Ignorieren: Karte ignorieren (nicht hinzufügen)\n"
                "  [a] Alle ignorieren: Alle zukünftigen fehlenden Karten ignorieren\n"
                "Ihre Wahl: "
            ).lower()

            if choice == 'z':
                result = self._prompt_assign_to_category({})
                if result:
                    # Neue Karte mit zugewiesener Kategorie erstellen
                    collection_key, category_key = result
                    sort_key = f"{len(self.cards) + 1:02d}_A_01"  # Einfaches Sortier-Schema für neue Karten
                    new_card = AnkiCard(
                        guid=str(uuid.uuid4()),
                        front=normalized_front,
                        back="TODO: Antwort hinzufügen",
                        collection=collection_key,
                        category=category_key,
                        sort_field=self._generate_sort_field(sort_key, normalized_front),
                        tags=self._generate_tags(collection_key, category_key),
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                    self.cards.append(new_card)
                    self.save_database()
                    safe_print(f"✅ Karte zugeordnet und gespeichert: {normalized_front}")
                return True
            elif choice == 'i':
                safe_print(f"🗑️ Karte ignoriert: {normalized_front}")
                return True
            elif choice == 'a':
                # Setze den Cache für alle zukünftigen Anfragen auf "ignorieren"
                self._orphan_resolution_cache['__ALL__'] = None
                safe_print(f"🗑️ Alle zukünftigen fehlenden Karten werden ignoriert.")
                return True
            else:
                safe_print("Ungültige Eingabe, bitte erneut versuchen.")

    def sync_from_ssot(self) -> bool:
        """
        Synchronisiert das System OHNE die bestehende SSOT zu überschreiben.
        
        Diese Methode:
        1. Behält die bestehende card_database.json bei
        2. Regeneriert nur die abgeleiteten Dateien (collection_*.json, Markdown)
        3. Aktualisiert Templates und Prompts
        
        Verwendung: Nach Integration neuer Karten, um System zu synchronisieren
        ohne die SSOT zu zerstören.
        
        Returns:
            bool: True wenn erfolgreich, False bei Fehlern
        """
        safe_print("🔄 Starte SSOT-Sync (bestehende Datenbank wird beibehalten)...")
        
        # 1. Stelle sicher, dass die SSOT-Datenbank geladen ist
        if not self.cards:
            if os.path.exists(self.db_path):
                self.load_database()
                safe_print(f"  -> SSOT-Datenbank geladen: {len(self.cards)} Karten")
            else:
                safe_print("❌ Keine bestehende SSOT-Datenbank gefunden. Verwende --extract für Bootstrap.")
                return False
        
        # 2. Regeneriere abgeleitete Dateien aus der SSOT
        safe_print("  -> Regeneriere abgeleitete Dateien aus SSOT...")
        if not self.distribute_to_derived_files('.'):
            safe_print("❌ Fehler beim Regenerieren der abgeleiteten Dateien.")
            return False
        
        safe_print("✅ SSOT-Sync erfolgreich abgeschlossen.")
        return True

    def _reconstruct_live_data_with_metadata(self, live_data_raw: dict) -> dict:
        """
        Reconstructs the live data structure as the workflow_manager would see it,
        with collection and category metadata added to cards.
        
        This mimics the logic in workflow_manager that adds metadata to cards.
        """
        import copy
        reconstructed_data = copy.deepcopy(live_data_raw)
        
        # Add metadata to cards like workflow_manager does
        if 'generated_cards' in reconstructed_data:
            for collection, categories in reconstructed_data['generated_cards'].items():
                for category, cards in categories.items():
                    for card in cards:
                        # Add collection/category info if not present in card dict
                        if 'collection' not in card:
                            card['collection'] = collection
                        if 'category' not in card:
                            card['category'] = category
        
        return reconstructed_data
