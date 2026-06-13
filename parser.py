"""Parser for OPIC scripts containing speaker-tagged text."""

from __future__ import annotations

import re
from pathlib import Path


SUPPORTED_SPEAKERS = {"SYSTEM", "NPC", "USER"}
_TAG_PATTERN = re.compile(r"^\s*\[([^\]]+)\]\s*(.*)$")


class ScriptParseError(ValueError):
    """Raised when an OPIC script is malformed."""


def parse_text(content: str, source: str = "<text>") -> list[dict[str, str]]:
    """Parse script content into ordered ``speaker``/``text`` dictionaries."""
    segments: list[dict[str, str]] = []
    current_speaker: str | None = None
    current_lines: list[str] = []
    current_tag_line = 0

    def finish_segment() -> None:
        if current_speaker is None:
            return

        text = "\n".join(current_lines).strip()
        if not text:
            raise ScriptParseError(
                f"{source}:{current_tag_line}: [{current_speaker}] has empty text."
            )
        segments.append({"speaker": current_speaker, "text": text})

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        tag_match = _TAG_PATTERN.match(raw_line)
        if tag_match:
            finish_segment()
            speaker = tag_match.group(1).strip().upper()
            if speaker not in SUPPORTED_SPEAKERS:
                allowed = ", ".join(f"[{name}]" for name in sorted(SUPPORTED_SPEAKERS))
                raise ScriptParseError(
                    f"{source}:{line_number}: unknown speaker tag "
                    f"[{tag_match.group(1).strip()}]. Expected one of: {allowed}."
                )
            current_speaker = speaker
            current_lines = [tag_match.group(2)] if tag_match.group(2) else []
            current_tag_line = line_number
            continue

        if current_speaker is None:
            if raw_line.strip():
                raise ScriptParseError(
                    f"{source}:{line_number}: text appears before the first speaker tag."
                )
            continue

        current_lines.append(raw_line)

    finish_segment()
    if not segments:
        raise ScriptParseError(f"{source}: no speech segments found.")
    return segments


def parse_file(path: str | Path) -> list[dict[str, str]]:
    """Read and parse a UTF-8 OPIC script file."""
    script_path = Path(path)
    try:
        content = script_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScriptParseError(f"Could not read {script_path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ScriptParseError(f"{script_path} is not valid UTF-8 text.") from exc

    return parse_text(content, source=str(script_path))
