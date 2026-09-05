"""Durable buttons. The whole point is that a token still works after a restart."""

import db
from services import buttons
from services.buttons import act, link


class TestTokens:
    def test_fits_inside_the_callback_limit(self):
        token = buttons._mint("results:page", {"q": "henlo", "p": 3}, 5, 5)
        assert len(token.encode()) <= 64

    def test_resolves_back_to_the_action(self):
        token = buttons._mint("results:page", {"q": "henlo", "p": 3}, 5, 5)
        record = buttons.resolve(token)
        assert record["action"] == "results:page"
        assert record["params"] == {"q": "henlo", "p": 3}

    def test_identical_buttons_reuse_one_row(self):
        first = buttons._mint("results:page", {"q": "a", "p": 1}, 5, 5)
        second = buttons._mint("results:page", {"p": 1, "q": "a"}, 5, 5)
        assert first == second
        assert db.scalar("SELECT COUNT(*) FROM callbacks") == 1

    def test_different_params_get_different_tokens(self):
        first = buttons._mint("results:page", {"p": 1}, 5, 5)
        second = buttons._mint("results:page", {"p": 2}, 5, 5)
        assert first != second

    def test_different_owners_get_different_tokens(self):
        first = buttons._mint("favs:page", {"p": 0}, 1, 1)
        second = buttons._mint("favs:page", {"p": 0}, 2, 2)
        assert first != second

    def test_unknown_token_resolves_to_nothing(self):
        assert buttons.resolve(b"not-a-real-token") is None

    def test_undecodable_token_resolves_to_nothing(self):
        assert buttons.resolve(b"\xff\xfe") is None

    def test_use_is_counted(self):
        token = buttons._mint("noop", {}, 5, 5)
        buttons.resolve(token)
        buttons.resolve(token)
        assert db.scalar("SELECT use_count FROM callbacks WHERE token = ?", (token,)) == 2

    def test_ownership_is_recorded(self):
        token = buttons._mint("noop", {}, 11, 22)
        record = buttons.resolve(token)
        assert record["chat_id"] == 11 and record["user_id"] == 22


class TestDurability:
    def test_a_token_survives_a_reconnect(self):
        token = buttons._mint("entry:open", {"tab": "dict", "id": "1"}, 5, 5)

        db._conn.close()
        db._conn = None
        db.connect()

        record = buttons.resolve(token)
        assert record and record["action"] == "entry:open"
        assert record["params"]["id"] == "1"

    def test_tokens_are_never_expired(self):
        token = buttons._mint("noop", {}, 5, 5)
        db.execute("UPDATE callbacks SET created_at = '2020-01-01 00:00:00' WHERE token = ?",
                   (token,))
        assert buttons.resolve(token) is not None


class TestBuilder:
    def test_builds_url_and_action_rows(self):
        rows = buttons.build(
            [[link("Open", "https://example.test"), act("Next", "results:page", {"p": 1})]],
            chat_id=5, user_id=5,
        )
        assert len(rows) == 1 and len(rows[0]) == 2

    def test_empty_rows_are_dropped(self):
        assert buttons.build([[]], chat_id=5, user_id=5) is None

    def test_rows_stay_within_telegram_limits(self):
        rows = buttons.build(
            [[act(f"b{i}", "noop", {"i": i}) for i in range(4)] for _ in range(3)],
            chat_id=5, user_id=5,
        )
        assert all(len(row) <= 8 for row in rows)


class TestRegistry:
    def test_every_action_has_exactly_one_handler(self):
        # Importing the handler modules registers them.
        import handlers.favourites  # noqa: F401
        import handlers.linking  # noqa: F401
        import handlers.search  # noqa: F401
        import handlers.start  # noqa: F401
        import handlers.subscriptions  # noqa: F401

        registered = buttons.registered_actions()
        assert len(registered) == len(set(registered))
        assert "home:show" in registered
        for name in registered:
            assert buttons.handler_for(name) is not None
