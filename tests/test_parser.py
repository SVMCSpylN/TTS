import tempfile
import unittest
from pathlib import Path

from parser import ScriptParseError, parse_file, parse_text


class ParserTests(unittest.TestCase):
    def test_parses_inline_and_multiline_segments(self) -> None:
        result = parse_text(
            "[SYSTEM] Welcome.\n[NPC]\nFirst line.\nSecond line.\n[USER] Answer."
        )

        self.assertEqual(
            result,
            [
                {"speaker": "SYSTEM", "text": "Welcome."},
                {"speaker": "NPC", "text": "First line.\nSecond line."},
                {"speaker": "USER", "text": "Answer."},
            ],
        )

    def test_rejects_unknown_tag(self) -> None:
        with self.assertRaisesRegex(ScriptParseError, "unknown speaker tag"):
            parse_text("[HOST] Hello", source="Q1.txt")

    def test_rejects_empty_segment(self) -> None:
        with self.assertRaisesRegex(ScriptParseError, "has empty text"):
            parse_text("[NPC]\n[USER] Hello")

    def test_rejects_text_before_tag(self) -> None:
        with self.assertRaisesRegex(ScriptParseError, "before the first speaker"):
            parse_text("Hello\n[NPC] World")

    def test_reads_utf8_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Q1.txt"
            path.write_text("[USER] Xin chào", encoding="utf-8")
            self.assertEqual(
                parse_file(path), [{"speaker": "USER", "text": "Xin chào"}]
            )


if __name__ == "__main__":
    unittest.main()
