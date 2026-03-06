#!/usr/bin/env python3
"""
Workflow Manager for Anki Cards System (v4.1 - SSOT)

This script orchestrates the complete, robust workflow based on a Single Source of Truth.

Verwendung:
    python workflow_manager.py --extract   # (Re-)Initializes the SSOT from legacy source files.
    python workflow_manager.py --integrate # Integrates new cards from LLM output into the SSOT.
"""

import argparse
import sys
import os
import json
from datetime import datetime
from pathlib import Path

# Import the new core components
from .database_manager import DatabaseManager
from .prompt_updater import TemplatePromptUpdater
from .console_utils import safe_print
from .project_config import ProjectConfig

class WorkflowManager:
    """
    Orchestrates the SSOT-based workflows (--extract, --integrate, --ingest, --export).
    """
    def __init__(self, project_dir: str = '.'):
        self._project_dir = str(Path(project_dir).resolve())
        self._config = ProjectConfig.from_file(self._project_dir)

        self.db_manager = DatabaseManager(
            db_path=self._config.get_db_path(),
            project_config=self._config,
        )
        self.legacy_collection_files = self._config.get_legacy_collection_files()
        self.legacy_markdown_file = self._config.get_markdown_path()
        self.new_cards_file = self._config.get_new_cards_path()

    def run_export_workflow(self) -> bool:
        """Exportiert den aktuellen SSOT als .apkg Dateien."""
        safe_print("\n=== 📦 Starting '--export' Workflow ===")
        from .apkg_exporter import export_to_apkg
        generated = export_to_apkg(self.db_manager, self._config, self._project_dir)
        safe_print(f"\n=== ✨ '--export' abgeschlossen: {len(generated)} .apkg Datei(en) ===")
        return True

    def run_ingest_workflow(self, input_files: list) -> bool:
        """Liest Textdateien und generiert new_cards_output.json via LLM."""
        safe_print(f"\n=== 📥 Starting '--ingest' Workflow ({len(input_files)} Datei(en)) ===")
        from .text_ingester import ingest_text
        result = ingest_text(input_files, self._config, self.new_cards_file)
        safe_print("\n=== ✨ '--ingest' abgeschlossen ===")
        return result

    def run_init_workflow(self, project_name: str) -> bool:
        """Erstellt project.json Template im aktuellen Projektverzeichnis."""
        safe_print(f"\n=== 🏗️  Initialisiere Projekt '{project_name}' ===")
        ProjectConfig.create_template(self._project_dir, project_name)
        safe_print("   Nächster Schritt: project.json editieren, dann --ingest oder --extract")
        return True

    def run_extract_workflow(self, force=False, auto_rescue_orphans=False,
                           auto_skip_conflicts=False, auto_create_missing=False,
                           auto_ignore_orphans=False, skip_tests=False, llm_resolve_conflicts=False,
                           llm_categorize_orphans=False, llm_complete_backs=False,
                           skip_export=False):
        """
        Executes the bootstrap workflow to create/recreate the SSOT.
        1. Bootstrap (SSOT erstellen)
        2. Distribute (Abgeleitete Dateien erstellen)
        3. Verify (Integrität prüfen)
        4. Post-Extract Tests (optional)
        5. Update Prompt
        
        Args:
            force: Skip user confirmation
            auto_rescue_orphans: Automatically rescue all orphaned cards
            auto_skip_conflicts: Automatically skip back conflicts (use first back)
            auto_create_missing: Automatically create missing cards with "TODO" back
            auto_ignore_orphans: Automatically ignore all orphaned cards
        """
        safe_print("\n=== 🚀 Starting '--extract' Workflow ===")
        
        # User confirmation to prevent accidental overwrites
        if os.path.exists(self.db_manager.db_path) and not force:
            safe_print(f"⚠️  WARNING: The database '{self.db_manager.db_path}' already exists.")
            response = input("This will rebuild it from potentially older legacy files. Continue? (y/n): ")
            if response.lower() != 'y':
                safe_print("Aborted by user.")
                return False

        # 1. Bootstrap
        safe_print("  -> Step 1: Bootstrapping from legacy files...")
        success_bootstrap = self.db_manager.bootstrap_from_legacy(
            self.legacy_collection_files, 
            self.legacy_markdown_file,
            auto_rescue_orphans=auto_rescue_orphans,
            auto_skip_conflicts=auto_skip_conflicts,
            auto_create_missing=auto_create_missing,
            auto_ignore_orphans=auto_ignore_orphans,
            llm_resolve_conflicts=llm_resolve_conflicts,
            llm_categorize_orphans=llm_categorize_orphans,
            llm_complete_backs=llm_complete_backs
        )
        if not success_bootstrap:
            safe_print("❌ ERROR: Bootstrap failed. Aborting.")
            return False
        safe_print("  ✅ OK: SSOT (card_database.json) was successfully created.")

        # 2. Distribute
        safe_print("  -> Step 2: Distributing from SSOT to derived files...")
        success_distribute = self.db_manager.distribute_to_derived_files('.') # Output to current dir
        if not success_distribute:
            safe_print("❌ ERROR: Distribution failed. Aborting.")
            return False
        safe_print("  ✅ OK: Derived files were successfully generated from the SSOT.")

        # 3. Verify
        safe_print("  -> Step 3: Verifying integrity...")
        is_ok, message = self.db_manager.verify_integrity('.')
        if not is_ok:
            safe_print(f"❌ CRITICAL ERROR: System is inconsistent after bootstrap. This indicates a bug. Details: {message}")
            return False
        safe_print("  ✅ OK: System is consistent after '--extract' workflow.")
        
        # 4. Post-Extract Validation Tests
        if not skip_tests:
            safe_print("  -> Step 4: Running post-extract validation tests...")
            tests_passed, test_results = self.db_manager.run_post_extract_tests('.')
            if not tests_passed:
                safe_print("❌ WARNING: Some validation tests failed:")
                for result in test_results:
                    if "❌ FAIL" in result:
                        safe_print(f"    {result}")
                safe_print("  ⚠️  System may have issues, but bootstrap completed.")
            else:
                safe_print("  ✅ OK: All validation tests passed.")
        else:
            safe_print("  -> Step 4: Skipping validation tests (--skip-tests enabled)")
        
        # 5. Update Prompt
        safe_print("  -> Step 5: Updating LLM prompt...")
        try:
            prompt_updater = TemplatePromptUpdater()
            prompt_updater.run_full_update()
            safe_print("  ✅ OK: Prompt updated successfully.")
        except Exception as e:
            safe_print(f"  ⚠️  WARN: Could not update prompt: {e}")

        # 6. Export to .apkg
        if not skip_export:
            safe_print("  -> Step 6: Exporting to .apkg...")
            from .apkg_exporter import export_to_apkg
            generated = export_to_apkg(self.db_manager, self._config, self._project_dir)
            safe_print(f"  ✅ OK: {len(generated)} .apkg Datei(en) exportiert.")
        else:
            safe_print("  -> Step 6: .apkg-Export übersprungen (--skip-export).")

        safe_print("\n=== ✨ '--extract' Workflow Completed Successfully ===")
        return True

    def run_integrate_workflow(self, skip_gate=False, skip_export=False):
        """
        Executes the integration workflow for new cards.
        1. (GATE) Verify Integrity with pending cards awareness
        2. Integrate new cards
        3. Distribute
        4. (GATE) Verify Integrity
        5. Archive new cards file
        """
        safe_print("\n=== 🚀 Starting '--integrate' Workflow ===")

        # Projektverzeichnis aus db_path ableiten (Bug 5: nicht CWD verwenden)
        _project_output_dir = os.path.dirname(os.path.abspath(self.db_manager.db_path))

        # Load pending cards early for the integrity check
        pending_cards = []
        if os.path.exists(self.new_cards_file):
            try:
                with open(self.new_cards_file, 'r', encoding='utf-8') as f:
                    new_cards_data = json.load(f)
                    
                # Parse the structure of new_cards_output.json
                if isinstance(new_cards_data, list): # Simple list of cards
                     pending_cards = new_cards_data
                elif isinstance(new_cards_data, dict) and 'new_cards' in new_cards_data: # Output from ingest_text()
                    pending_cards = new_cards_data['new_cards']
                elif isinstance(new_cards_data, dict) and 'generated_cards' in new_cards_data: # Legacy nested structure
                    for collection, categories in new_cards_data['generated_cards'].items():
                        for category, cards in categories.items():
                            for card in cards:
                                # Add collection/category info if not present in card dict
                                if 'collection' not in card: card['collection'] = collection
                                if 'category' not in card: card['category'] = category
                                pending_cards.append(card)
            except (json.JSONDecodeError, FileNotFoundError) as e:
                safe_print(f"⚠️ WARNING: Could not parse '{self.new_cards_file}': {e}")
                # Continue without pending cards information

        # 1. GATE: Verify Integrity (pending-cards-aware)
        if not skip_gate:
            safe_print("  -> Step 1 (GATE): Verifying pre-integration integrity...")
            safe_print(f"    (Accounting for {len(pending_cards)} pending card(s) from '{self.new_cards_file}')")
            is_ok, message = self.db_manager.verify_integrity(_project_output_dir, pending_new_cards=pending_cards)
            if not is_ok:
                safe_print("❌ ERROR: System is in an inconsistent state.")
                safe_print("Please run 'python workflow_manager.py --extract' to repair and resynchronize the system.")
                safe_print(f"Details: {message}")
                safe_print("  ⚠️ HINT: Use '--skip-gate' to bypass this check if you're sure the system is consistent.")
                return False
            safe_print("  ✅ OK: Pre-integration integrity check passed (accounting for pending cards).")
        else:
            safe_print("  -> Step 1 (GATE): SKIPPED (--skip-gate enabled)")

        # 2. Integrate
        safe_print("  -> Step 2: Integrating new cards...")
        if not os.path.exists(self.new_cards_file):
            safe_print(f"ℹ️ No new cards file found at '{self.new_cards_file}'. Nothing to integrate.")
            return True # Not an error, just nothing to do.
        
        if not pending_cards:
            safe_print("  -> No new cards to integrate found in the file.")
            return True

        cards_added = self.db_manager.integrate_new(pending_cards)
        safe_print(f"  ✅ OK: Integration complete. Added {cards_added} new card(s).")

        # 2.5. Archive the processed new_cards_output.json BEFORE distribution
        processed_filename = f"{self.new_cards_file}.processed_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            os.rename(self.new_cards_file, processed_filename)
            safe_print(f"  -> Archived processed file to '{processed_filename}'")
        except OSError as e:
            safe_print(f"  ⚠️ WARN: Could not archive processed file: {e}")

        # 3. Distribute
        safe_print("  -> Step 3: Distributing changes to derived files...")
        self.db_manager.distribute_to_derived_files(_project_output_dir)
        safe_print("  ✅ OK: Derived files were updated.")

        # 4. GATE: Verify
        safe_print("  -> Step 4 (GATE): Verifying post-integration integrity...")
        is_ok, message = self.db_manager.verify_integrity(_project_output_dir)
        if not is_ok:
            safe_print(f"❌ CRITICAL ERROR: System is inconsistent after integration. This indicates a bug. Details: {message}")
            return False
        safe_print("  ✅ OK: Post-integration integrity check passed.")


        # 5. Export to .apkg
        if not skip_export:
            safe_print("  -> Step 5: Exporting to .apkg...")
            from .apkg_exporter import export_to_apkg
            generated = export_to_apkg(self.db_manager, self._config, self._project_dir)
            safe_print(f"  ✅ OK: {len(generated)} .apkg Datei(en) exportiert.")
        else:
            safe_print("  -> Step 5: .apkg-Export übersprungen (--skip-export).")

        safe_print("\n=== ✨ '--integrate' Workflow Completed Successfully ===")
        return True

    def run_sync_workflow(self):
        """
        Executes the sync workflow to regenerate templates without touching SSOT.
        
        Diese Methode ist SICHER nach einer Integration, da sie:
        1. Die bestehende card_database.json NICHT überschreibt
        2. Nur die abgeleiteten Dateien (collection_*.json, Markdown) regeneriert  
        3. Templates und Prompts aktualisiert
        
        Verwendung: Nach --integrate, um System zu synchronisieren.
        """
        safe_print("\n=== 🔄 Starting '--sync' Workflow ===")
        
        # 1. Sync from SSOT
        safe_print("  -> Step 1: Syncing from existing SSOT...")
        success_sync = self.db_manager.sync_from_ssot()
        if not success_sync:
            safe_print("❌ ERROR: Sync failed. Aborting.")
            return False
        safe_print("  ✅ OK: System synced from existing SSOT.")

        # 2. Verify integrity
        safe_print("  -> Step 2: Verifying integrity...")
        is_ok, message = self.db_manager.verify_integrity('.')
        if not is_ok:
            safe_print(f"❌ CRITICAL ERROR: System is inconsistent after sync. This indicates a bug. Details: {message}")
            return False
        safe_print("  ✅ OK: System is consistent after '--sync' workflow.")
        
        # 3. Update Prompt
        safe_print("  -> Step 3: Updating LLM prompt...")
        try:
            prompt_updater = TemplatePromptUpdater()
            prompt_updater.run_full_update()
            safe_print("  ✅ OK: Prompt updated successfully.")
        except Exception as e:
            safe_print(f"  ⚠️  WARN: Could not update prompt: {e}")

        safe_print("\n=== ✨ '--sync' Workflow Completed Successfully ===")
        return True

    def run_smart_extract_workflow(self, force=False, auto_rescue_orphans=False,
                                  auto_skip_conflicts=False, auto_create_missing=False,
                                  auto_ignore_orphans=False, skip_tests=False, llm_resolve_conflicts=False,
                                  llm_categorize_orphans=False, llm_complete_backs=False,
                                  skip_export=False):
        """
        Intelligenter Extract-Workflow:
        - Wenn keine card_database.json existiert → Bootstrap (Genesis)
        - Wenn card_database.json existiert → Sync (SSOT-preserving)
        
        Das macht das System benutzerfreundlicher und verhindert versehentlichen Datenverlust.
        """
        safe_print("\n=== 🧠 Starting 'Smart Extract' Workflow ===")
        
        # Entscheide basierend auf Zustand der SSOT-Datenbank
        if os.path.exists(self.db_manager.db_path):
            file_size = os.path.getsize(self.db_manager.db_path)
            if file_size > 50:  # Nicht nur leer/minimal
                safe_print(f"✅ Bestehende SSOT-Datenbank gefunden ({file_size} bytes)")
                safe_print("🔄 Führe SICHEREN Sync durch (SSOT wird beibehalten)...")
                return self.run_sync_workflow()
            else:
                safe_print(f"⚠️ SSOT-Datenbank existiert, ist aber leer/minimal ({file_size} bytes)")
                if not force:
                    response = input("Soll Bootstrap (Genesis) durchgeführt werden? (y/n): ")
                    if response.lower() != 'y':
                        safe_print("Abgebrochen.")
                        return False
        else:
            safe_print("📂 Keine SSOT-Datenbank gefunden")
            safe_print("🚀 Führe Bootstrap (Genesis) durch...")
        
        # Führe Bootstrap durch
        return self.run_extract_workflow(
            force=force,
            auto_rescue_orphans=auto_rescue_orphans,
            auto_skip_conflicts=auto_skip_conflicts,
            auto_create_missing=auto_create_missing,
            auto_ignore_orphans=auto_ignore_orphans,
            skip_tests=skip_tests,
            llm_resolve_conflicts=llm_resolve_conflicts,
            llm_categorize_orphans=llm_categorize_orphans,
            llm_complete_backs=llm_complete_backs,
            skip_export=skip_export,
        )

def main():
    """
    Main entry point for the script. Parses arguments and runs the selected workflow.
    """
    parser = argparse.ArgumentParser(
        description="text2anki Workflow Manager (v5.1 - ProjectConfig)",
        formatter_class=argparse.RawTextHelpFormatter
    )

    # Project directory
    parser.add_argument("--project", default=".", metavar="VERZ",
                        help="Projektverzeichnis mit project.json (default: aktuelles Verzeichnis)")

    # Define mutually exclusive group for commands
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--extract", action="store_true",
                       help="🧠 Smart Extract: Auto-Bootstrap (if no SSOT) or Auto-Sync (if SSOT exists)")
    group.add_argument("--integrate", action="store_true",
                       help="Integriert neue Karten aus new_cards_output.json in den SSOT.")
    group.add_argument("--sync", action="store_true",
                       help="🔄 Manual Sync: Force sync templates from existing SSOT")
    group.add_argument("--bootstrap", action="store_true",
                       help="🚀 Force Bootstrap: Always recreate SSOT from legacy files")
    group.add_argument("--export", action="store_true",
                       help="📦 Exportiert aktuellen SSOT als .apkg Dateien.")
    group.add_argument("--ingest", nargs="+", metavar="FILE",
                       help="📥 Liest .txt Datei(en) und generiert Karten via LLM → new_cards_output.json")
    group.add_argument("--init", metavar="NAME",
                       help="🏗️  Initialisiert neues Projekt mit project.json Template.")

    # Options
    parser.add_argument("--force", action="store_true",
                        help="Force overwrite without prompt during --extract.")
    parser.add_argument("--skip-gate", action="store_true",
                        help="Skip pre-integration integrity check during --integrate.")
    parser.add_argument("--skip-export", action="store_true",
                        help="Deaktiviert automatischen .apkg-Export nach --extract/--integrate.")
    parser.add_argument("--auto-rescue-orphans", action="store_true",
                        help="Automatically rescue all orphaned cards.")
    parser.add_argument("--auto-skip-conflicts", action="store_true",
                        help="Automatically skip back conflicts (use first back).")
    parser.add_argument("--auto-create-missing", action="store_true",
                        help="Automatically create missing cards with 'TODO' back.")
    parser.add_argument("--auto-ignore-orphans", action="store_true",
                        help="Automatically ignore all orphaned cards.")
    parser.add_argument("--auto-all", action="store_true",
                        help="Enable all auto options (rescue orphans + skip conflicts + create missing).")
    parser.add_argument("--skip-tests", action="store_true",
                        help="Skip post-extract validation tests (faster execution).")

    # LLM Assistance Arguments
    parser.add_argument("--llm-all", action="store_true",
                        help="🚀 Aktiviert alle LLM-Features gleichzeitig (God Mode).")
    parser.add_argument("--llm-assist", action="store_true",
                        help="Alias für --llm-all (deprecated, use --llm-all).")
    parser.add_argument("--llm-resolve-conflicts", action="store_true",
                        help="Use LLM to resolve back conflicts.")
    parser.add_argument("--llm-complete-backs", action="store_true",
                        help="Use LLM to complete missing backs.")
    parser.add_argument("--llm-categorize-orphans", action="store_true",
                        help="Use LLM to categorize orphaned cards.")
    args = parser.parse_args()

    # Handle --auto-all shortcut
    if args.auto_all:
        args.auto_rescue_orphans = True
        args.auto_skip_conflicts = True
        args.auto_create_missing = True

    # Handle --llm-all / --llm-assist shortcut
    if args.llm_all or args.llm_assist:
        args.llm_resolve_conflicts = True
        args.llm_complete_backs = True
        args.llm_categorize_orphans = True

    # --init doesn't require a project.json yet — handle separately
    if args.init:
        from pathlib import Path
        project_dir = str(Path(args.project).resolve())
        ProjectConfig.create_template(project_dir, args.init)
        safe_print("   Nächster Schritt: project.json editieren, dann --ingest oder --extract")
        return

    manager = WorkflowManager(project_dir=args.project)

    success = False

    if args.extract:
        success = manager.run_smart_extract_workflow(
            force=args.force,
            auto_rescue_orphans=args.auto_rescue_orphans,
            auto_skip_conflicts=args.auto_skip_conflicts,
            auto_create_missing=args.auto_create_missing,
            auto_ignore_orphans=args.auto_ignore_orphans,
            skip_tests=args.skip_tests,
            llm_resolve_conflicts=args.llm_resolve_conflicts,
            llm_categorize_orphans=args.llm_categorize_orphans,
            llm_complete_backs=args.llm_complete_backs,
            skip_export=args.skip_export,
        )
    elif args.bootstrap:
        success = manager.run_extract_workflow(
            force=args.force,
            auto_rescue_orphans=args.auto_rescue_orphans,
            auto_skip_conflicts=args.auto_skip_conflicts,
            auto_create_missing=args.auto_create_missing,
            auto_ignore_orphans=args.auto_ignore_orphans,
            skip_tests=args.skip_tests,
            llm_resolve_conflicts=args.llm_resolve_conflicts,
            llm_categorize_orphans=args.llm_categorize_orphans,
            llm_complete_backs=args.llm_complete_backs,
            skip_export=args.skip_export,
        )
    elif args.integrate:
        success = manager.run_integrate_workflow(
            skip_gate=args.skip_gate,
            skip_export=args.skip_export,
        )
    elif args.sync:
        success = manager.run_sync_workflow()
    elif args.export:
        success = manager.run_export_workflow()
    elif args.ingest:
        success = manager.run_ingest_workflow(args.ingest)
    else:
        safe_print("No valid command specified. Use --help for options.")
        sys.exit(1)

    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()


"""

#Verkuerzung moeglich aber vllcht nicht gewollt?

    # Kapsle die gemeinsamen Argumente, um Code-Wiederholung zu vermeiden
    workflow_args = {
        "force": args.force,
        "auto_rescue_orphans": args.auto_rescue_orphans,
        "auto_skip_conflicts": args.auto_skip_conflicts,
        "auto_create_missing": args.auto_create_missing,
        "auto_ignore_orphans": args.auto_ignore_orphans,
        "skip_tests": args.skip_tests,
        "llm_resolve_conflicts": args.llm_resolve_conflicts,
        "llm_categorize_orphans": args.llm_categorize_orphans,
        "llm_complete_backs": args.llm_complete_backs
    }

    if args.extract:
        success = manager.run_smart_extract_workflow(**workflow_args)
    elif args.bootstrap:
        success = manager.run_extract_workflow(**workflow_args)
    elif args.integrate:
        success = manager.run_integrate_workflow(skip_gate=args.skip_gate)
    elif args.sync:
        success = manager.run_sync_workflow()
    else:
        # Dieser Fall sollte durch 'required=True' im Parser nicht eintreten, ist aber guter Stil.
        safe_print("Kein gültiger Befehl angegeben. Verwenden Sie --help für Optionen.", "ERROR")
        sys.exit(1)
        
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()

"""
