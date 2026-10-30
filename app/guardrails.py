"""Turn the raw LLM answer into a notification the user's own text can back up.

The model proposes; what the user wrote decides. Each repair is reported so it
can be counted, and anything that cannot be verified is rejected, never guessed.
"""

import re
from dataclasses import dataclass

from lenient_json import find_object
from message_source import AmbiguousBody, source_body, text_after_recipient
from models import Notification
from recipients import find_recipients, is_email, same_recipient

_ALIASES = {
    "to": "to", "recipient": "to", "destination": "to",
    "message": "message", "body": "message", "text": "message",
    "type": "type", "channel": "type", "method": "type",
}


@dataclass(frozen=True)
class Accepted:
    notification: Notification
    repairs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rejected:
    reason: str
    retryable: bool


def check_input(user_input: str) -> Rejected | None:
    """Reject what no model answer could fix, before spending an AI call."""
    if not find_recipients(user_input):
        return Rejected("no_recipient", retryable=False)
    return None


def extract_notification(content: str, user_input: str) -> Accepted | Rejected:
    rejection = check_input(user_input)
    if rejection is not None:
        return rejection

    found = find_object(content)
    if found is None:
        return Rejected("no_json", retryable=True)

    data, was_repaired = found
    repairs = ["json_repaired"] if was_repaired else []
    fields = _normalize_keys(data, repairs)

    recipient = _resolve_recipient(fields.get("to"), user_input, repairs)
    if recipient is None:
        return Rejected("ambiguous_recipient", retryable=True)

    message = _resolve_message(fields.get("message"), _says_no_body(data), user_input, recipient, repairs)
    if isinstance(message, Rejected):
        return message

    if len(find_recipients(_routing_text(user_input, message))) > 1:
        return Rejected("multiple_recipients", retryable=False)

    channel = _resolve_channel(fields.get("type"), recipient, repairs)
    notification = Notification(to=recipient, message=message, type=channel)
    return Accepted(notification, tuple(repairs))


def _normalize_keys(data: dict, repairs: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, value in data.items():
        canonical = _ALIASES.get(key.strip().lower())
        if canonical is None:
            _note(repairs, "dropped_keys")
            continue
        if key != canonical:
            _note(repairs, "key_alias")
        if isinstance(value, str) and value.strip():
            fields.setdefault(canonical, value.strip())
    return fields


def _resolve_recipient(proposed: str | None, user_input: str, repairs: list[str]) -> str | None:
    candidates = find_recipients(user_input)
    if proposed is not None:
        for candidate in candidates:
            if same_recipient(proposed, candidate):
                return candidate
    if len(candidates) == 1:
        repairs.append("recipient_from_input")
        return candidates[0]
    return None


def _says_no_body(data: dict) -> bool:
    return any(_ALIASES.get(key.strip().lower()) == "message" and value is None for key, value in data.items())


def _resolve_message(
    proposed: str | None, no_body: bool, user_input: str, recipient: str, repairs: list[str]
) -> str | Rejected:
    try:
        body = source_body(user_input, recipient)
    except AmbiguousBody:
        return Rejected("ambiguous_message", retryable=False)

    if body is not None:
        if proposed is None or proposed.casefold() != body.casefold():
            repairs.append("message_from_source")
        return body

    if no_body:
        return Rejected("no_body", retryable=False)
    if proposed is None:
        return Rejected("missing_message", retryable=True)

    # With no delimiter a substring proves nothing, since any fragment would pass.
    remainder = text_after_recipient(user_input, recipient)
    if remainder:
        if _without_final_punctuation(proposed) == _without_final_punctuation(remainder):
            return remainder
        return Rejected("message_unverified", retryable=False)

    if proposed.casefold() not in user_input.casefold() or recipient.casefold() in proposed.casefold():
        return Rejected("message_unverified", retryable=False)
    return proposed


def _without_final_punctuation(text: str) -> str:
    return text.rstrip(".!?… ").casefold()


def _routing_text(user_input: str, message: str) -> str:
    """The request without its body: contacts inside the body are content, not addressees."""
    return re.sub(re.escape(message), "", user_input, count=1, flags=re.IGNORECASE)


def _resolve_channel(proposed: str | None, recipient: str, repairs: list[str]) -> str:
    channel = "email" if is_email(recipient) else "sms"
    if proposed is None:
        repairs.append("type_inferred")
    elif proposed.lower() != channel:
        repairs.append("type_corrected")
    return channel


def _note(repairs: list[str], repair: str) -> None:
    if repair not in repairs:
        repairs.append(repair)
