"""
llm_discovery.py — Multi-turn LLM Discovery Loop for project.json hypothesis generation.

The LLM is given tools to inspect the directory (list files, read PDF pages,
read TXT excerpts) and must produce a valid project.json dict plus a pipeline plan.

Tool protocol (structured JSON, model-agnostic):
  Request:  {"tool_call": {"name": "<tool>", "args": {...}}}
  Final:    {"final": {"project_json": {...}, "skip_confirm": <bool>,
                       "pipeline_plan": [{"step": "...", "file": "...", "status": "..."}, ...]}}

Returns None if max_turns exhausted without a valid final answer
(caller should fall back to guided_wizard).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import NamedTuple, Optional

from .llm_helper import get_llm_conversation_turn
from .pipeline_state import scan_directory, infer_ocr_status
from .project_config import PROJECT_JSON_TEMPLATE

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

class DiscoveryResult(NamedTuple):
    project_json: dict
    skip_confirm: bool
    pipeline_plan: list


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a project configuration assistant for pdf2anki — a tool that converts PDF
lecture materials into Anki flashcard decks.

Your task: inspect the user's directory and produce a complete, valid project.json.

You will receive the directory tree AND content samples (first lines of representative
files from each subdirectory) upfront. Use both structure and content to infer topics.

=== TOOLS ===
Call exactly ONE tool per response by outputting a single JSON object:

  {"tool_call": {"name": "list_directory", "args": {}}}
  {"tool_call": {"name": "read_pdf_pages", "args": {"filename": "relative/path.pdf", "pages": "1-3"}}}
  {"tool_call": {"name": "read_txt_excerpt", "args": {"filename": "relative/path.txt", "lines": 50}}}
  {"tool_call": {"name": "read_excerpts", "args": {"filenames": ["a.txt", "b.txt"], "lines": 40}}}

- read_excerpts reads multiple files in one call (saves turns)
- pages can be "1", "1-3", or "1,3,5"
- lines is the number of lines to read from the start of each file

=== COLLECTION STRATEGY ===
Collections MUST represent thematic learning topics derived from the CONTENT of the files —
never from directory names, file paths, or folder structure.

Students study by topic, not by file origin. Material about the same topic from different
sources (lecture script chapter 3, exercise sheet 3, tutorial notes week 3) belongs in ONE
collection for that topic.

How to discover topics:
1. Look at the content samples provided with the directory listing
2. Identify the main document (longest file, usually a lecture script or textbook)
3. Find chapter headings, section titles, or a table of contents in that document
4. Use those chapter/section topics as your collection names
5. If you need more detail, use read_excerpts to read additional files

WRONG — collections mirror directory structure:
  "Lectures": ...           ← folder name, not a topic
  "Exercises_Homework": ... ← folder name
  "Exercises_Worksheets": ...

RIGHT — collections represent learning topics found in the content:
  "collection_0_Topic_A": {"display_name": "First major topic from the content", ...}
  "collection_1_Topic_B": {"display_name": "Second major topic from the content", ...}
  "collection_2_Topic_C": {"display_name": "Third major topic from the content", ...}

=== FINAL OUTPUT ===
When you have enough information (or on your LAST turn), output ONLY this JSON — no other text:

{
  "final": {
    "project_json": {
      "project_name": "<short identifier, e.g. GTI_WiSe2526>",
      "tag_prefix": "<UPPERCASE_TAG>",
      "language": "de",
      "domain": "<subject area description>",
      "orphan_collection_name": "Unsortierte_Karten",
      "files": {
        "db_path": "card_database.json",
        "markdown_file": "All_fronts.md",
        "new_cards_file": "new_cards_output.json",
        "material_file": "course_material.txt"
      },
      "collections": {
        "collection_0_TopicName": {
          "display_name": "Full readable name",
          "filename": "collection_0_TopicName.json",
          "description": "What this section covers"
        }
      },
      "llm": {"model": "google/gemini-2.5-flash", "temperature": 0.1}
    },
    "skip_confirm": false,
    "pipeline_plan": [
      {"step": "ocr",    "file": "relative/path.pdf", "status": "pending"},
      {"step": "ingest", "file": "all",                "status": "pending"},
      {"step": "export", "file": "all",                "status": "pending"}
    ]
  }
}

=== RULES ===
- collection keys must match their filename without .json suffix
- filename must end in .json
- Set skip_confirm=true only when naming is unambiguous and you are highly confident
- pipeline_plan must list every PDF found, with accurate status from the directory listing
- Output ONLY valid JSON — no markdown fences, no explanation text
"""


# ---------------------------------------------------------------------------
# Discovery loop
# ---------------------------------------------------------------------------

class LLMDiscoveryLoop:
    def __init__(
        self,
        base_dir: Path,
        max_turns: int = 7,
        model: str = "google/gemini-2.5-flash",
    ) -> None:
        self.base_dir = base_dir.resolve()
        self.max_turns = max_turns
        self.model = model
        self._pipeline_state = scan_directory(self.base_dir)
        # Counters exposed for pipeline trace
        self.turns_used: int = 0
        self.tool_calls_made: list[str] = []

    def run(self) -> Optional[DiscoveryResult]:
        """
        Run the discovery loop. Returns DiscoveryResult or None if it fails
        (e.g. max_turns exhausted without a valid final answer).
        """
        history: list = [{"role": "system", "content": _SYSTEM_PROMPT}]

        # First user message: directory listing + proactive content samples
        content_samples = self._sample_content_for_discovery()
        first_message = (
            "Here is the directory I need a project.json for:\n\n"
            + self._tool_list_directory()
        )
        if content_samples:
            first_message += (
                "\n\n--- CONTENT SAMPLES (one representative file per subdirectory) ---\n\n"
                + content_samples
            )
        first_message += (
            "\n\nUse the content samples above to identify thematic topics for collections. "
            "If you need more detail, call read_excerpts with additional files. "
            "Then produce the final project.json."
        )

        for turn_idx in range(self.max_turns):
            is_last_turn = (turn_idx == self.max_turns - 1)

            user_message = first_message if turn_idx == 0 else None

            if is_last_turn and user_message is None:
                user_message = (
                    "This is your LAST turn. Output your final answer now as JSON "
                    "with the 'final' key. No more tool calls."
                )
            elif is_last_turn:
                user_message += (
                    "\n\nNote: This is also your LAST turn. "
                    "Output the final JSON directly if you have enough information."
                )

            if user_message is not None:
                reply = get_llm_conversation_turn(history, user_message, model=self.model)
            else:
                # Continue: the last assistant message already asked for more info;
                # we provide a minimal continuation prompt
                reply = get_llm_conversation_turn(
                    history,
                    "Tool result attached above. Continue.",
                    model=self.model,
                )

            self.turns_used += 1

            if reply is None:
                return None  # API failure

            kind, data = self._parse_response(reply)

            if kind == "final":
                return self._build_result(data)

            if kind == "tool_call":
                tool_name = data.get("name", "")
                self.tool_calls_made.append(tool_name)
                args = data.get("args", {})
                tool_result = self._dispatch(tool_name, args)
                # Inject tool result as next user message
                get_llm_conversation_turn(
                    history,
                    f"Tool '{tool_name}' result:\n\n{tool_result}",
                    model=self.model,
                )
                # The loop will now continue; decrement remaining turns by 1
                # (the tool-result injection consumed a turn slot implicitly)
                # We do NOT decrement here — the outer for loop handles it.
                # But we need to be aware that injecting adds 2 messages.
                continue

            # Unparseable response — treat as last-chance fallback on next iteration
            # (already consumed a turn, loop continues)

        return None  # max_turns exhausted

    # -----------------------------------------------------------------------
    # Tools
    # -----------------------------------------------------------------------

    def _tool_list_directory(self) -> str:
        """Return an annotated tree of the base directory."""
        lines = [f"Directory: {self.base_dir}", ""]
        self._walk_tree(self.base_dir, lines, prefix="")
        # Append pipeline state summary
        if self._pipeline_state:
            lines.append("")
            lines.append("Pipeline state per PDF:")
            for rel_path, state in sorted(self._pipeline_state.items()):
                lines.append(
                    f"  {rel_path}: ocr={state.ocr}, "
                    f"ingest={state.ingest}, export={state.export}"
                )
        return "\n".join(lines)

    def _walk_tree(self, directory: Path, lines: list, prefix: str) -> None:
        _IGNORED = {"pdf2pic", "log_archive", "__pycache__", ".venv"}
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return

        dirs = [e for e in entries if e.is_dir() and e.name not in _IGNORED]
        files = [e for e in entries if e.is_file()]

        all_items = dirs + files
        for idx, item in enumerate(all_items):
            connector = "└── " if idx == len(all_items) - 1 else "├── "
            if item.is_dir():
                lines.append(f"{prefix}{connector}{item.name}/")
                extension = "    " if idx == len(all_items) - 1 else "│   "
                self._walk_tree(item, lines, prefix + extension)
            else:
                annotation = self._file_annotation(item)
                lines.append(f"{prefix}{connector}{item.name}{annotation}")

    def _file_annotation(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            txt = path.with_suffix(".txt")
            ocr = infer_ocr_status(txt)
            return f"  [OCR: {ocr}]"
        if suffix == ".txt":
            state_path = path.with_name(f"{path.name}.ocr_state.json")
            if state_path.exists():
                return "  [OCR output — in progress]"
            if path.exists():
                return "  [OCR output — done]"
        if suffix == ".json" and path.name == "project.json":
            return "  [EXISTS — project config]"
        return ""

    def _tool_read_pdf_pages(self, filename: str, pages: str = "1-3") -> str:
        """Extract text from specified pages of a PDF using pymupdf."""
        try:
            import fitz  # pymupdf
        except ImportError:
            return "[ERROR: pymupdf not installed — cannot read PDF pages]"

        pdf_path = self.base_dir / filename
        if not pdf_path.exists():
            return f"[ERROR: File not found: {filename}]"
        if pdf_path.suffix.lower() != ".pdf":
            return f"[ERROR: Not a PDF file: {filename}]"

        page_indices = self._parse_page_spec(pages)
        if not page_indices:
            return f"[ERROR: Could not parse page spec '{pages}']"

        try:
            doc = fitz.open(str(pdf_path))
            total = len(doc)
            results = []
            for idx in page_indices:
                if idx < 0 or idx >= total:
                    results.append(f"[Page {idx + 1}: out of range (total={total})]")
                    continue
                page = doc[idx]
                text = page.get_text().strip()
                results.append(f"--- Page {idx + 1} ---\n{text if text else '[No text layer — scanned image?]'}")
            doc.close()
            return "\n\n".join(results)
        except Exception as exc:
            return f"[ERROR reading {filename}: {exc}]"

    def _tool_read_txt_excerpt(self, filename: str, lines: int = 50) -> str:
        """Read the first N lines of a TXT file."""
        txt_path = self.base_dir / filename
        if not txt_path.exists():
            return f"[ERROR: File not found: {filename}]"
        try:
            content = txt_path.read_text(encoding="utf-8", errors="replace")
            all_lines = content.splitlines()
            excerpt = "\n".join(all_lines[:lines])
            truncated = len(all_lines) > lines
            suffix = f"\n... [{len(all_lines) - lines} more lines]" if truncated else ""
            return excerpt + suffix
        except OSError as exc:
            return f"[ERROR reading {filename}: {exc}]"

    def _tool_read_excerpts(self, filenames: list, lines: int = 40) -> str:
        """Read the first N lines of multiple TXT files in one call."""
        results = []
        for filename in filenames:
            header = f"=== {filename} ==="
            body = self._tool_read_txt_excerpt(str(filename), lines)
            results.append(f"{header}\n{body}")
        return "\n\n".join(results)

    def _sample_content_for_discovery(self) -> str:
        """Proactively sample content from representative files in each subdirectory.

        Heuristic: for each directory containing .txt files, pick the largest one
        (most content = most representative) and read its first lines. Also always
        sample the overall largest .txt (likely the main document / lecture script).
        """
        _IGNORED = {"pdf2pic", "log_archive", "__pycache__", ".venv", ".claude"}
        _SAMPLE_LINES = 40

        # Collect all .txt files grouped by parent directory
        dir_txts: dict[Path, list[Path]] = {}
        for txt in self.base_dir.rglob("*.txt"):
            # Skip ignored directories
            parts = txt.relative_to(self.base_dir).parts
            if any(p in _IGNORED for p in parts):
                continue
            parent = txt.parent
            dir_txts.setdefault(parent, []).append(txt)

        if not dir_txts:
            return ""

        # Pick the largest .txt per directory
        sampled: list[Path] = []
        for _dir, txts in sorted(dir_txts.items()):
            largest = max(txts, key=lambda p: p.stat().st_size)
            sampled.append(largest)

        # Ensure the overall largest .txt is always included (likely main document)
        all_txts = [t for txts in dir_txts.values() for t in txts]
        overall_largest = max(all_txts, key=lambda p: p.stat().st_size)
        if overall_largest not in sampled:
            sampled.insert(0, overall_largest)

        # Build excerpts — main document gets more lines
        parts = []
        for txt_path in sampled:
            rel = txt_path.relative_to(self.base_dir)
            n_lines = _SAMPLE_LINES * 2 if txt_path == overall_largest else _SAMPLE_LINES
            excerpt = self._tool_read_txt_excerpt(str(rel), n_lines)
            size_kb = txt_path.stat().st_size / 1024
            label = " (LARGEST FILE — likely main document)" if txt_path == overall_largest else ""
            parts.append(f"=== {rel} ({size_kb:.0f} KB){label} ===\n{excerpt}")

        return "\n\n".join(parts)

    def _dispatch(self, tool_name: str, args: dict) -> str:
        if tool_name == "list_directory":
            return self._tool_list_directory()
        if tool_name == "read_pdf_pages":
            return self._tool_read_pdf_pages(
                filename=args.get("filename", ""),
                pages=str(args.get("pages", "1-3")),
            )
        if tool_name == "read_txt_excerpt":
            return self._tool_read_txt_excerpt(
                filename=args.get("filename", ""),
                lines=int(args.get("lines", 50)),
            )
        if tool_name == "read_excerpts":
            filenames = args.get("filenames", [])
            if not isinstance(filenames, list):
                filenames = [filenames]
            return self._tool_read_excerpts(
                filenames=filenames,
                lines=int(args.get("lines", 40)),
            )
        return f"[ERROR: Unknown tool '{tool_name}']"

    # -----------------------------------------------------------------------
    # Response parsing
    # -----------------------------------------------------------------------

    def _parse_response(self, text: str) -> tuple[str, dict]:
        """
        Try to extract a JSON object from the LLM response.
        Returns ("final", data), ("tool_call", data), or ("unknown", {}).
        """
        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?\s*", "", text).strip()

        # Try to find a JSON object anywhere in the text
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return "unknown", {}

        try:
            obj = json.loads(match.group())
        except json.JSONDecodeError:
            return "unknown", {}

        if "final" in obj:
            return "final", obj["final"]
        if "tool_call" in obj:
            return "tool_call", obj["tool_call"]
        return "unknown", {}

    def _build_result(self, data: dict) -> Optional[DiscoveryResult]:
        project_json = data.get("project_json")
        if not isinstance(project_json, dict):
            return None

        # Merge missing top-level keys from template so validation doesn't fail
        for key, value in PROJECT_JSON_TEMPLATE.items():
            if key not in project_json:
                project_json[key] = value

        skip_confirm = bool(data.get("skip_confirm", False))
        pipeline_plan = data.get("pipeline_plan", [])
        if not isinstance(pipeline_plan, list):
            pipeline_plan = []

        return DiscoveryResult(
            project_json=project_json,
            skip_confirm=skip_confirm,
            pipeline_plan=pipeline_plan,
        )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_page_spec(spec: str) -> list[int]:
        """Convert '1-3' or '1,3,5' or '2' to 0-based page index list."""
        indices = []
        for part in spec.split(","):
            part = part.strip()
            if "-" in part:
                bounds = part.split("-", 1)
                try:
                    start, end = int(bounds[0]), int(bounds[1])
                    indices.extend(range(start - 1, end))
                except ValueError:
                    pass
            else:
                try:
                    indices.append(int(part) - 1)
                except ValueError:
                    pass
        return indices
