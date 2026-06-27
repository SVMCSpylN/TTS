import tempfile
import unittest
from pathlib import Path

from parser import SUPPORTED_EMOTIONS, SUPPORTED_PACES, ScriptParseError, parse_file, parse_text


class ParserTests(unittest.TestCase):
    def test_parses_inline_and_multiline_segments(self) -> None:
        result = parse_text(
            "[SYSTEM] Welcome.\n[USER]\nFirst line.\nSecond line.\n[SYSTEM] Thanks."
        )

        self.assertEqual(
            result,
            [
                {"speaker": "SYSTEM", "text": "Welcome."},
                {"speaker": "USER", "text": "First line.\nSecond line."},
                {"speaker": "SYSTEM", "text": "Thanks."},
            ],
        )

    def test_rejects_unknown_tag(self) -> None:
        with self.assertRaisesRegex(ScriptParseError, "unknown speaker tag"):
            parse_text("[HOST] Hello", source="Q1.txt")

    def test_rejects_empty_segment(self) -> None:
        with self.assertRaisesRegex(ScriptParseError, "has empty text"):
            parse_text("[SYSTEM]\n[USER] Hello")

    def test_rejects_text_before_tag(self) -> None:
        with self.assertRaisesRegex(ScriptParseError, "before the first speaker"):
            parse_text("Hello\n[SYSTEM] World")

    def test_reads_utf8_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Q1.txt"
            path.write_text("[USER] Xin chào", encoding="utf-8")
            self.assertEqual(
                parse_file(path), [{"speaker": "USER", "text": "Xin chào"}]
            )

    def test_parses_emotion_pace_and_pause(self) -> None:
        self.assertEqual(
            parse_text("[USER][happy][slow] Hello. <pause:0.5>"),
            [
                {
                    "speaker": "USER",
                    "text": "Hello. <pause:0.5>",
                    "emotion": "happy",
                    "pace": "slow",
                }
            ],
        )

    def test_rejects_unknown_emotion(self) -> None:
        with self.assertRaisesRegex(ScriptParseError, "unknown emotion"):
            parse_text("[USER][angryish][slow] Hello.")

    def test_rejects_invalid_pause(self) -> None:
        with self.assertRaisesRegex(ScriptParseError, "invalid pause"):
            parse_text("[USER][neutral][medium] Hello. <pause:abc>")

    def test_accepts_square_bracket_pause(self) -> None:
        result = parse_text("[USER][neutral][medium] Hello. [pause:0.4] Next.")
        self.assertEqual(result[0]["text"], "Hello. [pause:0.4] Next.")

    def test_accepts_square_bracket_pause_on_its_own_line(self) -> None:
        result = parse_text(
            "[USER][neutral][medium]\nHello.\n[pause:0.4]\nNext."
        )
        self.assertEqual(result[0]["text"], "Hello.\n[pause:0.4]\nNext.")

    def test_accepts_all_documented_emotions_and_paces(self) -> None:
        documented_emotions = {
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
        }
        self.assertTrue(documented_emotions.issubset(SUPPORTED_EMOTIONS))
        self.assertEqual(SUPPORTED_PACES, {"slow", "medium", "fast"})

        for emotion in documented_emotions:
            for pace in SUPPORTED_PACES:
                result = parse_text(f"[USER][{emotion}][{pace}] Test.")
                self.assertEqual(result[0]["emotion"], emotion)
                self.assertEqual(result[0]["pace"], pace)


if __name__ == "__main__":
    unittest.main()
