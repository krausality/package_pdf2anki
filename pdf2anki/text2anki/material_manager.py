#!/usr/bin/env python3
"""
Material Manager für Anki Cards Workflow

Verwaltet verschiedene Materialdateien und ermöglicht:
- Auswahl verschiedener Materialquellen
- Setzen neuer Defaults
- CLI-basierte Navigation
- Integration in den Workflow

Autor: Generated for PP_25 Ankicards
Version: 1.0
"""

import json
import os
from pathlib import Path
from .console_utils import safe_print

class MaterialManager:
    def __init__(self, config_file="workflow_config.json"):
        self.config_file = config_file
        self.config = self.load_config()
        
    def load_config(self):
        """Lädt die Workflow-Konfiguration"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            safe_print(f"❌ Fehler beim Laden der Config: {e}")
            return None
    
    def save_config(self):
        """Speichert die Konfiguration"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            safe_print(f"❌ Fehler beim Speichern der Config: {e}")
            return False
    
    def list_materials(self):
        """Zeigt alle verfügbaren Materialdateien"""
        safe_print("\n📚 VERFÜGBARE MATERIALDATEIEN:")
        safe_print("=" * 50)
        
        materials = self.config["workflow_config"]["material_sources"]
        default_file = self.config["workflow_config"]["default_material_file"]
        
        for num, material in materials.items():
            is_default = "⭐ DEFAULT" if material["path"] == default_file else ""
            is_available = "✅" if os.path.exists(material["path"]) else "❌"
            
            safe_print(f"\n{num}. {material['name']} {is_default}")
            safe_print(f"   {is_available} {material['path']}")
            safe_print(f"   📝 {material['description']}")
        
        safe_print(f"\n🎯 Aktuell aktive Datei: {default_file}")
        return materials
    
    def get_material_by_number(self, number):
        """Gibt Materialdatei für gegebene Nummer zurück"""
        materials = self.config["workflow_config"]["material_sources"]
        return materials.get(str(number))
    
    def set_default_material(self, number):
        """Setzt neue Default-Materialdatei"""
        material = self.get_material_by_number(number)
        if not material:
            safe_print(f"❌ Material #{number} nicht gefunden")
            return False
        
        if not os.path.exists(material["path"]):
            safe_print(f"⚠️  Warnung: Datei {material['path']} existiert nicht")
            safe_print("   Möchtest du trotzdem fortfahren? (j/n)")
            if input().lower() != 'j':
                return False
        
        self.config["workflow_config"]["default_material_file"] = material["path"]
        
        if self.save_config():
            safe_print(f"✅ Default Material gesetzt: {material['name']}")
            safe_print(f"   📁 {material['path']}")
            return True
        else:
            return False
    
    def add_material_source(self, name, path, description):
        """Fügt neue Materialquelle hinzu"""
        materials = self.config["workflow_config"]["material_sources"]
        
        # Finde nächste verfügbare Nummer
        next_num = str(max(int(k) for k in materials.keys()) + 1)
        
        materials[next_num] = {
            "name": name,
            "path": path,
            "description": description
        }
        
        if self.save_config():
            safe_print(f"✅ Neue Materialquelle hinzugefügt: #{next_num} {name}")
            return next_num
        else:
            return None
    
    def remove_material_source(self, number):
        """Entfernt Materialquelle"""
        materials = self.config["workflow_config"]["material_sources"]
        
        if str(number) not in materials:
            safe_print(f"❌ Material #{number} nicht gefunden")
            return False
        
        material = materials[str(number)]
        
        # Prüfe ob es das aktuelle Default ist
        if material["path"] == self.config["workflow_config"]["default_material_file"]:
            safe_print(f"⚠️  Material #{number} ist aktuell das Default!")
            safe_print("   Setze zuerst ein anderes Default, bevor du es löschst.")
            return False
        
        del materials[str(number)]
        
        if self.save_config():
            safe_print(f"✅ Material #{number} '{material['name']}' entfernt")
            return True
        else:
            return False
    
    def interactive_selection(self):
        """Interaktive Materialauswahl"""
        while True:
            self.list_materials()
            
            safe_print("\n🎛️  OPTIONEN:")
            safe_print("1-9    Wähle Material als Default")
            safe_print("a      Neue Materialquelle hinzufügen")
            safe_print("r      Materialquelle entfernen")
            safe_print("q      Zurück")
            
            choice = input("\n➡️  Deine Wahl: ").strip().lower()
            
            if choice == 'q':
                break
            elif choice == 'a':
                self._add_material_interactive()
            elif choice == 'r':
                self._remove_material_interactive()
            elif choice.isdigit():
                self.set_default_material(int(choice))
            else:
                safe_print("❌ Ungültige Eingabe")
    
    def _add_material_interactive(self):
        """Interaktives Hinzufügen einer Materialquelle"""
        safe_print("\n➕ NEUE MATERIALQUELLE HINZUFÜGEN:")
        
        name = input("Name: ").strip()
        if not name:
            safe_print("❌ Name darf nicht leer sein")
            return
        
        path = input("Dateipfad: ").strip()
        if not path:
            safe_print("❌ Pfad darf nicht leer sein")
            return
        
        description = input("Beschreibung: ").strip()
        if not description:
            description = f"Material: {name}"
        
        self.add_material_source(name, path, description)
    

    #Temporaere fix
    def get_course_material(self) -> str | None:
        """
        Lädt den Inhalt der als Standard definierten Materialdatei.

        Dies ist die primäre Methode, um den Kontext für LLM-Aufrufe zu erhalten.
        Sie liest den Pfad aus der Konfiguration und gibt den Dateiinhalt zurück.

        Returns:
            str: Der Inhalt der Materialdatei als String.
            None: Wenn die Datei nicht gefunden oder nicht geladen werden kann.
        """
        try:
            # Lese den Pfad zur Standard-Materialdatei aus der Konfiguration
            default_material_path_str = self.config.get("workflow_config", {}).get("default_material_file")
            
            if not default_material_path_str:
                safe_print("Keine Standard-Materialdatei in der Konfiguration definiert.", "WARNING")
                return None

            default_material_path = Path(default_material_path_str)

            if default_material_path.exists():
                return default_material_path.read_text(encoding='utf-8')
            else:
                safe_print(f"Standard-Materialdatei nicht gefunden unter: {default_material_path}", "ERROR")
                return None
        except Exception as e:
            safe_print(f"Ein Fehler ist beim Laden des Kursmaterials aufgetreten: {e}", "ERROR")
            return None

    def _remove_material_interactive(self):
        """Interaktives Entfernen einer Materialquelle"""
        safe_print("\n➖ MATERIALQUELLE ENTFERNEN:")
        
        try:
            number = int(input("Nummer der zu entfernenden Quelle: ").strip())
            self.remove_material_source(number)
        except ValueError:
            safe_print("❌ Bitte gib eine gültige Nummer ein")
    
    def get_material_content(self, number=None):
        """Lädt Inhalt der angegebenen oder Default-Materialdatei"""
        if number:
            material = self.get_material_by_number(number)
            if not material:
                return None
            file_path = material["path"]
        else:
            file_path = self.config["workflow_config"]["default_material_file"]
        
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                return None
        except Exception as e:
            safe_print(f"❌ Fehler beim Lesen von {file_path}: {e}")
            return None

def main():
    """Hauptfunktion für CLI-Verwendung"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Material Manager für Anki Cards")
    parser.add_argument('--list', '-l', action='store_true', 
                       help='Zeige alle verfügbaren Materialien')
    parser.add_argument('--set-default', '-s', type=int, metavar='N',
                       help='Setze Material N als Default')
    parser.add_argument('--add', '-a', nargs=3, metavar=('NAME', 'PATH', 'DESC'),
                       help='Füge neue Materialquelle hinzu')
    parser.add_argument('--remove', '-r', type=int, metavar='N',
                       help='Entferne Material N')
    parser.add_argument('--interactive', '-i', action='store_true',
                       help='Interaktiver Modus')
    
    args = parser.parse_args()
    
    manager = MaterialManager()
    
    if args.list:
        manager.list_materials()
    elif args.set_default:
        manager.set_default_material(args.set_default)
    elif args.add:
        name, path, desc = args.add
        manager.add_material_source(name, path, desc)
    elif args.remove:
        manager.remove_material_source(args.remove)
    elif args.interactive:
        manager.interactive_selection()
    else:
        # Default: Liste anzeigen
        manager.list_materials()
        safe_print("\n💡 Verwende --help für alle Optionen")

if __name__ == "__main__":
    main()
