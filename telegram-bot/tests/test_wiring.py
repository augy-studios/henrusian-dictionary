"""Boot wiring: everything registers, and nothing references a handler that is not there."""

import pathlib
import re

import bot
import db
from services import buttons, scheduler


class TestRegistration:
    def test_every_module_registers(self, client):
        assert bot.HANDLER_MODULES
        for module in bot.HANDLER_MODULES:
            assert hasattr(module, "register")
            module.register(client)
        assert len(getattr(client, "handlers", [])) > 10

    def test_the_callback_dispatcher_registers(self, client):
        bot.register_callbacks(client)
        assert getattr(client, "handlers", [])

    def test_every_job_kind_referenced_is_registered(self, client):
        for module in bot.HANDLER_MODULES:
            module.register(client)
        kinds = set(scheduler.registered_kinds())
        assert {"refresh_entries", "prune_cache", "daily_wotd", "code_request_poll",
                "link_sweep", "broadcast_chunk"} <= kinds

    def test_every_button_action_in_the_source_has_a_handler(self, client):
        for module in bot.HANDLER_MODULES:
            module.register(client)
        registered = set(buttons.registered_actions())

        # Any quoted action-shaped literal in the handler sources counts as a reference,
        # since a label can be built by a call and defeat a narrower pattern.
        referenced = set()
        for path in pathlib.Path("handlers").glob("*.py"):
            source = path.read_text(encoding="utf-8")
            referenced |= set(re.findall(r'"(noop|[a-z]+:[a-z]+)"', source))

        assert referenced - registered == set()
        assert registered - referenced == set()


class TestSeedJobs:
    def test_the_recurring_jobs_are_seeded_once(self):
        bot.seed_jobs()
        bot.seed_jobs()
        kinds = [row["kind"] for row in db.query("SELECT kind FROM jobs ORDER BY kind")]
        assert kinds == ["code_request_poll", "link_sweep", "prune_cache", "refresh_entries"]

    def test_a_missing_daily_job_is_restored(self):
        db.touch_user_id(4242)
        db.execute(
            "INSERT INTO subscriptions (chat_id, user_id, hour, timezone) "
            "VALUES (4242, 4242, 8, 'Asia/Singapore')"
        )
        bot.seed_jobs()
        assert db.one("SELECT 1 FROM jobs WHERE dedupe_key = 'wotd:4242'") is not None

    def test_an_inactive_subscription_is_not_restored(self):
        db.touch_user_id(4242)
        db.execute(
            "INSERT INTO subscriptions (chat_id, user_id, hour, timezone, active) "
            "VALUES (4242, 4242, 8, 'Asia/Singapore', 0)"
        )
        bot.seed_jobs()
        assert db.one("SELECT 1 FROM jobs WHERE dedupe_key = 'wotd:4242'") is None


class TestConfig:
    def test_required_values_are_validated(self):
        import config

        config.verify()  # the test environment sets them, so this must not exit

    def test_the_web_app_url_has_no_trailing_slash(self):
        import config

        assert not config.WEB_APP_URL.endswith("/")

    def test_the_session_and_database_live_under_data(self):
        import config

        assert config.SESSION_PATH.parent.name == "data"


class TestSchema:
    def test_applying_the_schema_twice_is_safe(self):
        db.apply_schema()
        db.apply_schema()
        assert db.get_meta("schema_version") == "1"

    def test_write_ahead_logging_is_on(self):
        assert db.scalar("PRAGMA journal_mode").lower() == "wal"

    def test_the_expected_tables_exist(self):
        rows = db.query("SELECT name FROM sqlite_master WHERE type = 'table'")
        names = {row["name"] for row in rows}
        assert {
            "users", "callbacks", "ui_views", "jobs", "subscriptions", "entry_cache",
            "api_cache", "favourites_local", "ratelimits", "link_attempts", "outbox",
        } <= names

    def test_nothing_sensitive_is_stored_locally(self):
        rows = db.query("SELECT name FROM sqlite_master WHERE type = 'table'")
        names = {row["name"] for row in rows}
        # Code hashes and link records belong in Supabase, not here.
        assert "backup_codes" not in names
        assert "code_requests" not in names
