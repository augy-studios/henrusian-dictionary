"""The copy rules, and the small formatting helpers."""

from utils.rich import compose
from utils.text import esc, format_date, one_line, plural, sanitise, split_for_telegram, truncate


class TestSanitiser:
    def test_em_dash_becomes_a_comma(self):
        assert sanitise("a word — another word") == "a word, another word"

    def test_tight_em_dash(self):
        assert sanitise("water—milk") == "water, milk"

    def test_numeric_range_reads_as_to(self):
        assert sanitise("8–16 entries") == "8 to 16 entries"

    def test_no_doubled_comma(self):
        assert sanitise("first, — second") == "first, second"

    def test_no_space_before_punctuation(self):
        assert sanitise("a word — .") == "a word,."

    def test_minus_sign_becomes_a_hyphen(self):
        assert sanitise("−5") == "-5"

    def test_leaves_ordinary_copy_alone(self):
        original = "Search words, idioms and names. Nothing to change here."
        assert sanitise(original) == original

    def test_handles_empty(self):
        assert sanitise("") == ""


class TestCompose:
    def test_applies_the_dash_rules(self):
        text = compose("Title — here", "Body – text", "8–16")
        assert "—" not in text and "–" not in text
        assert "Title, here" in text and "8 to 16" in text

    def test_keeps_html(self):
        assert compose("Word", "<b>bold</b>").startswith("<b>Word</b>")

    def test_parts_are_optional(self):
        assert compose(body="only the body") == "only the body"


class TestEscaping:
    def test_escapes_markup_from_the_database(self):
        assert esc("<script>x</script>") == "&lt;script&gt;x&lt;/script&gt;"

    def test_none_becomes_empty(self):
        assert esc(None) == ""


class TestSplitting:
    def test_short_text_is_one_chunk(self):
        assert split_for_telegram("short") == ["short"]

    def test_long_text_respects_the_limit(self):
        chunks = split_for_telegram("paragraph text\n\n" * 900)
        assert len(chunks) > 1
        assert all(len(chunk) <= 4000 for chunk in chunks)

    def test_nothing_is_lost(self):
        source = "word " * 3000
        assert "".join(split_for_telegram(source)).replace(" ", "") == source.replace(" ", "")


class TestHelpers:
    def test_truncate_adds_an_ellipsis(self):
        assert truncate("abcdefghij", 5).endswith("…")

    def test_truncate_leaves_short_text(self):
        assert truncate("abc", 10) == "abc"

    def test_one_line_collapses_whitespace(self):
        assert one_line("a\n  b\tc") == "a b c"

    def test_plural(self):
        assert plural(1, "entry", "entries") == "1 entry"
        assert plural(3, "entry", "entries") == "3 entries"

    def test_format_date(self):
        assert format_date("2026-04-07T02:07:00+00:00") == "7 Apr 2026"

    def test_format_date_ignores_rubbish(self):
        assert format_date("not a date") == ""
        assert format_date(None) == ""
