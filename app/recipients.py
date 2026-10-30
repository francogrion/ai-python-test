"""Detect and compare the email addresses and phone numbers in a text."""

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w+])\+?\d(?:[ -]?\d){8,14}(?!\w)")


def find_recipients(text: str) -> list[str]:
    """Return the distinct recipients in order of appearance, as written."""
    emails = list(_EMAIL.finditer(text))
    without_emails = _EMAIL.sub(lambda match: " " * len(match.group()), text)
    matches = sorted([*emails, *_PHONE.finditer(without_emails)], key=lambda match: match.start())

    recipients: list[str] = []
    for match in matches:
        if not any(same_recipient(match.group(), known) for known in recipients):
            recipients.append(match.group())
    return recipients


def is_email(recipient: str) -> bool:
    return _EMAIL.fullmatch(recipient) is not None


def same_recipient(first: str, second: str) -> bool:
    if is_email(first) or is_email(second):
        return first.casefold() == second.casefold()
    return _digits(first) == _digits(second)


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone)
