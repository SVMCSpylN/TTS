"""Generate OPIC practice audio from one text file or a folder of text files."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from audio_utils import AudioProcessingError, export_wav_to_mp3
from parser import SUPPORTED_EMOTIONS, ScriptParseError, parse_file
from tts_engine import BaseTTSEngine, ChatterboxEngine, TTSError


PROJECT_ROOT = Path(__file__).resolve().parent
VERSION_NAMES = ("IH", "IM")
DEFAULT_CONFIG = PROJECT_ROOT / "config.yaml"
SUPPORTED_PACES = {"slow", "medium", "fast"}


class ConfigurationError(ValueError):
    """Raised when config.yaml contains invalid settings."""


def _parse_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "on"}:
            return True
        if normalized in {"false", "no", "0", "off"}:
            return False
    raise ConfigurationError(f"{name} must be true or false.")


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
    try:
        output_sample_rate = int(raw_config.get("output_sample_rate", 44100))
        output_channels = int(raw_config.get("output_channels", 2))
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            "output_sample_rate and output_channels must be integers."
        ) from exc
    if output_sample_rate <= 0:
        raise ConfigurationError("output_sample_rate must be greater than zero.")
    if output_channels not in (1, 2):
        raise ConfigurationError("output_channels must be 1 or 2.")
    raw_config["output_sample_rate"] = output_sample_rate
    raw_config["output_channels"] = output_channels
    raw_config["normalize_audio"] = _parse_bool(
        raw_config.get("normalize_audio", True), "normalize_audio"
    )
    raw_config["regenerate_existing"] = _parse_bool(
        raw_config.get("regenerate_existing", False), "regenerate_existing"
    )
    raw_config["voices"] = _resolve_voice_paths(raw_config["voices"], path.parent)
    return raw_config


def _resolve_voice_paths(
    voices: dict[str, Any], config_directory: Path
) -> dict[str, str | None]:
    resolved: dict[str, str | None] = {}
    for speaker in ("SYSTEM", "USER"):
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
        voice_lead_in_ms = int(tts_config.get("voice_lead_in_ms", 45))
        voice_fade_in_ms = int(tts_config.get("voice_fade_in_ms", 35))
        chunk_fade_out_ms = int(tts_config.get("chunk_fade_out_ms", 20))
        user_tail_silence_ms = int(tts_config.get("user_tail_silence_ms", 0))
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            "TTS chunk and voice smoothing settings must be integers."
        ) from exc
    if max_chunk_chars < 40:
        raise ConfigurationError("tts.max_chunk_chars must be at least 40.")
    if sentence_pause_ms < 0:
        raise ConfigurationError("tts.sentence_pause_ms cannot be negative.")
    if not 0 <= voice_lead_in_ms <= 250:
        raise ConfigurationError("tts.voice_lead_in_ms must be between 0 and 250.")
    if not 0 <= voice_fade_in_ms <= 250:
        raise ConfigurationError("tts.voice_fade_in_ms must be between 0 and 250.")
    if not 0 <= chunk_fade_out_ms <= 100:
        raise ConfigurationError("tts.chunk_fade_out_ms must be between 0 and 100.")
    if not 0 <= user_tail_silence_ms <= 3000:
        raise ConfigurationError("tts.user_tail_silence_ms must be between 0 and 3000.")
    pace_override = _optional_string(tts_config.get("pace_override"))
    if pace_override and pace_override not in SUPPORTED_PACES:
        raise ConfigurationError(
            "tts.pace_override must be one of: slow, medium, fast."
        )
    emotion_overrides = _emotion_overrides(tts_config.get("emotion_overrides"))

    return ChatterboxEngine(
        sample_rate=config["sample_rate"],
        voices=config["voices"],
        device=str(tts_config.get("device", "auto")),
        model_options=model_options,
        max_chunk_chars=max_chunk_chars,
        sentence_pause_ms=sentence_pause_ms,
        pace_override=pace_override,
        emotion_overrides=emotion_overrides,
        voice_lead_in_ms=voice_lead_in_ms,
        voice_fade_in_ms=voice_fade_in_ms,
        chunk_fade_out_ms=chunk_fade_out_ms,
    )


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _emotion_overrides(value: Any) -> dict[str, str]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ConfigurationError("tts.emotion_overrides must be a YAML mapping.")

    overrides: dict[str, str] = {}
    for source, target in value.items():
        source_emotion = _optional_string(source)
        target_emotion = _optional_string(target)
        if not source_emotion or not target_emotion:
            raise ConfigurationError(
                "tts.emotion_overrides must map emotion names to emotion names."
            )
        if source_emotion not in SUPPORTED_EMOTIONS:
            raise ConfigurationError(
                f"tts.emotion_overrides contains unknown emotion: {source_emotion}"
            )
        if target_emotion not in SUPPORTED_EMOTIONS:
            raise ConfigurationError(
                f"tts.emotion_overrides maps {source_emotion} to unknown emotion: "
                f"{target_emotion}"
            )
        overrides[source_emotion] = target_emotion
    return overrides


def _version_input_root(path: Path) -> Path | None:
    """Return the IH/input or IM/input ancestor for a path."""
    resolved = path.resolve()
    for candidate in (resolved, *resolved.parents):
        if (
            candidate.name == "input"
            and candidate.parent.name.upper() in VERSION_NAMES
        ):
            return candidate
    return None


def _input_scopes(input_path: Path) -> list[tuple[Path, Path]]:
    """Resolve a CLI path to one or more (search path, input root) pairs."""
    resolved = input_path.resolve()
    if resolved == PROJECT_ROOT:
        scopes = [
            (version_root, version_root)
            for name in VERSION_NAMES
            if (version_root := PROJECT_ROOT / name / "input").is_dir()
        ]
        if scopes:
            return scopes

    if (
        resolved.is_dir()
        and resolved.name.upper() in VERSION_NAMES
        and (resolved / "input").is_dir()
    ):
        return [(resolved / "input", resolved / "input")]

    input_root = _version_input_root(resolved)
    if input_root is None:
        raise ValueError(
            f"Input path must be inside IH/input or IM/input: {input_path}"
        )
    return [(resolved, input_root)]


def discover_inputs(input_path: Path) -> list[Path]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    if input_path.is_file():
        if input_path.suffix.lower() != ".txt":
            raise ValueError(f"Input file must have a .txt extension: {input_path}")
        input_root = _version_input_root(input_path)
        if input_root is None:
            raise ValueError(
                f"Input file must be inside IH/input or IM/input: {input_path}"
            )
        if input_path.resolve().parent == input_root:
            raise ValueError(
                f"Input file must be inside a category folder under {input_root}: "
                f"{input_path}"
            )
        return [input_path]
    if not input_path.is_dir():
        raise ValueError(f"Input path is neither a file nor a folder: {input_path}")

    files: list[Path] = []
    for search_path, input_root in _input_scopes(input_path):
        files.extend(
            path
            for path in search_path.rglob("*")
            if (
                path.is_file()
                and path.suffix.lower() == ".txt"
                and path.resolve().parent != input_root.resolve()
            )
        )
    files.sort(key=lambda path: path.resolve().as_posix().lower())
    if not files:
        raise FileNotFoundError(f"No .txt files found in folder: {input_path}")
    return files


def output_path_for(
    input_file: Path,
    input_root: Path | None = None,
    output_root: Path | None = None,
) -> Path:
    """Map a versioned input TXT to its matching IH/output or IM/output folder."""
    if input_root is None:
        input_root = _version_input_root(input_file)
        if input_root is None:
            raise ValueError(
                f"Input file must be inside IH/input or IM/input: {input_file}"
            )
    if output_root is None:
        output_root = input_root.parent / "output"
    try:
        relative_path = input_file.resolve().relative_to(input_root.resolve())
    except ValueError as exc:
        raise ValueError(f"{input_file} is not inside input root {input_root}") from exc
    return (output_root / relative_path).with_suffix("")


def generate_file(
    input_file: Path,
    engine: BaseTTSEngine,
    config: dict[str, Any],
    output_directory: Path,
    temp_root: Path,
) -> list[Path]:
    segments = parse_file(input_file)

    temp_root.mkdir(parents=True, exist_ok=True)
    output_directory.mkdir(parents=True, exist_ok=True)
    for stale_mp3 in output_directory.glob("*.mp3"):
        stale_mp3.unlink()

    work_directory = Path(
        tempfile.mkdtemp(prefix=f"{input_file.stem}_", dir=temp_root)
    )
    try:
        generated_paths: list[Path] = []
        unit_index = 1
        for segment in segments:
            speaker = str(segment["speaker"])
            emotion = segment.get("emotion")
            pace = segment.get("pace")
            for unit_text in engine.speech_unit_texts(
                str(segment["text"]),
                speaker=speaker,
                emotion=emotion,
                pace=pace,
            ):
                wav_path = work_directory / f"{unit_index:04d}_{speaker.lower()}.wav"
                mp3_path = output_directory / f"{unit_index:02d}.mp3"
                engine.synthesize(
                    unit_text,
                    speaker,
                    wav_path,
                    emotion=emotion,
                    pace=pace,
                )
                generated_paths.append(
                    export_wav_to_mp3(
                        wav_path,
                        mp3_path,
                        mp3_bitrate=config.get("mp3_bitrate", "192k"),
                        normalize_audio=config.get("normalize_audio", True),
                        output_sample_rate=config.get("output_sample_rate", 44100),
                        output_channels=config.get("output_channels", 2),
                        tail_silence_ms=(
                            (config.get("tts") or {}).get("user_tail_silence_ms", 0)
                            if speaker.upper() == "USER"
                            else 0
                        ),
                    )
                )
                unit_index += 1

        return generated_paths
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
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="Regenerate MP3 files even when matching outputs already exist",
    )
    return parser


def _has_generated_mp3s(output_directory: Path) -> bool:
    return output_directory.is_dir() and any(output_directory.glob("*.mp3"))


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        config_path = args.config.expanduser().resolve()
        config = load_config(config_path)
        inputs = discover_inputs(args.input.expanduser().resolve())

        temp_root = PROJECT_ROOT / "temp"
        regenerate = args.rerun or config["regenerate_existing"]
        jobs: list[tuple[Path, Path]] = []
        for input_file in inputs:
            output_directory = output_path_for(input_file)
            if _has_generated_mp3s(output_directory) and not regenerate:
                print(f"Skipped existing {output_directory}")
                continue
            jobs.append((input_file, output_directory))

        if not jobs:
            print("No files to generate.")
            return 0

        engine = create_engine(config)
        failures = 0
        for input_file, output_directory in jobs:
            try:
                generated_path = generate_file(
                    input_file, engine, config, output_directory, temp_root
                )
                print(
                    f"Created {len(generated_path)} MP3 files in {output_directory}"
                )
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
