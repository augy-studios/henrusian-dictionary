"""The handlers, driven through the same paths Telegram would take."""

import re

import db
from handlers import linking as linking_handlers
from handlers import views
from services import backup_codes, buttons, favourites, linking
from tests.conftest import FakeEvent
from tests.test_backup_codes import seed_codes, seed_request
from tests.test_linking import DEVICE, SECOND_DEVICE, seed_token

TG = 4242


def fire(run, action, event, params=None):
    handler = buttons.handler_for(action)
    assert handler is not None, f"no handler for {action}"
    return run(handler(event, params or {}))


class TestStartToken:
    def test_a_deep_link_token_completes_the_pairing(self, rest, run, event, known_user, catalogue):
        seed_token(rest, favourites_payload=[{"tab": "dict", "id": "1"}])
        ev = event(sender_id=TG)

        assert run(linking_handlers.complete_link(ev, "7QK4XM2P")) is True
        assert "Paired" in ev.last_text()
        assert linking.cached_linked(TG) is True
        assert run(favourites.ids_for(TG)) == {("dict", "1")}

    def test_the_reply_reports_what_was_merged(self, rest, run, event, known_user, catalogue):
        run(favourites.toggle(TG, "names", "200"))
        seed_token(rest, favourites_payload=[{"tab": "dict", "id": "1"}])
        ev = event(sender_id=TG)
        run(linking_handlers.complete_link(ev, "7QK4XM2P"))

        text = ev.last_text()
        assert "Merged" in text and "2 in total" in text

    def test_a_second_browser_says_how_many_are_paired(self, rest, run, event, known_user,
                                                       catalogue):
        seed_token(rest)
        run(linking_handlers.complete_link(event(sender_id=TG), "7QK4XM2P"))

        seed_token(rest, token="AAAA1111", device_id=SECOND_DEVICE, label="Chrome on Android")
        ev = event(sender_id=TG)
        run(linking_handlers.complete_link(ev, "AAAA1111"))

        assert "2 browsers now share" in ev.last_text()

    def test_an_expired_token_explains_itself(self, rest, run, event, known_user):
        seed_token(rest, expires="2020-01-01T00:00:00+00:00")
        ev = event(sender_id=TG)

        assert run(linking_handlers.complete_link(ev, "7QK4XM2P")) is False
        assert "expired" in ev.last_text().lower()
        assert db.scalar("SELECT outcome FROM link_attempts") == "link-failed"


class TestCodeCommand:
    def test_eight_characters_is_treated_as_a_pairing_token(self, rest, run, event, known_user):
        seed_token(rest)
        ev = event(sender_id=TG)
        run(linking_handlers.redeem_any(ev, "7qk4xm2p"))
        assert "Paired" in ev.last_text()

    def test_twelve_characters_moves_a_collection(self, rest, run, event, known_user, catalogue):
        # Another Telegram account holds the collection, and this one has the code.
        db.touch_user_id(9999)
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", 9999, "old"))
        run(favourites.merge_on_link(9999, [{"tab": "dict", "id": "1"}]))
        seed_codes(rest, ["ABCD-EFGH-JKMN"], telegram_user_id=9999)

        ev = event(sender_id=TG)
        run(linking_handlers.redeem_any(ev, "abcd-efgh-jkmn"))

        assert any("Recovered" in message["text"] for message in ev.client.sent)
        assert len(run(linking.linked_devices(TG))) == 1
        assert run(linking.linked_devices(9999)) == []
        assert run(favourites.shared_ids(TG)) == {("dict", "1")}

    def test_the_previous_holder_is_told(self, rest, run, event, known_user, catalogue):
        db.touch_user_id(9999)
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", 9999, "old"))
        seed_codes(rest, ["ABCD-EFGH-JKMN"], telegram_user_id=9999)

        ev = event(sender_id=TG)
        run(linking_handlers.redeem_any(ev, "ABCD-EFGH-JKMN"))
        assert 9999 in [message["chat"] for message in ev.client.sent]

    def test_the_codes_travel_with_the_collection(self, rest, run, event, known_user, catalogue):
        db.touch_user_id(9999)
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", 9999, "old"))
        seed_codes(rest, ["ABCD-EFGH-JKMN", "BBBB-BBBB-BBBB"], telegram_user_id=9999)

        ev = event(sender_id=TG)
        run(linking_handlers.redeem_any(ev, "ABCD-EFGH-JKMN"))

        assert run(backup_codes.remaining(TG)) == 1
        assert run(backup_codes.remaining(9999)) == 0

    def test_using_your_own_code_says_so(self, rest, run, event, known_user, catalogue):
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", TG, "augy"))
        seed_codes(rest, ["ABCD-EFGH-JKMN"], telegram_user_id=TG)

        ev = event(sender_id=TG)
        run(linking_handlers.redeem_any(ev, "ABCD-EFGH-JKMN"))
        assert "Nothing to move" in ev.last_text()

    def test_a_wrong_length_is_explained(self, run, event, known_user):
        ev = event(sender_id=TG)
        run(linking_handlers.redeem_any(ev, "abc"))
        assert "does not look like a code" in ev.last_text()

    def test_a_locked_account_is_refused_early(self, rest, run, event, known_user):
        for _ in range(5):
            db.execute(
                "INSERT INTO link_attempts (telegram_user_id, outcome) VALUES (?, 'recover-failed')",
                (TG,),
            )
        ev = event(sender_id=TG)
        run(linking_handlers.redeem_any(ev, "7QK4XM2P"))
        assert "Too many attempts" in ev.last_text()
        assert rest.calls == []


class TestStatus:
    def test_nothing_paired_explains_how_to_pair(self, rest, run, known_user):
        title, body, rows = run(linking_handlers.status_body(TG))
        assert title == "Not paired"
        assert "Sync with Telegram" in body

    def test_one_browser_is_reported_in_the_singular(self, rest, run, known_user, catalogue):
        seed_token(rest)
        run(linking.claim_token("7QK4XM2P", TG, "augy"))
        run(favourites.merge_on_link(TG, [{"tab": "dict", "id": "1"}]))

        title, body, rows = run(linking_handlers.status_body(TG))
        assert title == "Paired"
        assert "One browser is" in body
        assert "- Firefox on Linux" in body
        assert "| Saved entries | 1 |" in body

    def test_several_browsers_are_listed(self, rest, run, known_user, catalogue):
        seed_token(rest, label="Firefox on Linux")
        run(linking.claim_token("7QK4XM2P", TG, "augy"))
        seed_token(rest, token="AAAA1111", device_id=SECOND_DEVICE, label="Chrome on Android")
        run(linking.claim_token("AAAA1111", TG, "augy"))

        _, body, _ = run(linking_handlers.status_body(TG))
        assert "2 browsers are" in body
        assert "Firefox on Linux" in body and "Chrome on Android" in body


class TestUnlink:
    def test_removing_one_of_two_keeps_the_collection(self, rest, run, event, known_user,
                                                      catalogue):
        seed_token(rest, favourites_payload=[{"tab": "dict", "id": "1"}])
        run(linking_handlers.complete_link(event(sender_id=TG), "7QK4XM2P"))
        seed_token(rest, token="AAAA1111", device_id=SECOND_DEVICE, label="Chrome on Android")
        ev = event(sender_id=TG)
        run(linking_handlers.complete_link(ev, "AAAA1111"))

        second = run(linking.linked_devices(TG))[0]
        ev2 = event(sender_id=TG)
        fire(run, "unlink:one", ev2, {"id": second["id"]})

        assert "still paired" in ev2.edited
        assert run(favourites.shared_ids(TG)) == {("dict", "1")}
        assert favourites.local_ids(TG) == set()

    def test_removing_the_last_one_keeps_a_local_copy(self, rest, run, event, known_user,
                                                     catalogue):
        seed_token(rest, favourites_payload=[{"tab": "dict", "id": "1"},
                                            {"tab": "names", "id": "200"}])
        ev = event(sender_id=TG)
        run(linking_handlers.complete_link(ev, "7QK4XM2P"))
        only = run(linking.linked_devices(TG))[0]

        ev2 = event(sender_id=TG)
        fire(run, "unlink:one", ev2, {"id": only["id"]})

        assert "last one" in ev2.edited
        assert favourites.local_ids(TG) == {("dict", "1"), ("names", "200")}
        assert rest.rows(favourites.TABLE) == []
        assert linking.cached_linked(TG) is False

    def test_removing_all_of_them(self, rest, run, event, known_user, catalogue):
        seed_token(rest, favourites_payload=[{"tab": "dict", "id": "1"}])
        run(linking_handlers.complete_link(event(sender_id=TG), "7QK4XM2P"))
        seed_token(rest, token="AAAA1111", device_id=SECOND_DEVICE)
        run(linking_handlers.complete_link(event(sender_id=TG), "AAAA1111"))

        ev = event(sender_id=TG)
        fire(run, "unlink:all", ev)

        assert "2 browsers are no longer sharing" in ev.edited
        assert favourites.local_ids(TG) == {("dict", "1")}
        assert run(linking.linked_devices(TG)) == []

    def test_declining_changes_nothing(self, rest, run, event, known_user, catalogue):
        seed_token(rest)
        run(linking_handlers.complete_link(event(sender_id=TG), "7QK4XM2P"))

        ev = event(sender_id=TG)
        fire(run, "unlink:no", ev)
        assert ev.answered == "Nothing changed"
        assert len(run(linking.linked_devices(TG))) == 1

    def test_the_prompt_lists_every_browser(self, rest, run, known_user):
        seed_token(rest, label="Firefox on Linux")
        run(linking.claim_token("7QK4XM2P", TG, "augy"))
        seed_token(rest, token="AAAA1111", device_id=SECOND_DEVICE, label="Chrome on Android")
        run(linking.claim_token("AAAA1111", TG, "augy"))

        devices = run(linking.linked_devices(TG))
        pack = run(linking_handlers.unlink_prompt(TG, TG, devices))
        labels = [button.text for row in pack["buttons"] for button in row]
        assert "Firefox on Linux" in labels
        assert "Chrome on Android" in labels
        assert "All 2 browsers" in labels


class TestLinkSweep:
    def test_the_last_pairing_going_is_noticed(self, rest, run, client, known_user, catalogue):
        seed_token(rest, favourites_payload=[{"tab": "dict", "id": "1"}])
        run(linking_handlers.complete_link(FakeEvent(sender_id=TG, client=client), "7QK4XM2P"))

        # The website revokes the row and leaves the rest to the bot.
        rest.rows(linking.LINKS)[0]["revoked_at"] = "2026-09-05T01:00:00+00:00"
        run(linking_handlers.link_sweep(client, {}))

        assert linking.cached_linked(TG) is False
        assert favourites.local_ids(TG) == {("dict", "1")}
        assert rest.rows(favourites.TABLE) == []
        assert any("last pairing was removed" in m["text"] for m in client.sent)

    def test_one_of_two_going_is_left_alone(self, rest, run, client, known_user, catalogue):
        seed_token(rest)
        run(linking_handlers.complete_link(FakeEvent(sender_id=TG, client=client), "7QK4XM2P"))
        seed_token(rest, token="AAAA1111", device_id=SECOND_DEVICE)
        run(linking_handlers.complete_link(FakeEvent(sender_id=TG, client=client), "AAAA1111"))

        rest.rows(linking.LINKS)[0]["revoked_at"] = "2026-09-05T01:00:00+00:00"
        before = len(client.sent)
        run(linking_handlers.link_sweep(client, {}))

        assert linking.cached_linked(TG) is True
        assert len(client.sent) == before

    def test_a_live_pairing_is_left_alone(self, rest, run, client, known_user, catalogue):
        seed_token(rest)
        run(linking_handlers.complete_link(FakeEvent(sender_id=TG, client=client), "7QK4XM2P"))
        run(linking_handlers.link_sweep(client, {}))
        assert linking.cached_linked(TG) is True


class TestCodeApproval:
    def test_approving_points_back_at_the_website(self, rest, run, event, known_user):
        request_id = seed_request(rest)
        ev = event(sender_id=TG)
        fire(run, "codes:approve", ev, {"r": request_id})

        assert ev.answered == "Approved"
        assert "browser that asked" in ev.edited
        assert run(backup_codes.get_request(request_id))["status"] == "approved"

    def test_the_bot_never_shows_a_code(self, rest, run, event, known_user):
        request_id = seed_request(rest)
        ev = event(sender_id=TG)
        fire(run, "codes:approve", ev, {"r": request_id})
        assert re.search(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}\b", ev.edited) is None
        assert re.search(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}\b", ev.edited_markdown) is None

    def test_rejecting_says_nothing_changed(self, rest, run, event, known_user):
        request_id = seed_request(rest)
        ev = event(sender_id=TG)
        fire(run, "codes:reject", ev, {"r": request_id})
        assert "No codes were created" in ev.edited
        assert "# Request rejected" in ev.edited_markdown

    def test_rejecting_twice_drops_the_stale_buttons(self, rest, run, event, known_user):
        from telethon import types

        request_id = seed_request(rest)
        fire(run, "codes:reject", event(sender_id=TG), {"r": request_id})
        ev = event(sender_id=TG)
        fire(run, "codes:reject", ev, {"r": request_id})
        assert "Nothing to reject" in ev.edited
        # An empty inline keyboard is what removes the old one; None would keep it.
        assert ev.edited_buttons == types.ReplyInlineMarkup(rows=[])

    def test_a_stranger_cannot_approve(self, rest, run, event, known_user):
        request_id = seed_request(rest)
        ev = event(sender_id=7777)
        fire(run, "codes:approve", ev, {"r": request_id})
        assert ev.alerted is True
        assert run(backup_codes.get_request(request_id))["status"] == "pending"


class TestCodeRequestPoll:
    def test_a_pending_request_is_announced_once(self, rest, run, client, known_user):
        seed_codes(rest, ["AAAA-AAAA-AAAA"])
        seed_request(rest, device_label="Chrome on Android")

        run(linking_handlers.code_request_poll(client, {}))
        assert len(client.sent) == 1
        text = client.sent[0]["text"]
        assert "Approve new recovery codes" in text
        assert "Chrome on Android" in text
        assert "replaces the 1 unused code" in text
        assert client.sent[0]["markdown"].startswith("# Approve new recovery codes")

        run(linking_handlers.code_request_poll(client, {}))
        assert len(client.sent) == 1

    def test_the_notification_carries_both_choices(self, rest, run, client, known_user):
        seed_request(rest)
        run(linking_handlers.code_request_poll(client, {}))
        assert len(client.sent[0]["buttons"]) == 2


class TestFavouriteButtons:
    def test_starring_from_a_result_updates_the_view(self, rest, run, event, known_user, catalogue):
        ev = event(sender_id=TG)
        fire(run, "fav:toggle", ev, {"tab": "dict", "id": "1", "back": {"v": "home"}})
        assert ev.answered == "Saved"
        assert ("dict", "1") in favourites.local_ids(TG)

        ev2 = event(sender_id=TG)
        fire(run, "fav:toggle", ev2, {"tab": "dict", "id": "1", "back": {"v": "home"}})
        assert ev2.answered == "Removed from your favourites"
        assert favourites.local_ids(TG) == set()

    def test_removing_from_the_list_refreshes_it(self, rest, run, event, known_user, catalogue):
        run(favourites.toggle(TG, "dict", "1"))
        ev = event(sender_id=TG)
        fire(run, "fav:remove", ev, {"tab": "dict", "id": "1", "p": 0})
        assert favourites.local_ids(TG) == set()
        assert "not saved anything yet" in ev.edited


class TestPendingFlow:
    def test_a_code_sent_as_plain_text_is_handled(self, rest, run, event, known_user):
        seed_token(rest)
        db.set_pending(TG, {"kind": "code"})

        ev = event(sender_id=TG, text="7QK4XM2P")
        run(linking_handlers.pending_code(ev, {"kind": "code"}))

        assert db.get_pending(TG) is None
        assert "Paired" in ev.last_text()


class TestViews:
    def test_the_home_view_lists_every_command(self, rest, known_user):
        from handlers.common import COMMANDS

        pack = views.home_view(TG, TG, first_name="Augy", linked=False)
        for name, _ in COMMANDS:
            assert f"- **/{name}**" in pack["rich"]["markdown"]
            assert f"/{name}" in pack["rich"]["fallback"]

    def test_the_home_view_says_what_the_project_is(self, known_user):
        pack = views.home_view(TG, TG)
        markdown = pack["rich"]["markdown"]
        assert markdown.startswith("# Henrusian Dictionary")
        assert "## Commands" in markdown and "MIT" in markdown

    def test_the_home_view_offers_the_donation_link(self, known_user):
        pack = views.home_view(TG, TG)
        assert pack["buttons"] is not None

    def test_a_random_entry_offers_another(self, run, known_user, catalogue):
        pack = run(views.entry_view(TG, TG, tab="dict", entry_id="1",
                                   back={"v": "random", "tab": "all"}))
        labels = [button.text for row in pack["buttons"] for button in row]
        assert "Another random" in labels

    def test_an_entry_is_headed_by_its_word(self, run, known_user, catalogue):
        pack = run(views.entry_view(TG, TG, tab="dict", entry_id="1"))
        assert pack["rich"]["markdown"].startswith("# wataa\n")
        assert pack["rich"]["fallback"].startswith("wataa\n")

    def test_a_heading_prefix_is_applied(self, run, known_user, catalogue):
        pack = run(views.entry_view(TG, TG, tab="dict", entry_id="1",
                                   heading_prefix="Word of the day"))
        assert pack["rich"]["markdown"].startswith("# Word of the day: wataa")

    def test_results_stay_within_the_page_size(self, known_user, catalogue):
        import config

        pack = views.results_view(TG, TG, q="", tab="dict", page=0)
        numbered = re.findall(r"^\*\*\d+\. ", pack["rich"]["markdown"], re.MULTILINE)
        assert 0 < len(numbered) <= config.RESULTS_PER_PAGE

    def test_catalogue_text_is_escaped_for_markdown(self, run, known_user, catalogue):
        catalogue._cache["dict"][0]["definition"] = "a *greeting* with_underscores | pipes"
        pack = run(views.entry_view(TG, TG, tab="dict", entry_id="0"))
        assert r"a \*greeting\* with\_underscores \| pipes" in pack["rich"]["markdown"]
        assert "a *greeting* with_underscores | pipes" in pack["rich"]["fallback"]

    def test_outbound_copy_carries_no_dashes(self, run, known_user, catalogue):
        packs = [
            views.home_view(TG, TG, first_name="Augy"),
            views.results_view(TG, TG, q="henlo"),
            views.results_view(TG, TG, q="no such word"),
            run(views.entry_view(TG, TG, tab="dict", entry_id="0")),
            run(views.favourites_view(TG, TG)),
        ]
        for pack in packs:
            for text in pack["rich"].values():
                assert "—" not in text and "–" not in text

    def test_a_sent_view_is_remembered_by_its_message_id(self, run, event, known_user, catalogue):
        ev = event(sender_id=TG)
        run(views.send_view(ev, views.results_view(TG, TG, q="henlo")))
        assert ev.client.sent[-1]["markdown"].startswith("# Search: henlo")
        row = db.one("SELECT view, message_id FROM ui_views WHERE chat_id = ?", (TG,))
        assert row["view"] == "results" and row["message_id"] == len(ev.client.sent)


class TestStructuredScreens:
    def test_stats_is_a_table_with_a_total(self, known_user, catalogue):
        from handlers.search import build_stats

        rich = build_stats()
        assert "| Words | 10 |" in rich["markdown"]
        assert "| Total | 12 |" in rich["markdown"]
        assert "Words: 10" in rich["fallback"] and "Total: 12" in rich["fallback"]

    def test_health_lists_the_counters(self, known_user):
        from handlers.admin import build_health

        rich = build_health()
        assert rich["markdown"].startswith("# Health")
        assert "| Users seen | 1 |" in rich["markdown"]
        assert "Users seen: 1" in rich["fallback"]

    def test_settings_shows_the_timezone(self, known_user):
        from handlers.subscriptions import build_settings

        rich, keyboard = build_settings(TG, TG)
        assert "| Daily word | off |" in rich["markdown"]
        assert "| Timezone | Asia/Singapore |" in rich["markdown"]
        assert keyboard is not None
