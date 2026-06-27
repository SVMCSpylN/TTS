"""Parser for OPIC scripts containing speaker-tagged text."""

from __future__ import annotations

import re
from pathlib import Path


SUPPORTED_SPEAKERS = {"SYSTEM", "USER"}
SUPPORTED_EMOTIONS = {
    "neutral",
    "calm",
    "warm",
    "happy",
    "excited",
    "surprised",
    "worried",
    "concerned",
    "disappointed",
    "embarrassed",
    "frustrated",
    "relieved",
    "grateful",
    "curious",
    "polite",
    "professional",
    "reassuring",
    "determined",
    # Kept for compatibility with existing scripts such as Q22.txt.
    "cooperative",
}
SUPPORTED_PACES = {"slow", "medium", "fast"}
_TAG_PATTERN = re.compile(
    r"^\s*\[([^\]]+)\](?:\[([^\]]+)\])?(?:\[([^\]]+)\])?\s*(.*)$"
)
_PAUSE_PATTERN = re.compile(
    r"(?:<pause:([^>]+)>|\[pause:([^\]]+)\])", re.IGNORECASE
)


class ScriptParseError(ValueError):
    """Raised when an OPIC script is malformed."""


def parse_text(content: str, source: str = "<text>") -> list[dict[str, str | None]]:
    """Parse script content into ordered speech segments with optional style."""
    segments: list[dict[str, str | None]] = []
    current_speaker: str | None = None
    current_emotion: str | None = None
    current_pace: str | None = None
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
        _validate_pauses(text, source, current_tag_line)
        segment: dict[str, str | None] = {
            "speaker": current_speaker,
            "text": text,
        }
        if current_emotion:
            segment["emotion"] = current_emotion
        if current_pace:
            segment["pace"] = current_pace
        segments.append(segment)

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        if re.fullmatch(r"\s*\[pause:[^\]]+\]\s*", raw_line, re.IGNORECASE):
            if current_speaker is None:
                raise ScriptParseError(
                    f"{source}:{line_number}: pause appears before the first speaker tag."
                )
            current_lines.append(raw_line.strip())
            continue

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
            emotion = _normalize_style(tag_match.group(2))
            pace = _normalize_style(tag_match.group(3))
            if emotion and emotion not in SUPPORTED_EMOTIONS:
                allowed = ", ".join(sorted(SUPPORTED_EMOTIONS))
                raise ScriptParseError(
                    f"{source}:{line_number}: unknown emotion [{emotion}]. "
                    f"Expected one of: {allowed}."
                )
            if pace and pace not in SUPPORTED_PACES:
                allowed = ", ".join(sorted(SUPPORTED_PACES))
                raise ScriptParseError(
                    f"{source}:{line_number}: unknown pace [{pace}]. "
                    f"Expected one of: {allowed}."
                )
            current_speaker = speaker
            current_emotion = emotion
            current_pace = pace
            current_lines = [tag_match.group(4)] if tag_match.group(4) else []
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


def _normalize_style(value: str | None) -> str | None:
    return value.strip().lower() if value else None


def _validate_pauses(text: str, source: str, line_number: int) -> None:
    for match in _PAUSE_PATTERN.finditer(text):
        pause_value = match.group(1) or match.group(2)
        try:
            seconds = float(pause_value)
        except ValueError as exc:
            raise ScriptParseError(
                f"{source}:{line_number}: invalid pause {match.group(0)}."
            ) from exc
        if not 0 <= seconds <= 10:
            raise ScriptParseError(
                f"{source}:{line_number}: pause must be between 0 and 10 seconds."
            )

    text_without_valid_pauses = _PAUSE_PATTERN.sub("", text)
    if re.search(
        r"(?:<pause[^>]*>|\[pause[^\]]*\])",
        text_without_valid_pauses,
        re.IGNORECASE,
    ):
        raise ScriptParseError(
            f"{source}:{line_number}: invalid pause. "
            "Use <pause:0.5> or [pause:0.5]."
        )


def parse_file(path: str | Path) -> list[dict[str, str | None]]:
    """Read and parse a UTF-8 OPIC script file."""
    script_path = Path(path)
    try:
        content = script_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScriptParseError(f"Could not read {script_path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ScriptParseError(f"{script_path} is not valid UTF-8 text.") from exc

    return parse_text(content, source=str(script_path))
