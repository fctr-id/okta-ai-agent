import unittest

from src.integrations.teams.message_text import clean_message_text


class MessageTextTests(unittest.TestCase):
    def test_pasted_whitespace_and_invisible_controls(self):
        self.assertEqual(
            clean_message_text("\ufeff  List\u00a0users\r\n\tall\x00 statuses\rnow\u202e\u2066\u200b  "),
            "List users\n\tall statuses\nnow",
        )

    def test_preserves_language_emoji_operators_and_literal_text(self):
        text = "Jos\u00e9\u2019s \u7528\u6237 \u0645\u06cc\u200c\u0631\u0648\u0645 \U0001f469\u200d\U0001f4bb: count < 5 && score > 1; <admin@example.test> &amp;"
        self.assertEqual(clean_message_text(text), text)

    def test_empty_or_control_only_rejected(self):
        for text in ("", " \r\n\t", "\x00\x01\u202e\ufeff", "\ud800"):
            with self.subTest(text=repr(text)), self.assertRaisesRegex(ValueError, "^empty_text$"):
                clean_message_text(text)

    def test_limit_applies_before_cleanup(self):
        self.assertEqual(clean_message_text("x" * 8000), "x" * 8000)
        for text in ("x" * 8001, " " * 8000 + "x", "\x00" * 8000 + "x"):
            with self.assertRaisesRegex(ValueError, "^text_too_long$"):
                clean_message_text(text)

    def test_idempotent(self):
        text = " \ufeffHello\u00a0world\r\n\u202e\U0001f419 "
        cleaned = clean_message_text(text)
        self.assertEqual(clean_message_text(cleaned), cleaned)


if __name__ == "__main__":
    unittest.main()
