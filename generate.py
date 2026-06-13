"""Generate OPIC practice audio from one text file or a folder of text files."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from audio_utils import AudioProcessingError, concatenate_wavs
from parser import ScriptParseError, parse_file
from tts_engine import BaseTTSEngine, ChatterboxEngine, TTSError


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_ROOT / "config.yaml"


class ConfigurationError(ValueError):
    """Raised when config.yaml contains invalid settings."""


def load_config(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise ConfigurationError(
            "PyYAML is not installed. Install project dependencies first."
        ) from exc

    try:
        raw_config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(f"Could not read configuration {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw_config, dict):
        raise ConfigurationError(f"{path} must contain a YAML mapping.")

    required = ("sample_rate", "pause_ms", "output_format", "voices")
    missing = [key for key in required if key not in raw_config]
    if missing:
        raise ConfigurationError(f"Missing configuration keys: {', '.join(missing)}.")

    try:
        sample_rate = int(raw_config["sample_rate"])
        pause_ms = int(raw_config["pause_ms"])
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("sample_rate and pause_ms must be integers.") from exc

    if sample_rate <= 0:
        raise ConfigurationError("sample_rate must be greater than zero.")
    if pause_ms < 0:
        raise ConfigurationError("pause_ms cannot be negative.")
    if str(raw_config["output_format"]).lower() != "mp3":
        raise ConfigurationError("output_format must be 'mp3'.")
    if not isinstance(raw_config["voices"], dict):
        raise ConfigurationError("voices must be a mapping of speaker names to files.")

    raw_config["sample_rate"] = sample_rate
    raw_config["pause_ms"] = pause_ms
    raw_config["output_format"] = "mp3"
    raw_config["mp3_bitrate"] = str(raw_config.get("mp3_bitrate", "192k"))
    raw_config["normalize_audio"] = bool(raw_config.get("normalize_audio", True))
    raw_config["voices"] = _resolve_voice_paths(raw_config["voices"], path.parent)
    return raw_config


def _resolve_voice_paths(
    voices: dict[str, Any], config_directory: Path
) -> dict[str, str | None]:
    resolved: dict[str, str | None] = {}
    for speaker in ("SYSTEM", "NPC", "USER"):
        value = voices.get(speaker)
        if value in (None, ""):
            resolved[speaker] = None
            continue
        voice_path = Path(str(value)).expanduser()
        if not voice_path.is_absolute():
            voice_path = config_directory / voice_path
        resolved[speaker] = str(voice_path.resolve())
    return resolved


def create_engine(config: dict[str, Any]) -> BaseTTSEngine:
    tts_config = config.get("tts") or {}
    if not isinstance(tts_config, dict):
        raise ConfigurationError("tts must be a YAML mapping.")

    engine_name = str(tts_config.get("engine", "chatterbox")).lower()
    if engine_name != "chatterbox":
        raise ConfigurationError(f"Unsupported TTS engine: {engine_name}")

    model_options = tts_config.get("model_options") or {}
    if not isinstance(model_options, dict):
        raise ConfigurationError("tts.model_options must be a YAML mapping.")

    try:
        max_chunk_chars = int(tts_config.get("max_chunk_chars", 220))
        sentence_pause_ms = int(tts_config.get("sentence_pause_ms", 180))
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            "tts.max_chunk_chars and tts.sentence_pause_ms must be integers."
        ) from exc
    if max_chunk_chars < 40:
        raise ConfigurationError("tts.max_chunk_chars must be at least 40.")
    if sentence_pause_ms < 0:
        raise ConfigurationError("tts.sentence_pause_ms cannot be negative.")

    return ChatterboxEngine(
        sample_rate=config["sample_rate"],
        voices=config["voices"],
        device=str(tts_config.get("device", "auto")),
        model_options=model_options,
        max_chunk_chars=max_chunk_chars,
        sentence_pause_ms=sentence_pause_ms,
    )


def discover_inputs(input_path: Path) -> list[Path]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    if input_path.is_file():
        if input_path.suffix.lower() != ".txt":
            raise ValueError(f"Input file must have a .txt extension: {input_path}")
        return [input_path]
    if not input_path.is_dir():
        raise ValueError(f"Input path is neither a file nor a folder: {input_path}")

    files = sorted(
        path for path in input_path.iterdir() if path.is_file() and path.suffix.lower() == ".txt"
    )
    if not files:
        raise FileNotFoundError(f"No .txt files found in folder: {input_path}")
    return files


def generate_file(
    input_file: Path,
    engine: BaseTTSEngine,
    config: dict[str, Any],
    output_directory: Path,
    temp_root: Path,
) -> Path:
    segments = parse_file(input_file)
    output_path = output_directory / f"{input_file.stem}.mp3"

    temp_root.mkdir(parents=True, exist_ok=True)
    work_directory = Path(
        tempfile.mkdtemp(prefix=f"{input_file.stem}_", dir=temp_root)
    )
    try:
        wav_paths: list[Path] = []
        for index, segment in enumerate(segments, start=1):
            wav_path = work_directory / f"{index:04d}_{segment['speaker'].lower()}.wav"
            engine.synthesize(segment["text"], segment["speaker"], wav_path)
            wav_paths.append(wav_path)

        return concatenate_wavs(
            wav_paths,
            output_path,
            pause_ms=config["pause_ms"],
            output_format=config["output_format"],
            mp3_bitrate=config.get("mp3_bitrate", "192k"),
            normalize_audio=config.get("normalize_audio", True),
        )
    finally:
        shutil.rmtree(work_directory, ignore_errors=True)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate MP3 audio from OPIC speaker-tagged text."
    )
    parser.add_argument("input", type=Path, help="A .txt file or folder of .txt files")
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG, help="Path to config.yaml"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        config_path = args.config.expanduser().resolve()
        config = load_config(config_path)
        inputs = discover_inputs(args.input.expanduser().resolve())
        engine = create_engine(config)

        output_directory = PROJECT_ROOT / "output"
        temp_root = PROJECT_ROOT / "temp"
        failures = 0
        for input_file in inputs:
            try:
                output_path = generate_file(
                    input_file, engine, config, output_directory, temp_root
                )
                print(f"Created {output_path}")
            except (ScriptParseError, TTSError, AudioProcessingError, OSError) as exc:
                failures += 1
                print(f"Error processing {input_file}: {exc}", file=sys.stderr)

        return 1 if failures else 0
    except (ConfigurationError, FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
