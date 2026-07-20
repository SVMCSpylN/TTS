import re
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
    main,
    output_path_for,
)
from tts_engine import BaseTTSEngine


class FakeEngine(BaseTTSEngine):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Path, str | None, str | None]] = []

    def synthesize(
        self,
        text: str,
        speaker: str,
        output_path: Path,
        emotion: str | None = None,
        pace: str | None = None,
    ) -> None:
        self.calls.append((text, speaker, output_path, emotion, pace))
        output_path.write_bytes(b"fake wav")

    def speech_unit_texts(
        self,
        text: str,
        speaker: str | None = None,
        emotion: str | None = None,
        pace: str | None = None,
    ) -> list[str]:
        text = re.sub(
            r"(?:<pause:[^>]+>|\[pause:[^\]]+\])",
            "\n",
            text,
            flags=re.IGNORECASE,
        )
        return [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+|\n+", text.strip())
            if part.strip()
        ]


class GenerateTests(unittest.TestCase):
    def test_discovers_sorted_txt_files_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "IH" / "input"
            input_root.mkdir(parents=True)
            (input_root / "root-file.txt").touch()
            (input_root / "housing").mkdir()
            (input_root / "housing" / "B.txt").touch()
            (input_root / "housing" / "A.TXT").touch()
            (input_root / "housing" / "Q1.txt").touch()
            (input_root / "ignored.md").touch()

            self.assertEqual(
                [
                    path.relative_to(input_root).as_posix()
                    for path in discover_inputs(input_root)
                ],
                ["housing/A.TXT", "housing/B.txt", "housing/Q1.txt"],
            )

    def test_rejects_txt_directly_under_input_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_file = root / "IH" / "input" / "Q38.txt"
            input_file.parent.mkdir(parents=True)
            input_file.touch()

            with self.assertRaisesRegex(ValueError, "category folder"):
                discover_inputs(input_file)

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
                "  USER: voices/user.wav\n",
                encoding="utf-8",
            )

            config = load_config(config_path)
            self.assertEqual(config["sample_rate"], 24000)
            self.assertEqual(config["voices"]["USER"], str(root / "voices/user.wav"))
            self.assertFalse(config["regenerate_existing"])
            self.assertEqual(config["output_sample_rate"], 44100)
            self.assertEqual(config["output_channels"], 2)

    def test_maps_nested_input_to_matching_output_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_file = root / "input" / "home appliances" / "Q24.txt"

            self.assertEqual(
                output_path_for(input_file, root / "input", root / "output"),
                root / "output" / "home appliances" / "Q24",
            )

    def test_infers_output_root_for_each_text_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for version in ("IH", "IM"):
                input_file = root / version / "input" / "park" / "Park 01.txt"
                self.assertEqual(
                    output_path_for(input_file),
                    root / version / "output" / "park" / "Park 01",
                )

    def test_version_folder_discovers_only_its_own_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ih_file = root / "IH" / "input" / "park" / "IH.txt"
            im_file = root / "IM" / "input" / "park" / "IM.txt"
            ih_file.parent.mkdir(parents=True)
            im_file.parent.mkdir(parents=True)
            ih_file.touch()
            im_file.touch()

            self.assertEqual(discover_inputs(root / "IH"), [ih_file])
            self.assertEqual(discover_inputs(root / "IM"), [im_file])

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
                "voices": {"SYSTEM": None, "USER": None},
                "tts": {
                    "max_chunk_chars": 180,
                    "sentence_pause_ms": 150,
                    "voice_lead_in_ms": 40,
                    "voice_fade_in_ms": 30,
                    "chunk_fade_out_ms": 15,
                },
            }
        )

        self.assertEqual(engine.max_chunk_chars, 180)
        self.assertEqual(engine.sentence_pause_ms, 150)
        self.assertIsNone(engine.pace_override)
        self.assertEqual(engine.voice_lead_in_ms, 40)
        self.assertEqual(engine.voice_fade_in_ms, 30)
        self.assertEqual(engine.chunk_fade_out_ms, 15)

    def test_pace_override_forces_tagged_pace_to_configured_pace(self) -> None:
        engine = create_engine(
            {
                "sample_rate": 24000,
                "voices": {"SYSTEM": None, "USER": None},
                "tts": {
                    "pace_override": "slow",
                    "model_options": {"cfg_weight": 0.30},
                },
            }
        )

        for pace in ("medium", "fast"):
            options, sentence_pause_ms = engine._style_options(None, pace)
            self.assertEqual(options["cfg_weight"], 0.20)
            self.assertEqual(sentence_pause_ms, 351)

    def test_passes_emotion_overrides_to_engine(self) -> None:
        engine = create_engine(
            {
                "sample_rate": 24000,
                "voices": {"SYSTEM": None, "USER": None},
                "tts": {
                    "emotion_overrides": {
                        "excited": "warm",
                        "worried": "concerned",
                    },
                },
            }
        )

        self.assertEqual(engine.emotion_overrides["excited"], "warm")
        self.assertEqual(engine.emotion_overrides["worried"], "concerned")

    def test_rejects_invalid_emotion_override(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "unknown emotion"):
            create_engine(
                {
                    "sample_rate": 24000,
                    "voices": {"SYSTEM": None, "USER": None},
                    "tts": {"emotion_overrides": {"excited": "sleepy"}},
                }
            )

    def test_rejects_invalid_pace_override(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "tts.pace_override"):
            create_engine(
                {
                    "sample_rate": 24000,
                    "voices": {"SYSTEM": None, "USER": None},
                    "tts": {"pace_override": "very-slow"},
                }
            )

    def test_emotion_overrides_use_calmer_generation_style(self) -> None:
        engine = create_engine(
            {
                "sample_rate": 24000,
                "voices": {"SYSTEM": None, "USER": None},
                "tts": {
                    "model_options": {"cfg_weight": 0.30},
                    "emotion_overrides": {
                        "excited": "warm",
                        "worried": "concerned",
                    },
                },
            }
        )

        neutral_options, neutral_pause_ms = engine._style_options(
            "neutral", "medium", "USER"
        )
        warm_options, warm_pause_ms = engine._style_options("warm", "medium", "USER")
        excited_options, excited_pause_ms = engine._style_options(
            "excited", "medium", "USER"
        )
        worried_options, worried_pause_ms = engine._style_options(
            "worried", "medium", "USER"
        )

        self.assertAlmostEqual(neutral_options["cfg_weight"], 0.15624)
        self.assertAlmostEqual(warm_options["cfg_weight"], 0.15624)
        self.assertAlmostEqual(worried_options["cfg_weight"], 0.15624)
        self.assertAlmostEqual(excited_options["cfg_weight"], 0.15624)
        self.assertEqual(neutral_pause_ms, 373)
        self.assertEqual(warm_pause_ms, 373)
        self.assertEqual(worried_pause_ms, 373)
        self.assertEqual(excited_pause_ms, 373)
        self.assertEqual(excited_options["exaggeration"], 0.45)
        self.assertEqual(worried_options["exaggeration"], 0.50)

    def test_user_speaker_runs_at_seventy_percent_of_system_pace(self) -> None:
        engine = create_engine(
            {
                "sample_rate": 24000,
                "voices": {"SYSTEM": None, "USER": None},
                "tts": {"pace_override": "slow"},
            }
        )

        system_options, system_pause_ms = engine._style_options(
            "neutral", "fast", "SYSTEM"
        )
        user_options, user_pause_ms = engine._style_options(
            "neutral", "fast", "USER"
        )

        self.assertEqual(system_options["cfg_weight"], 0.20)
        self.assertEqual(system_pause_ms, 351)
        self.assertAlmostEqual(user_options["cfg_weight"], 0.1302)
        self.assertEqual(user_pause_ms, 539)

    def test_rejects_invalid_chunk_size(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "at least 40"):
            create_engine(
                {
                    "sample_rate": 24000,
                    "voices": {"SYSTEM": None, "USER": None},
                    "tts": {"max_chunk_chars": 20},
                }
            )

    def test_generate_file_synthesizes_units_into_lesson_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_file = root / "Q23.txt"
            input_file.write_text(
                "[SYSTEM] Start.\n[USER] Question.\n[USER] Answer.",
                encoding="utf-8",
            )
            engine = FakeEngine()
            expected_output = root / "output" / "Q23"

            def fake_export(wav_path, output_path, **_kwargs):
                Path(output_path).write_bytes(b"fake mp3")
                return Path(output_path)

            with patch("generate.export_wav_to_mp3", side_effect=fake_export) as export:
                result = generate_file(
                    input_file,
                    engine,
                    {
                        "pause_ms": 700,
                        "output_format": "mp3",
                        "tts": {"user_tail_silence_ms": 500},
                    },
                    expected_output,
                    root / "temp",
                )

            self.assertEqual(
                result,
                [
                    expected_output / "01.mp3",
                    expected_output / "02.mp3",
                    expected_output / "03.mp3",
                ],
            )
            self.assertEqual(
                [(text, speaker) for text, speaker, _, _, _ in engine.calls],
                [
                    ("Start.", "SYSTEM"),
                    ("Question.", "USER"),
                    ("Answer.", "USER"),
                ],
            )
            self.assertEqual(
                [call.args[1] for call in export.call_args_list],
                [
                    expected_output / "01.mp3",
                    expected_output / "02.mp3",
                    expected_output / "03.mp3",
                ],
            )
            self.assertEqual(export.call_args.kwargs["output_sample_rate"], 44100)
            self.assertEqual(export.call_args.kwargs["output_channels"], 2)
            self.assertEqual(
                [call.kwargs["tail_silence_ms"] for call in export.call_args_list],
                [0, 500, 500],
            )
            self.assertFalse(any((root / "temp").iterdir()))

    def test_generate_file_splits_pause_markers_into_separate_mp3s(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_file = root / "Q1.txt"
            input_file.write_text(
                "[USER][polite][medium] Hello. <pause:0.5>\nNext question?",
                encoding="utf-8",
            )
            output_directory = root / "output" / "Q1"

            with patch(
                "generate.export_wav_to_mp3",
                side_effect=lambda _wav, mp3, **_kwargs: Path(mp3),
            ) as export:
                generate_file(
                    input_file,
                    engine := FakeEngine(),
                    {"pause_ms": 700, "output_format": "mp3"},
                    output_directory,
                    root / "temp",
                )

            self.assertEqual(
                [(text, speaker) for text, speaker, _, _, _ in engine.calls],
                [("Hello.", "USER"), ("Next question?", "USER")],
            )
            self.assertEqual(
                [call.args[1] for call in export.call_args_list],
                [output_directory / "01.mp3", output_directory / "02.mp3"],
            )

    def test_generate_file_removes_stale_mp3s_on_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_file = root / "Q1.txt"
            input_file.write_text("[USER] Hello.", encoding="utf-8")
            output_directory = root / "output" / "Q1"
            output_directory.mkdir(parents=True)
            stale_file = output_directory / "99.mp3"
            stale_file.write_bytes(b"stale")

            with patch(
                "generate.export_wav_to_mp3",
                side_effect=lambda _wav, mp3, **_kwargs: Path(mp3),
            ):
                generate_file(
                    input_file,
                    FakeEngine(),
                    {"pause_ms": 700, "output_format": "mp3"},
                    output_directory,
                    root / "temp",
                )

            self.assertFalse(stale_file.exists())

    def test_main_skips_existing_output_without_loading_engine(self) -> None:
        input_file = Path("/tmp/input/housing/Q1.txt")
        output_directory = Path("/tmp/output/housing/Q1")

        with (
            patch("generate.discover_inputs", return_value=[input_file]),
            patch("generate.output_path_for", return_value=output_directory),
            patch("generate._has_generated_mp3s", return_value=True),
            patch("generate.create_engine") as create_engine_mock,
            patch("builtins.print"),
        ):
            result = main(["input/"])

        self.assertEqual(result, 0)
        create_engine_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
