"""Sending and editing Telegram Rich Messages.

Telethon's send_message and edit_message do not expose the rich_message field, so these
go straight to the TL requests. Every helper takes the same payload,

    rich = {"markdown": <Rich Markdown>, "fallback": <plain text>}

puts the markdown in rich_message and the plain text in the request's mandatory message
field, which is what old clients show and what goes out if Telegram rejects the rich
payload. A rich failure never surfaces: the helpers log why and send the fallback instead.

No parse_mode anywhere in here. The fallback is plain text by contract.
"""

import logging

from telethon import types
from telethon.errors import MessageNotModifiedError
from telethon.tl import functions

log = logging.getLogger("reply")


def _rich_markdown(rich):
    return types.InputRichMessageMarkdown(markdown=rich["markdown"])


# Editing without reply_markup keeps the old keyboard; an empty inline
# keyboard is what actually removes it.
_NO_BUTTONS = types.ReplyInlineMarkup(rows=[])


def sent_message_id(result):
    """Id of the message a raw send created (bot sends come back as Updates)."""
    if isinstance(result, (types.Message, types.UpdateShortSentMessage)):
        return result.id
    for update in getattr(result, "updates", []):
        if isinstance(update, types.UpdateMessageID):
            return update.id
        if isinstance(update, (types.UpdateNewMessage, types.UpdateNewChannelMessage)):
            return update.message.id
    return None


async def send_rich_message(client, entity, rich, buttons=None):
    markup = client.build_reply_markup(buttons) if buttons else None
    try:
        return await client(functions.messages.SendMessageRequest(
            peer=entity, message=rich["fallback"],
            rich_message=_rich_markdown(rich), reply_markup=markup))
    except Exception as err:
        log.warning("[send_rich_message] rich send failed, falling back: %s", err)
        return await client.send_message(entity, rich["fallback"], buttons=buttons)


async def reply_rich(event, rich, buttons=None):
    """send_rich_message aimed at the chat an event came from."""
    return await send_rich_message(event.client, event.chat_id, rich, buttons)


async def edit_rich_message_at(client, peer, msg_id, rich, buttons=None):
    """Edit by chat + message id. No buttons => keyboard removed."""
    markup = client.build_reply_markup(buttons) if buttons else _NO_BUTTONS
    try:
        await client(functions.messages.EditMessageRequest(
            peer=peer, id=msg_id, message=rich["fallback"],
            rich_message=_rich_markdown(rich), reply_markup=markup))
    except MessageNotModifiedError:
        return
    except Exception as err:
        log.warning("[edit_rich_message_at] rich edit failed, falling back: %s", err)
        await client.edit_message(peer, msg_id, text=rich["fallback"], buttons=buttons)


async def edit_rich_message(client, event, rich, buttons=None):
    """Edit the message a CallbackQuery came from — regular chat or inline-mode."""
    markup = client.build_reply_markup(buttons) if buttons else None
    is_inline = isinstance(event.query, types.UpdateInlineBotCallbackQuery)
    try:
        if is_inline:
            await client(functions.messages.EditInlineBotMessageRequest(
                id=event.query.msg_id, message=rich["fallback"],
                rich_message=_rich_markdown(rich), reply_markup=markup))
        else:
            await client(functions.messages.EditMessageRequest(
                peer=event.query.peer, id=event.query.msg_id, message=rich["fallback"],
                rich_message=_rich_markdown(rich), reply_markup=markup))
    except MessageNotModifiedError:
        return
    except Exception as err:
        log.warning("[edit_rich_message] rich edit failed, falling back: %s", err)
        if is_inline:
            await client.edit_message(event.query.msg_id, text=rich["fallback"], buttons=buttons)
        else:
            await client.edit_message(event.query.peer, event.query.msg_id,
                                      text=rich["fallback"], buttons=buttons)
