"""The rich message helpers: raw requests first, plain text when Telegram says no."""

from telethon import types
from telethon.tl import functions

from tests.conftest import FakeClient, FakeEvent
from utils.reply import (
    edit_rich_message, edit_rich_message_at, reply_rich, send_rich_message, sent_message_id,
)
from utils.rich import compose

RICH = compose("Title", "**body**")


class RejectingClient(FakeClient):
    """Telegram refusing the rich payload, so every raw request fails."""

    async def __call__(self, request):
        raise RuntimeError("RICH_MESSAGE_INVALID")


class TestSend:
    def test_the_fallback_goes_in_the_message_field(self, run, client):
        run(send_rich_message(client, 4242, RICH))
        sent = client.sent[-1]
        assert sent["text"] == "Title\n\nbody"
        assert sent["markdown"] == "# Title\n\n**body**"
        assert sent["buttons"] is None

    def test_the_new_message_id_is_reported(self, run, client):
        result = run(send_rich_message(client, 4242, RICH))
        assert sent_message_id(result) == 1

    def test_a_rejected_rich_send_falls_back_to_plain_text(self, run):
        client = RejectingClient()
        result = run(send_rich_message(client, 4242, RICH, buttons=[["b"]]))
        assert client.sent[-1] == {"chat": 4242, "text": "Title\n\nbody", "markdown": None,
                                   "buttons": [["b"]]}
        assert sent_message_id(result) == 1

    def test_reply_rich_targets_the_event_chat(self, run, client):
        ev = FakeEvent(sender_id=7, chat_id=99, client=client)
        run(reply_rich(ev, RICH))
        assert client.sent[-1]["chat"] == 99


class TestEdit:
    def test_a_callback_edit_hits_the_message_it_came_from(self, run, client):
        ev = FakeEvent(sender_id=7, client=client)
        run(edit_rich_message(client, ev, RICH, buttons=[["b"]]))
        assert client.edits[-1]["id"] == ev.message_id
        assert client.edits[-1]["chat"] == ev.chat_id
        assert client.edits[-1]["markdown"] == RICH["markdown"]
        assert client.edits[-1]["buttons"] == [["b"]]

    def test_a_callback_edit_without_buttons_leaves_the_keyboard_alone(self, run, client):
        ev = FakeEvent(sender_id=7, client=client)
        run(edit_rich_message(client, ev, RICH))
        assert client.edits[-1]["buttons"] is None

    def test_editing_by_id_without_buttons_removes_the_keyboard(self, run, client):
        run(edit_rich_message_at(client, 4242, 12, RICH))
        assert client.edits[-1] == {"chat": 4242, "id": 12, "text": "Title\n\nbody",
                                    "markdown": "# Title\n\n**body**",
                                    "buttons": types.ReplyInlineMarkup(rows=[])}

    def test_a_rejected_rich_edit_falls_back(self, run):
        client = RejectingClient()
        ev = FakeEvent(sender_id=7, client=client)
        run(edit_rich_message(client, ev, RICH))
        assert client.edits[-1] == {"chat": ev.chat_id, "id": ev.message_id,
                                    "text": "Title\n\nbody", "markdown": None, "buttons": None}

    def test_an_unchanged_message_is_not_an_error(self, run):
        from telethon.errors import MessageNotModifiedError

        class Unchanged(FakeClient):
            async def __call__(self, request):
                raise MessageNotModifiedError(request)

        client = Unchanged()
        run(edit_rich_message_at(client, 4242, 12, RICH))
        assert client.edits == []


class TestSentMessageId:
    def test_reads_a_short_sent_message(self):
        short = types.UpdateShortSentMessage(id=5, pts=0, pts_count=0, date=None, out=True)
        assert sent_message_id(short) == 5

    def test_reads_a_new_message_update(self):
        message = types.Message(id=9, peer_id=types.PeerUser(user_id=1), date=None, message="")
        updates = types.Updates(
            updates=[types.UpdateNewMessage(message=message, pts=0, pts_count=0)],
            users=[], chats=[], date=None, seq=0,
        )
        assert sent_message_id(updates) == 9

    def test_gives_up_quietly_on_anything_else(self):
        assert sent_message_id(None) is None
        assert sent_message_id(object()) is None


class TestRequestShape:
    def test_the_raw_send_carries_no_parse_mode(self):
        request = functions.messages.SendMessageRequest(
            peer=1, message=RICH["fallback"],
            rich_message=types.InputRichMessageMarkdown(markdown=RICH["markdown"]),
        )
        assert not hasattr(request, "parse_mode")
        assert request.entities is None
