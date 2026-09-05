"""The SQLite job queue."""

import db
from services import scheduler


class TestClaiming:
    def test_a_due_job_is_claimed(self):
        scheduler.enqueue("refresh_entries", {}, delay_seconds=-5, dedupe_key="t1")
        claimed = scheduler._claim_due()
        assert [row["kind"] for row in claimed] == ["refresh_entries"]

    def test_a_claimed_job_is_not_handed_out_twice(self):
        scheduler.enqueue("refresh_entries", {}, delay_seconds=-5, dedupe_key="t1")
        scheduler._claim_due()
        assert scheduler._claim_due() == []

    def test_a_future_job_waits(self):
        scheduler.enqueue("refresh_entries", {}, delay_seconds=3600, dedupe_key="later")
        assert scheduler._claim_due() == []

    def test_a_stale_lock_is_reclaimed(self):
        scheduler.enqueue("refresh_entries", {}, delay_seconds=-5, dedupe_key="t1")
        scheduler._claim_due()
        # A crash mid job leaves the lock behind.
        db.execute("UPDATE jobs SET locked_at = '2020-01-01 00:00:00'")
        assert len(scheduler._claim_due()) == 1


class TestDeduplication:
    def test_the_same_key_updates_rather_than_duplicates(self):
        scheduler.enqueue("daily_wotd", {"chat_id": 1}, delay_seconds=60, dedupe_key="wotd:1")
        scheduler.enqueue("daily_wotd", {"chat_id": 1}, delay_seconds=120, dedupe_key="wotd:1")
        assert db.scalar("SELECT COUNT(*) FROM jobs WHERE dedupe_key = 'wotd:1'") == 1

    def test_recurring_registration_is_idempotent(self):
        scheduler.ensure_recurring("prune_cache", 3600)
        scheduler.ensure_recurring("prune_cache", 3600)
        assert db.scalar("SELECT COUNT(*) FROM jobs WHERE kind = 'prune_cache'") == 1

    def test_cancel_removes_the_row(self):
        scheduler.enqueue("daily_wotd", {}, dedupe_key="wotd:9")
        scheduler.cancel("wotd:9")
        assert db.scalar("SELECT COUNT(*) FROM jobs WHERE dedupe_key = 'wotd:9'") == 0

    def test_pending_count(self):
        scheduler.enqueue("prune_cache", {}, dedupe_key="a")
        scheduler.enqueue("prune_cache", {}, dedupe_key="b")
        assert scheduler.pending_count() == 2


class TestRunning:
    def test_a_one_off_job_is_deleted_after_it_runs(self, run, client):
        seen = []

        async def handler(_client, payload):
            seen.append(payload)

        scheduler._kinds["test_once"] = handler
        scheduler._client = client
        try:
            scheduler.enqueue("test_once", {"x": 1}, delay_seconds=-1, dedupe_key="once")
            row = scheduler._claim_due()[0]
            run(scheduler._run(row))
        finally:
            del scheduler._kinds["test_once"]

        assert seen == [{"x": 1}]
        assert db.scalar("SELECT COUNT(*) FROM jobs WHERE dedupe_key = 'once'") == 0

    def test_a_repeating_job_is_rescheduled(self, run, client):
        async def handler(_client, payload):
            return None

        scheduler._kinds["test_repeat"] = handler
        scheduler._client = client
        try:
            scheduler.enqueue("test_repeat", {}, delay_seconds=-1, interval_s=60,
                              dedupe_key="repeat")
            row = scheduler._claim_due()[0]
            run(scheduler._run(row))
        finally:
            del scheduler._kinds["test_repeat"]

        remaining = db.one("SELECT run_at, locked_at FROM jobs WHERE dedupe_key = 'repeat'")
        assert remaining is not None
        assert remaining["locked_at"] is None
        assert db.from_iso(remaining["run_at"]) > db.now()

    def test_a_failure_backs_off_then_gives_up(self, run, client):
        async def handler(_client, payload):
            raise RuntimeError("nope")

        scheduler._kinds["test_fail"] = handler
        scheduler._client = client
        try:
            scheduler.enqueue("test_fail", {}, delay_seconds=-1, dedupe_key="fail")
            for _ in range(scheduler.MAX_ATTEMPTS):
                db.execute("UPDATE jobs SET run_at = '2020-01-01 00:00:00', locked_at = NULL")
                rows = scheduler._claim_due()
                if not rows:
                    break
                run(scheduler._run(rows[0]))
        finally:
            del scheduler._kinds["test_fail"]

        row = db.one("SELECT status, attempts, last_error FROM jobs WHERE dedupe_key = 'fail'")
        assert row["status"] == "failed"
        assert row["attempts"] == scheduler.MAX_ATTEMPTS
        assert "nope" in row["last_error"]

    def test_an_unknown_kind_is_marked_failed_rather_than_crashing(self, run, client):
        scheduler._client = client
        db.execute(
            "INSERT INTO jobs (kind, payload, run_at) VALUES ('does_not_exist', '{}', ?)",
            (db.to_iso(db.now()),),
        )
        row = scheduler._claim_due()[0]
        run(scheduler._run(row))
        assert db.scalar("SELECT status FROM jobs WHERE kind = 'does_not_exist'") == "failed"
