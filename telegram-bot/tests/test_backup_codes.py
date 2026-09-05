"""Backup codes: the format, the approval gate, redemption, and the lockouts."""

import config
import db
from services import backup_codes, linking

TG = 4242
OTHER_TG = 8888


def seed_link(rest, telegram_user_id=TG, device_id="device-abcdef123456"):
    rows = rest.seed(linking.LINKS, [{
        "device_id": device_id,
        "device_secret_hash": "hash",
        "device_label": "Firefox on Linux",
        "telegram_user_id": telegram_user_id,
        "linked_at": "2026-09-05T00:00:00+00:00",
    }])
    db.execute("UPDATE users SET linked = 1 WHERE telegram_user_id = ?", (telegram_user_id,))
    return rows[-1]["id"]


def seed_codes(rest, codes, telegram_user_id=TG):
    rest.seed(backup_codes.TABLE,
              [{"telegram_user_id": telegram_user_id, "code_hash": backup_codes.digest(code)}
               for code in codes])


def seed_request(rest, telegram_user_id=TG, status="pending",
                 expires="2099-01-01T00:00:00+00:00", notified=None,
                 device_label="Firefox on Linux"):
    rows = rest.seed(backup_codes.REQUESTS, [{
        "telegram_user_id": telegram_user_id,
        "device_label": device_label,
        "status": status,
        "requested_at": "2026-09-05T00:00:00+00:00",
        "expires_at": expires,
        "notified_at": notified,
    }])
    return rows[-1]["id"]


class TestFormat:
    def test_twelve_characters_in_three_groups(self):
        raw = backup_codes._raw()
        assert len(raw) == 12
        assert backup_codes.pretty(raw).count("-") == 2
        assert len(backup_codes.pretty(raw)) == 14

    def test_the_alphabet_avoids_ambiguous_letters(self):
        assert not set("ILOU") & set(backup_codes.ALPHABET)

    def test_normalising_accepts_any_reasonable_typing(self):
        target = backup_codes.normalise("ABCDEFGHJKMN")
        for variant in ("abcd-efgh-jkmn", "ABCD EFGH JKMN", "  abcdefghjkmn  ", "abcd_efgh_jkmn"):
            assert backup_codes.normalise(variant) == target

    def test_ambiguous_letters_map_to_digits(self):
        assert backup_codes.normalise("ILOU") == "1101"

    def test_the_digest_is_stable_and_peppered(self):
        assert backup_codes.digest("abcd-efgh-jkmn") == backup_codes.digest("ABCDEFGHJKMN")
        assert len(backup_codes.digest("abcd")) == 64


class TestApprovalRequests:
    def test_pending_requests_are_listed_once(self, rest, run):
        seed_request(rest)
        pending = run(backup_codes.awaiting_notification())
        assert len(pending) == 1

        run(backup_codes.mark_notified(pending[0]["id"]))
        assert run(backup_codes.awaiting_notification()) == []

    def test_expired_requests_are_not_announced(self, rest, run):
        seed_request(rest, expires="2020-01-01T00:00:00+00:00")
        assert run(backup_codes.awaiting_notification()) == []

    def test_approving_claims_it_exactly_once(self, rest, run):
        request_id = seed_request(rest)
        assert run(backup_codes.claim_request(request_id, TG))[0] == "ok"
        assert run(backup_codes.claim_request(request_id, TG))[0] == "settled"

    def test_someone_else_cannot_approve_it(self, rest, run):
        request_id = seed_request(rest)
        reason, _ = run(backup_codes.claim_request(request_id, OTHER_TG))
        assert reason == "missing"
        assert run(backup_codes.get_request(request_id))["status"] == "pending"

    def test_an_expired_request_cannot_be_approved(self, rest, run):
        request_id = seed_request(rest, expires="2020-01-01T00:00:00+00:00")
        reason, _ = run(backup_codes.claim_request(request_id, TG))
        assert reason == "expired"
        assert run(backup_codes.get_request(request_id))["status"] == "expired"

    def test_rejecting_settles_it(self, rest, run):
        request_id = seed_request(rest)
        assert run(backup_codes.reject_request(request_id, TG)) is True
        assert run(backup_codes.get_request(request_id))["status"] == "rejected"
        assert run(backup_codes.claim_request(request_id, TG))[0] == "settled"

    def test_rejecting_twice_reports_nothing_to_do(self, rest, run):
        request_id = seed_request(rest)
        run(backup_codes.reject_request(request_id, TG))
        assert run(backup_codes.reject_request(request_id, TG)) is False

    def test_the_bot_never_creates_codes(self):
        # Creating a set is a website action. Nothing here should be able to mint one.
        assert not hasattr(backup_codes, "generate")


class TestRedemption:
    def test_a_good_code_returns_its_link(self, rest, run, known_user):
        seed_link(rest)
        seed_codes(rest, ["ABCD-EFGH-JKMN"])
        assert run(backup_codes.redeem("abcd-efgh-jkmn", TG)) == TG

    def test_a_code_works_only_once(self, rest, run, known_user):
        seed_link(rest)
        seed_codes(rest, ["ABCD-EFGH-JKMN"])
        run(backup_codes.redeem("ABCD-EFGH-JKMN", TG))
        assert run(backup_codes.redeem("ABCD-EFGH-JKMN", TG)) is None

    def test_an_unknown_code_fails(self, rest, run, known_user):
        seed_link(rest)
        assert run(backup_codes.redeem("ZZZZ-ZZZZ-ZZZZ", TG)) is None

    def test_a_revoked_code_fails(self, rest, run, known_user):
        seed_link(rest)
        seed_codes(rest, ["ABCD-EFGH-JKMN"])
        rest.rows(backup_codes.TABLE)[0]["revoked_at"] = "2026-09-05T00:00:00+00:00"
        assert run(backup_codes.redeem("ABCD-EFGH-JKMN", TG)) is None

    def test_remaining_counts_only_live_codes(self, rest, run):
        seed_link(rest)
        seed_codes(rest, ["AAAA-AAAA-AAAA", "BBBB-BBBB-BBBB", "CCCC-CCCC-CCCC"])
        rest.rows(backup_codes.TABLE)[0]["used_at"] = "2026-09-05T00:00:00+00:00"
        rest.rows(backup_codes.TABLE)[1]["revoked_at"] = "2026-09-05T00:00:00+00:00"
        assert run(backup_codes.remaining(TG)) == 1


class TestLockouts:
    def test_no_lockout_to_begin_with(self, known_user):
        assert backup_codes.locked_out(TG) == 0

    def test_five_failures_lock_this_telegram_account(self, known_user):
        for _ in range(config.RECOVERY_LOCKOUT_ATTEMPTS):
            db.execute(
                "INSERT INTO link_attempts (telegram_user_id, outcome) VALUES (?, 'recover-failed')",
                (TG,),
            )
        assert backup_codes.locked_out(TG) > 0
        assert backup_codes.locked_out(OTHER_TG) == 0

    def test_old_failures_do_not_count(self, known_user):
        for _ in range(config.RECOVERY_LOCKOUT_ATTEMPTS):
            db.execute(
                "INSERT INTO link_attempts (telegram_user_id, outcome, created_at) "
                "VALUES (?, 'recover-failed', '2020-01-01 00:00:00')",
                (TG,),
            )
        assert backup_codes.locked_out(TG) == 0

    def test_a_spent_code_counts_against_the_collection(self, rest, run, known_user):
        """This is what stops a lockout being sidestepped by changing Telegram account."""
        seed_link(rest)
        seed_codes(rest, ["ABCD-EFGH-JKMN"])
        rest.rows(backup_codes.TABLE)[0]["used_at"] = "2026-09-05T00:00:00+00:00"

        for _ in range(config.RECOVERY_LOCKOUT_ATTEMPTS):
            run(backup_codes.redeem("ABCD-EFGH-JKMN", TG))

        assert run(backup_codes.collection_locked_out(TG)) > 0

    def test_a_locked_collection_refuses_a_valid_code(self, rest, run, known_user):
        seed_link(rest)
        seed_codes(rest, ["AAAA-AAAA-AAAA", "BBBB-BBBB-BBBB"])
        rest.rows(backup_codes.TABLE)[0]["used_at"] = "2026-09-05T00:00:00+00:00"

        # Burn through the allowance from several different Telegram accounts.
        for offset in range(config.RECOVERY_LOCKOUT_ATTEMPTS):
            db.touch_user_id(50000 + offset)
            run(backup_codes.redeem("AAAA-AAAA-AAAA", 50000 + offset))

        assert run(backup_codes.collection_locked_out(TG)) > 0
        assert run(backup_codes.redeem("BBBB-BBBB-BBBB", TG)) is None

    def test_an_unattributable_failure_does_not_lock_a_collection(self, rest, run, known_user):
        seed_link(rest)
        for _ in range(config.RECOVERY_LOCKOUT_ATTEMPTS):
            run(backup_codes.redeem("ZZZZ-ZZZZ-ZZZZ", TG))
        assert run(backup_codes.collection_locked_out(TG)) == 0

    def test_attempts_are_written_to_the_shared_log(self, rest, run, known_user):
        seed_link(rest)
        seed_codes(rest, ["ABCD-EFGH-JKMN"])
        run(backup_codes.redeem("ABCD-EFGH-JKMN", TG))
        attempts = rest.rows(backup_codes.ATTEMPTS)
        assert len(attempts) == 1
        assert attempts[0]["succeeded"] is True
        assert attempts[0]["telegram_user_id"] == TG
        assert attempts[0]["by_telegram_user_id"] == TG
        assert attempts[0]["source"] == "bot"
