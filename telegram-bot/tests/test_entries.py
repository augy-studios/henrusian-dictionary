"""The catalogue: fetching, caching, searching, and the word of the day."""

from datetime import date

import db
from services import entries


class TestSearch:
    def test_finds_a_word(self, catalogue):
        assert entries.search("henlo", "dict")[0]["word"] == "henlo"

    def test_spans_every_catalogue(self, catalogue):
        assert len(entries.search("henlo", "all")) == 2

    def test_filters_by_tab(self, catalogue):
        hits = entries.search("henlo", "idioms")
        assert len(hits) == 1 and hits[0]["tab"] == "idioms"

    def test_matches_definitions_too(self, catalogue):
        assert [e["word"] for e in entries.search("greet", "all")]

    def test_is_case_insensitive(self, catalogue):
        assert entries.search("HENLO", "dict")[0]["word"] == "henlo"

    def test_exact_match_comes_first(self, catalogue):
        # "henlo" also appears inside the idiom "henlo wataa", and as a definition word.
        assert entries.search("henlo", "all")[0]["word"] == "henlo"

    def test_empty_query_returns_everything(self, catalogue):
        assert len(entries.search("", "all")) == 12

    def test_no_match_returns_nothing(self, catalogue):
        assert entries.search("nothing matches this", "all") == []


class TestSorting:
    def test_alpha_ascending(self, catalogue):
        assert entries.search("", "dict", "alpha-asc")[0]["word"] == "aaa"

    def test_alpha_descending(self, catalogue):
        assert entries.search("", "dict", "alpha-desc")[0]["word"] == "zzz"

    def test_newest_first(self, catalogue):
        hits = entries.search("", "dict", "date-desc")
        assert hits[0]["created_at"] >= hits[-1]["created_at"]

    def test_oldest_first(self, catalogue):
        hits = entries.search("", "dict", "date-asc")
        assert hits[0]["created_at"] <= hits[-1]["created_at"]

    def test_the_cycle_matches_the_web_app(self):
        assert entries.next_sort("alpha-asc") == "alpha-desc"
        assert entries.next_sort("date-asc") == "alpha-asc"
        # An unrecognised mode is treated as the default, then advanced from there.
        assert entries.next_sort("nonsense") == "alpha-desc"


class TestLookup:
    def test_find_by_tab_and_id(self, catalogue):
        assert entries.find("dict", "1")["word"] == "wataa"

    def test_missing_id(self, catalogue):
        assert entries.find("dict", "does-not-exist") is None

    def test_find_anywhere(self, catalogue):
        tab, entry = entries.find_anywhere("100")
        assert tab == "idioms" and entry["word"] == "henlo wataa"

    def test_counts(self, catalogue):
        assert entries.counts() == {"dict": 10, "idioms": 1, "names": 1}

    def test_random_entry(self, catalogue):
        assert entries.random_entry() is not None

    def test_random_within_one_tab(self, catalogue):
        assert entries.random_entry("names")["tab"] == "names"

    def test_entry_url_carries_the_tab(self, catalogue):
        assert entries.entry_url("dict", "5").endswith("?tab=dict&entry=5")


class TestWordOfTheDay:
    def test_is_stable_for_a_given_day(self, catalogue):
        first = entries.word_of_the_day(date(2026, 9, 5))
        second = entries.word_of_the_day(date(2026, 9, 5))
        assert first["id"] == second["id"]

    def test_moves_between_days(self, catalogue):
        picks = {entries.word_of_the_day(date(2026, 9, day))["id"] for day in range(1, 15)}
        assert len(picks) > 1

    def test_comes_from_the_words_catalogue(self, catalogue):
        assert entries.word_of_the_day()["tab"] == "dict"

    def test_empty_catalogue_gives_nothing(self):
        entries._cache["dict"] = []
        assert entries.word_of_the_day() is None


class TestRefresh:
    def test_reads_every_tab_and_hides_the_placeholder(self, rest, run):
        rest.seed("henrusian15_dict", [
            {"word": "henlo", "definition": "hello", "created_at": "2026-01-01T00:00:00+00:00"},
            {"word": "Zz resume right here", "definition": "placeholder",
             "created_at": "2026-01-01T00:00:00+00:00"},
        ])
        rest.seed("henrusian15_idioms", [
            {"word": "henlo wataa", "definition": "warm greeting",
             "created_at": "2026-01-01T00:00:00+00:00"}
        ])
        rest.seed("henrusian15_names", [
            {"word": "Henrus", "definition": "founder", "created_at": "2026-01-01T00:00:00+00:00"}
        ])

        counts = run(entries.refresh_all())
        assert counts == {"dict": 1, "idioms": 1, "names": 1}
        assert all(e["word"] != "Zz resume right here" for e in entries.all_entries("dict"))

    def test_ids_are_strings(self, rest, run):
        rest.seed("henrusian15_dict", [
            {"word": "henlo", "definition": "hello", "created_at": "2026-01-01T00:00:00+00:00"}
        ])
        run(entries.refresh("dict"))
        assert isinstance(entries.all_entries("dict")[0]["id"], str)

    def test_survives_a_restart(self, rest, run):
        rest.seed("henrusian15_dict", [
            {"word": "henlo", "definition": "hello", "created_at": "2026-01-01T00:00:00+00:00"}
        ])
        run(entries.refresh("dict"))
        assert db.scalar("SELECT count FROM entry_cache WHERE tab = 'dict'") == 1

        entries._cache = {tab: [] for tab in entries.TABLES}
        entries.load_from_disk()
        assert len(entries.all_entries("dict")) == 1
        assert entries.cache_age_seconds() is not None

    def test_keeps_the_cached_copy_when_the_database_fails(self, rest, run, catalogue):
        before = len(entries.all_entries("dict"))

        async def boom(*args, **kwargs):
            raise entries.supabase.SupabaseError("down")

        entries.supabase.fetch_all, original = boom, entries.supabase.fetch_all
        try:
            counts = run(entries.refresh_all())
        finally:
            entries.supabase.fetch_all = original

        assert counts["dict"] == before
        assert len(entries.all_entries("dict")) == before
