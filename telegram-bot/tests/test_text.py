"""The copy rules, the Rich Markdown formatters, and the small text helpers."""

from utils.rich import bullets, compose, escape_cell, escape_md, table, to_plain
from utils.text import format_date, one_line, plural, sanitise, truncate


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

    def test_leaves_a_table_rule_alone(self):
        rule = "| --- | --- |"
        assert sanitise(rule) == rule


class TestCompose:
    def test_returns_markdown_and_a_plain_fallback(self):
        rich = compose("Word", "**bold** body", "a footer")
        assert rich["markdown"] == "# Word\n\n**bold** body\n\n*a footer*"
        assert rich["fallback"] == "Word\n\nbold body\n\na footer"

    def test_applies_the_dash_rules_to_both(self):
        rich = compose("Title — here", "Body – text", "8–16")
        for text in rich.values():
            assert "—" not in text and "–" not in text
            assert "Title, here" in text and "8 to 16" in text

    def test_parts_are_optional(self):
        assert compose(body="only the body") == {"markdown": "only the body",
                                                 "fallback": "only the body"}

    def test_the_fallback_is_never_empty_when_there_is_a_title(self):
        assert compose("Just a title")["fallback"] == "Just a title"


class TestEscaping:
    def test_escapes_every_markdown_special(self):
        assert escape_md(r"a*b_c~d`e|f[g]h#i>j=k\l") == r"a\*b\_c\~d\`e\|f\[g\]h\#i\>j\=k\\l"

    def test_none_becomes_empty(self):
        assert escape_md(None) == ""

    def test_numbers_are_accepted(self):
        assert escape_md(12) == "12"

    def test_a_cell_flattens_newlines_and_pipes(self):
        assert escape_cell("one\ntwo | three") == r"one two \| three"


class TestTable:
    def test_the_first_column_is_a_blank_headed_label(self):
        assert table(["Entries"], [["Words", 10]]).splitlines() == [
            "|  | Entries |",
            "| --- | --- |",
            "| Words | 10 |",
        ]

    def test_cells_are_escaped(self):
        assert r"| a\|b | 1 |" in table(["N"], [["a|b", 1]])

    def test_bullets(self):
        assert bullets(["one", "two"]) == "- one\n- two"


class TestToPlain:
    def test_strips_headings_and_emphasis(self):
        assert to_plain("# Title\n\n## Sub\n**b** *i* _i_ ~~s~~ `c`") == "Title\n\nSub\nb i i s c"

    def test_keeps_escaped_characters_literally(self):
        assert to_plain(r"a \*real\* star and 2\*3") == "a *real* star and 2*3"

    def test_a_two_column_table_becomes_key_value_lines(self):
        plain = to_plain(table(["Entries"], [["Words", 10], ["Idioms", 1]]))
        assert plain == "Words: 10\nIdioms: 1"

    def test_a_wider_table_keeps_its_header(self):
        markdown = "|  | Count | Note |\n| --- | --- | --- |\n| A | 1 | x |"
        assert to_plain(markdown) == "Count | Note\nA | 1 | x"

    def test_an_escaped_pipe_in_a_cell_does_not_split_it(self):
        plain = to_plain(table(["N"], [["a|b", 1]]))
        assert plain == "a|b: 1"

    def test_a_link_keeps_its_text(self):
        assert to_plain("see [the site](https://example.test)") == "see the site"


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
