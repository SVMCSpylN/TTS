import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from generate import (
    ConfigurationError,
    create_engine,
    discover_inputs,
    generate_file,
    load_config,
)
from tts_engine import BaseTTSEngine


class FakeEngine(BaseTTSEngine):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Path]] = []

    def synthesize(self, text: str, speaker: str, output_path: Path) -> None:
        self.calls.append((text, speaker, output_path))
        output_path.write_bytes(b"fake wav")


class GenerateTests(unittest.TestCase):
    def test_discovers_sorted_txt_files_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "B.txt").touch()
            (root / "A.TXT").touch()
            (root / "ignored.md").touch()

            self.assertEqual(
                [path.name for path in discover_inputs(root)], ["A.TXT", "B.txt"]
            )

    def test_loads_and_resolves_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.yaml"
            config_path.write_text(
                "sample_rate: 24000\n"
                "pause_ms: 500\n"
                "output_format: mp3\n"
                "voices:\n"
                "  SYSTEM: null\n"
                "  NPC: voices/npc.wav\n"
                "  USER: null\n",
                encoding="utf-8",
            )

            config = load_config(config_path)
            self.assertEqual(config["sample_rate"], 24000)
            self.assertEqual(config["voices"]["NPC"], str(root / "voices/npc.wav"))

    def test_rejects_non_mp3_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            config_path.write_text(
                "sample_rate: 24000\n"
                "pause_ms: 500\n"
                "output_format: wav\n"
                "voices: {}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigurationError, "must be 'mp3'"):
                load_config(config_path)

    def test_passes_chunk_settings_to_engine(self) -> None:
        engine = create_engine(
            {
                "sample_rate": 24000,
                "voices": {"SYSTEM": None, "NPC": None, "USER": None},
                "tts": {"max_chunk_chars": 180, "sentence_pause_ms": 150},
            }
        )

        self.assertEqual(engine.max_chunk_chars, 180)
        self.assertEqual(engine.sentence_pause_ms, 150)

    def test_rejects_invalid_chunk_size(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "at least 40"):
            create_engine(
                {
                    "sample_rate": 24000,
                    "voices": {"SYSTEM": None, "NPC": None, "USER": None},
                    "tts": {"max_chunk_chars": 20},
                }
            )

    def test_generate_file_synthesizes_segments_and_preserves_basename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_file = root / "Q23.txt"
            input_file.write_text(
                "[SYSTEM] Start.\n[NPC] Question.\n[USER] Answer.",
                encoding="utf-8",
            )
            engine = FakeEngine()
            expected_output = root / "output" / "Q23.mp3"

            with patch("generate.concatenate_wavs", return_value=expected_output) as join:
                result = generate_file(
                    input_file,
                    engine,
                    {"pause_ms": 700, "output_format": "mp3"},
                    root / "output",
                    root / "temp",
                )

            self.assertEqual(result, expected_output)
            self.assertEqual(
                [(text, speaker) for text, speaker, _ in engine.calls],
                [
                    ("Start.", "SYSTEM"),
                    ("Question.", "NPC"),
                    ("Answer.", "USER"),
                ],
            )
            wav_paths = join.call_args.args[0]
            self.assertEqual(len(wav_paths), 3)
            self.assertEqual(join.call_args.args[1], expected_output)
            self.assertFalse(any((root / "temp").iterdir()))


if __name__ == "__main__":
    unittest.main()
