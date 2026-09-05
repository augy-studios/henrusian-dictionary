"""The command surface, and the guards around it."""

import db
import pytest
from handlers import common
from handlers.common import COMMANDS, botfather_command_block, cmd, track


class TestCommandList:
    def test_no_duplicates(self):
        names = [name for name, _ in COMMANDS]
        assert len(names) == len(set(names))

    def test_the_required_commands_are_present(self):
        names = {name for name, _ in COMMANDS}
        assert {"start", "link", "unlink"} <= names

    def test_no_command_names_the_bot(self):
        for name, description in COMMANDS:
            assert "henrus" not in name.lower()
            assert "hrd" not in name.lower()
            assert "henrusian_bot" not in description.lower()

    def test_the_removed_commands_are_gone(self):
        names = {name for name, _ in COMMANDS}
        for gone in ("search", "word", "idiom", "name", "help", "about", "donate",
                     "quote", "fact", "export", "backupcodes", "linkstatus",
                     "subscribe", "unsubscribe", "favourites", "recover"):
            assert gone not in names

    def test_the_short_names_are_used(self):
        names = {name for name, _ in COMMANDS}
        assert {"sub", "unsub", "favs", "code"} <= names

    def test_descriptions_fit_botfather(self):
        for name, description in COMMANDS:
            assert 1 <= len(name) <= 32
            assert 3 <= len(description) <= 256

    def test_the_botfather_block_matches_the_list(self):
        lines = botfather_command_block().splitlines()
        assert len(lines) == len(COMMANDS)
        for line, (name, description) in zip(lines, COMMANDS):
            assert line == f"{name} - {description}"


class TestPatterns:
    def test_a_bare_command_matches(self):
        assert cmd("link").pattern("/link") is not None

    def test_the_username_suffix_is_stripped(self):
        match = cmd("code").pattern("/code@henrusian_bot 7QK4XM2P")
        assert match and match.group(1) == "7QK4XM2P"

    def test_arguments_are_captured(self):
        match = cmd("code").pattern("/code abcd-efgh-jkmn")
        assert match.group(1) == "abcd-efgh-jkmn"

    def test_multiline_arguments_survive(self):
        match = cmd("broadcast").pattern("/broadcast first line\nsecond line")
        assert "second line" in match.group(1)

    def test_a_longer_command_does_not_match(self):
        assert cmd("link").pattern("/linkstatus") is None

    def test_aliases_work(self):
        pattern = cmd("favs", "favourites", "saved").pattern
        assert pattern("/favs") and pattern("/favourites") and pattern("/saved")

    def test_matching_is_case_insensitive(self):
        assert cmd("link").pattern("/LINK") is not None

    def test_args_of_handles_no_match(self):
        class Bare:
            pattern_match = None

        assert common.args_of(Bare()) == ""


class TestGuards:
    def test_private_only_redirects_a_group(self, run, event):
        calls = []

        @common.private_only
        async def handler(event):
            calls.append(event)

        ev = event(is_private=False)
        run(handler(ev))
        assert calls == []
        assert "private chat" in ev.last_text()

    def test_private_only_lets_a_direct_chat_through(self, run, event):
        calls = []

        @common.private_only
        async def handler(event):
            calls.append(event)

        run(handler(event(is_private=True)))
        assert len(calls) == 1

    def test_owner_only_ignores_everybody_else(self, run, event):
        calls = []

        @common.owner_only
        async def handler(event):
            calls.append(event)

        run(handler(event(sender_id=1234)))
        assert calls == []

    def test_owner_only_allows_the_owner(self, run, event):
        import config

        calls = []

        @common.owner_only
        async def handler(event):
            calls.append(event)

        run(handler(event(sender_id=config.BOT_OWNER_ID)))
        assert len(calls) == 1

    def test_safe_reports_rather_than_raising(self, run, event):
        @common.safe
        async def handler(event):
            raise RuntimeError("boom")

        ev = event()
        run(handler(ev))  # must not raise
        assert "went wrong" in ev.last_text()


class TestTracking:
    def test_a_user_row_is_created_from_the_id_alone(self, event):
        ev = event(sender_id=555)
        ev.sender = None
        row = track(ev)
        assert row is not None and row["telegram_user_id"] == 555

    def test_names_fill_in_when_they_are_known(self, event):
        from tests.conftest import FakeSender

        ev = event(sender_id=556)
        ev.sender = FakeSender(556, "augy", "Augy")
        track(ev)
        assert db.get_user(556)["username"] == "augy"

    def test_a_later_bare_touch_does_not_wipe_the_names(self, event):
        from tests.conftest import FakeSender

        ev = event(sender_id=557)
        ev.sender = FakeSender(557, "augy", "Augy")
        track(ev)

        bare = event(sender_id=557)
        bare.sender = None
        track(bare)
        assert db.get_user(557)["username"] == "augy"

    def test_the_default_timezone_is_applied(self, event):
        import config

        ev = event(sender_id=558)
        ev.sender = None
        assert track(ev)["timezone"] == config.DEFAULT_TIMEZONE

    def test_pending_state_round_trips(self):
        db.touch_user_id(559)
        db.set_pending(559, {"kind": "code"})
        assert db.get_pending(559) == {"kind": "code"}
        db.set_pending(559, None)
        assert db.get_pending(559) is None
