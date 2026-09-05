"""Pairing browsers with a Telegram account, and the merge that comes with it."""

import db
from services import favourites, linking

TG = 4242
OTHER_TG = 8888
DEVICE = "device-abcdef123456"
SECOND_DEVICE = "device-222222222222"


def seed_token(rest, token="7QK4XM2P", favourites_payload=None,
               expires="2099-01-01T00:00:00+00:00", device_id=DEVICE,
               label="Firefox on Linux"):
    rest.seed(linking.TOKENS, [{
        "token": token,
        "device_id": device_id,
        "device_secret_hash": "hash-of-the-secret",
        "device_label": label,
        "favourites": favourites_payload if favourites_payload is not None else [],
        "expires_at": expires,
    }])
    return token


class TestTokenNormalising:
    def test_accepts_lower_case_and_spaces(self):
        assert linking.normalise_token(" 7qk4 xm2p ") == "7QK4XM2P"

    def test_maps_ambiguous_letters(self):
        assert linking.normalise_token("ILOU1234") == "11011234"


class TestClaimingAToken:
    def test_creates_the_pairing(self, rest, run, known_user):
        seed_token(rest)
        reason, result = run(linking.claim_token("7QK4XM2P", TG, "augy"))

        assert reason == "ok"
        assert result["link"]["device_id"] == DEVICE
        assert result["link"]["telegram_user_id"] == TG
        assert result["first"] is True
        assert linking.cached_linked(TG) is True

    def test_carries_the_browser_favourites(self, rest, run, known_user):
        seed_token(rest, favourites_payload=[{"tab": "dict", "id": "1"}])
        _, result = run(linking.claim_token("7QK4XM2P", TG, "augy"))
        assert result["device_favourites"] == [{"tab": "dict", "id": "1"}]

    def test_a_token_works_only_once(self, rest, run, known_user):
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", TG, "augy"))
        reason, _ = run(linking.claim_token("7QK4XM2P", TG, "augy"))
        assert reason == "unknown"

    def test_an_expired_token_is_refused(self, rest, run, known_user):
        seed_token(rest, expires="2020-01-01T00:00:00+00:00")
        assert run(linking.claim_token("7QK4XM2P", TG, "augy"))[0] == "unknown"

    def test_an_unknown_token_is_refused(self, rest, run, known_user):
        assert run(linking.claim_token("ZZZZZZZZ", TG, "augy"))[0] == "unknown"

    def test_a_malformed_token_is_refused_without_a_query(self, rest, run, known_user):
        assert run(linking.claim_token("nope", TG, "augy"))[0] == "unknown"
        assert rest.calls == []


class TestSeveralBrowsers:
    def test_a_second_browser_joins_rather_than_replacing(self, rest, run, known_user):
        seed_token(rest, device_id=DEVICE, label="Firefox on Linux")
        run(linking.claim_token("7QK4XM2P", TG, "augy"))

        seed_token(rest, token="AAAA1111", device_id=SECOND_DEVICE, label="Chrome on Android")
        reason, result = run(linking.claim_token("AAAA1111", TG, "augy"))

        assert reason == "ok"
        assert result["first"] is False
        assert result["devices"] == 2
        assert len(run(linking.linked_devices(TG))) == 2

    def test_all_browsers_share_one_collection(self, rest, run, known_user):
        seed_token(rest, favourites_payload=[{"tab": "dict", "id": "1"}])
        run(linking.claim_token("7QK4XM2P", TG, "augy"))
        run(favourites.merge_on_link(TG, [{"tab": "dict", "id": "1"}]))

        seed_token(rest, token="AAAA1111", device_id=SECOND_DEVICE,
                   favourites_payload=[{"tab": "names", "id": "200"}])
        _, result = run(linking.claim_token("AAAA1111", TG, "augy"))
        run(favourites.merge_on_link(TG, result["device_favourites"]))

        assert run(favourites.shared_ids(TG)) == {("dict", "1"), ("names", "200")}

    def test_relinking_the_same_browser_replaces_its_own_row(self, rest, run, known_user):
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", TG, "augy"))
        seed_token(rest, token="BBBB2222", device_id=DEVICE)
        run(linking.claim_token("BBBB2222", TG, "augy"))

        assert len(run(linking.linked_devices(TG))) == 1

    def test_a_browser_moves_between_telegram_accounts(self, rest, run, known_user):
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", TG, "augy"))

        db.touch_user_id(OTHER_TG)
        seed_token(rest, token="CCCC3333", device_id=DEVICE)
        run(linking.claim_token("CCCC3333", OTHER_TG, "other"))

        assert run(linking.linked_devices(TG)) == []
        assert len(run(linking.linked_devices(OTHER_TG))) == 1

    def test_removing_one_leaves_the_others(self, rest, run, known_user):
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", TG, "augy"))
        seed_token(rest, token="AAAA1111", device_id=SECOND_DEVICE)
        _, second = run(linking.claim_token("AAAA1111", TG, "augy"))

        removed = run(linking.unlink_device(TG, second["link"]["id"]))
        assert removed["device_id"] == SECOND_DEVICE

        remaining = run(linking.linked_devices(TG))
        assert len(remaining) == 1 and remaining[0]["device_id"] == DEVICE
        assert linking.cached_linked(TG) is True

    def test_removing_the_last_one_clears_the_cache(self, rest, run, known_user):
        seed_token(rest)
        _, result = run(linking.claim_token("7QK4XM2P", TG, "augy"))
        run(linking.unlink_device(TG, result["link"]["id"]))
        assert linking.cached_linked(TG) is False

    def test_unlink_all_removes_every_browser(self, rest, run, known_user):
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", TG, "augy"))
        seed_token(rest, token="AAAA1111", device_id=SECOND_DEVICE)
        run(linking.claim_token("AAAA1111", TG, "augy"))

        assert run(linking.unlink_all(TG)) == 2
        assert run(linking.linked_devices(TG)) == []
        assert linking.cached_linked(TG) is False

    def test_unlink_all_with_nothing_paired(self, rest, run, known_user):
        assert run(linking.unlink_all(TG)) == 0


class TestStatus:
    def test_nothing_paired_reads_as_none(self, rest, run, known_user):
        assert run(linking.get_link(TG)) is None
        assert linking.cached_linked(TG) is False

    def test_describe_names_the_browser_and_the_date(self):
        assert "Firefox on Linux" in linking.describe(
            {"device_label": "Firefox on Linux", "linked_at": "2026-09-05T00:00:00+00:00"}
        )

    def test_describe_copes_with_a_missing_label(self):
        assert linking.describe({}) == "a browser"


class TestMoving:
    def test_the_collection_changes_hands(self, rest, run, known_user):
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", TG, "augy"))
        run(favourites.merge_on_link(TG, [{"tab": "dict", "id": "1"}]))

        db.touch_user_id(OTHER_TG)
        moved = run(linking.move_collection(TG, OTHER_TG, "other"))
        total = run(favourites.move_collection(TG, OTHER_TG))

        assert moved == 1
        assert total == 1
        assert run(linking.linked_devices(TG)) == []
        assert len(run(linking.linked_devices(OTHER_TG))) == 1
        assert run(favourites.shared_ids(OTHER_TG)) == {("dict", "1")}
        assert run(favourites.shared_ids(TG)) == set()

    def test_moving_merges_rather_than_colliding(self, rest, run, known_user):
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", TG, "augy"))
        run(favourites.merge_on_link(TG, [{"tab": "dict", "id": "1"},
                                          {"tab": "names", "id": "200"}]))

        # The receiving account already had one of the same entries.
        db.touch_user_id(OTHER_TG)
        rest.seed(favourites.TABLE, [{"telegram_user_id": OTHER_TG, "tab": "dict", "entry_id": "1"}])

        total = run(favourites.move_collection(TG, OTHER_TG))
        assert total == 2
        assert run(favourites.shared_ids(OTHER_TG)) == {("dict", "1"), ("names", "200")}


class TestMerging:
    def test_union_of_both_sides_with_no_duplicates(self, rest, run, known_user):
        # Saved in the bot before pairing.
        run(favourites.toggle(TG, "dict", "1"))
        run(favourites.toggle(TG, "idioms", "100"))

        seed_token(rest, favourites_payload=[
            {"tab": "dict", "id": "1"},      # the same entry the bot already had
            {"tab": "names", "id": "200"},   # and one only the browser had
        ])
        _, result = run(linking.claim_token("7QK4XM2P", TG, "augy"))
        merged = run(favourites.merge_on_link(TG, result["device_favourites"]))

        assert merged["total"] == 3
        assert merged["from_device"] == 2
        assert merged["from_bot"] == 2
        assert run(favourites.shared_ids(TG)) == {("dict", "1"), ("idioms", "100"),
                                                  ("names", "200")}
        assert len(rest.rows(favourites.TABLE)) == 3

    def test_local_rows_are_cleared_after_merging(self, rest, run, known_user):
        run(favourites.toggle(TG, "dict", "1"))
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", TG, "augy"))
        run(favourites.merge_on_link(TG, []))
        assert favourites.local_ids(TG) == set()

    def test_merging_again_adds_nothing(self, rest, run, known_user):
        seed_token(rest, favourites_payload=[{"tab": "dict", "id": "1"}])
        _, result = run(linking.claim_token("7QK4XM2P", TG, "augy"))
        run(favourites.merge_on_link(TG, result["device_favourites"]))
        again = run(favourites.merge_on_link(TG, result["device_favourites"]))

        assert again["added"] == 0
        assert len(rest.rows(favourites.TABLE)) == 1

    def test_rubbish_from_the_browser_is_ignored(self, rest, run, known_user):
        seed_token(rest, favourites_payload=[
            {"tab": "nonsense", "id": "1"},
            {"tab": "dict"},
            {"id": "2"},
            "not even an object",
            {"tab": "dict", "id": "x" * 200},
            {"tab": "dict", "id": "9"},
        ])
        _, result = run(linking.claim_token("7QK4XM2P", TG, "augy"))
        merged = run(favourites.merge_on_link(TG, result["device_favourites"]))

        assert merged["from_device"] == 1
        assert run(favourites.shared_ids(TG)) == {("dict", "9")}


class TestKeepingACopy:
    def test_the_collection_is_copied_back_before_it_goes(self, rest, run, known_user):
        seed_token(rest, favourites_payload=[{"tab": "dict", "id": "1"},
                                            {"tab": "names", "id": "200"}])
        _, result = run(linking.claim_token("7QK4XM2P", TG, "augy"))
        run(favourites.merge_on_link(TG, result["device_favourites"]))

        kept = run(favourites.keep_local_copy(TG))
        run(favourites.drop_shared(TG))

        assert kept == 2
        assert favourites.local_ids(TG) == {("dict", "1"), ("names", "200")}
        assert rest.rows(favourites.TABLE) == []


class TestSharedToggling:
    def test_a_star_lands_in_the_shared_collection(self, rest, run, known_user):
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", TG, "augy"))

        assert run(favourites.toggle(TG, "dict", "5")) is True
        assert run(favourites.shared_ids(TG)) == {("dict", "5")}
        assert favourites.local_ids(TG) == set()

    def test_unstarring_removes_it_again(self, rest, run, known_user):
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", TG, "augy"))
        run(favourites.toggle(TG, "dict", "5"))

        assert run(favourites.toggle(TG, "dict", "5")) is False
        assert run(favourites.shared_ids(TG)) == set()

    def test_starring_twice_does_not_duplicate(self, rest, run, known_user):
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", TG, "augy"))
        run(favourites.merge_on_link(TG, [{"tab": "dict", "id": "5"}]))
        run(favourites.merge_on_link(TG, [{"tab": "dict", "id": "5"}]))

        assert len(rest.rows(favourites.TABLE)) == 1
