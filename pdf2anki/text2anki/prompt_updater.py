#!/usr/bin/env python3
"""
Template-basierter Prompt-Updater

Generiert review_fronts_prompt.md aus review_fronts_prompt_template.md
mit automatischen Injektionen von Material, Fronts und Kategorien.

Ein-Weg-System: Template → Output (Template wird nie automatisch verändert)

Autor: Generated for PP_25 Ankicards
Version: 2.0 (Template-basiert)
"""

import json
import os
from pathlib import Path
import logging
import shutil
from .console_utils import safe_print

class TemplatePromptUpdater:
    def __init__(self, config_file="workflow_config.json"):
        self.config_file = config_file
        self.config = self.load_config()
        
    def load_config(self):
        """Lädt die Workflow-Konfiguration"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            safe_print(f"⚠️  Config-Datei {self.config_file} nicht gefunden. Verwende Defaults.")
            return self.get_default_config()
        except Exception as e:
            safe_print(f"❌ Fehler beim Laden der Config: {e}")
            return self.get_default_config()
    
    def get_default_config(self):
        """Standard-Konfiguration falls keine Config-Datei vorhanden"""
        return {
            "workflow_config": {
                "default_material_file": "KURSMATERIAL_PP25.md",
                "prompt_template": "review_fronts_prompt_template.md",
                "prompt_output": "review_fronts_prompt.md",
                "output_file": "new_cards_output.json",
                "fronts_collection": "All_collections_only_fronts.md",
                "auto_update_prompt": True
            },
            "placeholders": {
                "material_placeholder": "[KURSMATERIAL HIER EINFÜGEN]",
                "fronts_placeholder": "[HIER All_collections_only_fronts.md EINFÜGEN]",
                "categories_placeholder": "[KATEGORIEN WERDEN AUTOMATISCH EINGEFÜGT]",
                "json_template_placeholder": "[JSON_TEMPLATE_STRUCTURE]"
            }
        }
    
    def read_file_safe(self, filepath):
        """Liest eine Datei sicher ein"""
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                safe_print(f"⚠️  Datei {filepath} nicht gefunden")
                return None
        except Exception as e:
            safe_print(f"❌ Fehler beim Lesen von {filepath}: {e}")
            return None
    
    def load_template(self):
        """Lädt das Template"""
        template_file = self.config["workflow_config"]["prompt_template"]
        template_content = self.read_file_safe(template_file)
        
        if not template_content:
            safe_print(f"❌ Template {template_file} konnte nicht geladen werden")
            return None
            
        safe_print(f"✅ Template {template_file} geladen")
        return template_content
    
    def get_material_content(self, material_number=None):
        """Lädt Material-Inhalt oder erstellt Fallback"""
        if material_number:
            # Verwende spezifische Materialquelle
            try:
                from material_manager import MaterialManager
                manager = MaterialManager(self.config_file)
                material_content = manager.get_material_content(material_number)
                material = manager.get_material_by_number(material_number)
                
                if material_content:
                    safe_print(f"✅ Material #{material_number} '{material['name']}' geladen")
                    return material_content
                else:
                    safe_print(f"⚠️  Material #{material_number} nicht gefunden")
                    return self._get_fallback_material(f"Material #{material_number}")
            except ImportError:
                safe_print(f"⚠️  Material Manager nicht verfügbar")
                return self._get_fallback_material("Material Manager")
        else:
            # Verwende Default-Material
            material_file = self.config["workflow_config"]["default_material_file"]
            material_content = self.read_file_safe(material_file)
            
            if material_content:
                safe_print(f"✅ Default-Material aus {material_file} geladen")
                return material_content
            else:
                safe_print(f"⚠️  {material_file} nicht gefunden - verwende Fallback")
                return self._get_fallback_material(material_file)
    
    def _get_fallback_material(self, source_name):
        """Erstellt Fallback-Material"""
        return f"""[MATERIAL DATEI {source_name} NICHT GEFUNDEN]

**ANWEISUNG**: Bitte füge hier dein Kursmaterial ein:
- Vorlesungsfolien
- Texte und Literatur  
- Übungsaufgaben
- Klausur-Beispiele

Je detaillierter das Material, desto bessere Karten werden generiert!

**TIPP**: Verwende `python material_manager.py --list` um verfügbare Materialien zu sehen."""
    
    def get_fronts_content(self):
        """Lädt All_collections_only_fronts.md Inhalt"""
        fronts_file = self.config["workflow_config"]["fronts_collection"]
        fronts_content = self.read_file_safe(fronts_file)
        
        if fronts_content:
            safe_print(f"✅ Fronts aus {fronts_file} geladen")
            return fronts_content
        else:
            safe_print(f"⚠️  {fronts_file} nicht gefunden")
            return "[All_collections_only_fronts.md NICHT GEFUNDEN - FÜHRE ZUERST EXTRAKTION AUS]"
    
    def get_categories_content(self):
        """Lädt Kategorien aus prompt_categories_section.md"""
        categories_content = self.read_file_safe("prompt_categories_section.md")
        
        if categories_content:
            safe_print(f"✅ Kategorien aus prompt_categories_section.md geladen")
            return categories_content
        else:
            safe_print(f"⚠️  prompt_categories_section.md nicht gefunden")
            return """[KATEGORIEN NICHT GEFUNDEN - FÜHRE ZUERST --extract AUS]

**Anweisung**: Führe `python workflow_manager.py --extract` aus,
um die Kategorien-Struktur zu generieren."""
    
    def create_backup_if_exists(self):
        """Erstellt Backup der Output-Datei falls sie existiert"""
        output_file = self.config["workflow_config"]["prompt_output"]
        
        if os.path.exists(output_file):
            backup_file = f"{output_file}.backup"
            shutil.copy2(output_file, backup_file)
            safe_print(f"📦 Backup erstellt: {backup_file}")
    
    def generate_prompt_from_template(self, material_number=None):
        """Generiert den finalen Prompt aus dem Template"""
        # 1. Template laden
        template_content = self.load_template()
        if not template_content:
            return False
        
        # 2. Backup erstellen
        self.create_backup_if_exists()
        
        # 3. Inhalte laden
        material_content = self.get_material_content(material_number)
        fronts_content = self.get_fronts_content()
        categories_content = self.get_categories_content()
        json_template_content = self.get_json_template_content()
        
        # 4. Platzhalter ersetzen
        config = self.config["placeholders"]
        
        final_content = template_content
        final_content = final_content.replace(config["material_placeholder"], material_content)
        final_content = final_content.replace(config["fronts_placeholder"], fronts_content)
        final_content = final_content.replace(config["categories_placeholder"], categories_content)
        final_content = final_content.replace(config["json_template_placeholder"], json_template_content)
        
        # 5. Output-Datei schreiben
        output_file = self.config["workflow_config"]["prompt_output"]
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(final_content)
            safe_print(f"✅ {output_file} erfolgreich generiert")
            return True
        except Exception as e:
            safe_print(f"❌ Fehler beim Schreiben von {output_file}: {e}")
            return False
    
    def run_full_update(self, material_number=None):
        """Führt komplette Template-basierte Prompt-Generierung durch"""
        if material_number:
            safe_print(f"🔄 Starte Template-Generierung mit Material #{material_number}...")
        else:
            safe_print("🔄 Starte Template-basierte Prompt-Generierung...")
        
        success = self.generate_prompt_from_template(material_number)
        
        if success:
            safe_print("✅ Prompt erfolgreich aus Template generiert!")
            safe_print(f"📋 Template: {self.config['workflow_config']['prompt_template']}")
            safe_print(f"📄 Output: {self.config['workflow_config']['prompt_output']}")
            return True
        else:
            safe_print("❌ Prompt-Generierung fehlgeschlagen")
            return False

    def get_json_template_content(self):
        """Lädt die aktuelle JSON-Template-Struktur"""
        json_template_content = self.read_file_safe("new_cards_output.json")
        
        if json_template_content:
            safe_print(f"✅ JSON-Template aus new_cards_output.json geladen")
            
            # Formatiere das JSON schön für das Template
            try:
                import json
                json_data = json.loads(json_template_content)
                formatted_json = json.dumps(json_data, ensure_ascii=False, indent=2)
                
                # Erstelle eine ansprechende Template-Darstellung
                template_section = f"""## JSON-OUTPUT-STRUKTUR für das LLM

**WICHTIG**: Verwende EXAKT diese Struktur für deinen Output. Fülle nur die leeren Arrays in `generated_cards` mit neuen Karten.

```json
{formatted_json}
```

**Anweisungen für das LLM:**
1. **Nur `generated_cards` befüllen** - alle anderen Bereiche bleiben unverändert
2. **Exakte Schlüssel verwenden** - nutze nur die vordefinierten Collection- und Subkategorie-Schlüssel
3. **Korrekte Struktur beibehalten** - jede Karte hat genau `"front"` und `"back"`
4. **Leere Arrays nur bei neuen Karten füllen** - nicht alle Arrays müssen befüllt werden"""
                
                return template_section
                
            except json.JSONDecodeError:
                safe_print("⚠️  JSON-Template ist nicht gültig")
                return "[JSON-TEMPLATE DEFEKT - FÜHRE ZUERST --extract AUS]"
        else:
            safe_print(f"⚠️  new_cards_output.json nicht gefunden")
            return """[JSON-TEMPLATE NICHT GEFUNDEN - FÜHRE ZUERST --extract AUS]

**Anweisung**: Führe `python workflow_manager.py --extract` aus,
um die JSON-Template-Struktur zu generieren."""
    
def main():
    """Hauptfunktion"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Template-basierter Prompt Updater")
    parser.add_argument('--material', '-m', type=int, metavar='N',
                       help='Verwende Material N statt Default')
    
    args = parser.parse_args()
    
    updater = TemplatePromptUpdater()
    success = updater.run_full_update(args.material)
    
    if success:
        safe_print("\n🎯 Der Prompt ist bereit für das LLM!")
        safe_print("   📋 Kopiere review_fronts_prompt.md in dein LLM")
        safe_print("   🔧 Das Template bleibt unverändert für zukünftige Nutzung")
        if args.material:
            safe_print(f"   🎯 Verwendetes Material: #{args.material}")
    else:
        safe_print("\n❌ Prompt-Generierung fehlgeschlagen. Prüfe die Dateien.")

if __name__ == "__main__":
    main()
