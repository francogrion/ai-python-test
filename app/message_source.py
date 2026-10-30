"""Read the message body straight from what the user wrote."""

import re

_CONNECTORS = (
    "diciéndole que", "diciendole que", "diciendo que", "diciéndole", "diciendole", "diciendo",
    "indicando que", "indicando", "avisando que", "avisando", "que diga", "y dile que", "dile que",
    "de que", "con el mensaje", "con el texto", "el mensaje", "saying that", "saying",
    "with the message", "with the text", "un mensaje diciendo que", "un mensaje diciendo",
    "a message saying that", "a message saying", "para decirle que", "para decirles que",
    "para decir que", "para avisarle que", "para avisar que", "to say that", "to say", "that", "que",
)
_ALTERNATIVES = "|".join(sorted(_CONNECTORS, key=len, reverse=True))
_DELIMITER = re.compile(
    rf"\s*[,;–—)-]?\s*(?:(?P<connector>{_ALTERNATIVES})\b\s*(?P<labelled>:)?|:)\s*(?P<body>.+)$",
    re.IGNORECASE | re.DOTALL,
)


class AmbiguousBody(Exception):
    """A colon away from the recipient may start the real body, so the body is unclear."""


def text_after_recipient(user_input: str, recipient: str) -> str:
    """Return everything after the recipient, without the punctuation that separates it."""
    location = re.search(re.escape(recipient), user_input, re.IGNORECASE)
    if location is None:
        return ""
    return user_input[location.end():].lstrip(" \t\r\n,;:.)–—-").rstrip()


def source_body(user_input: str, recipient: str) -> str | None:
    """Return the text after a delimiter next to the recipient, if there is one."""
    location = re.search(re.escape(recipient), user_input, re.IGNORECASE)
    if location is None:
        return None

    match = _DELIMITER.match(user_input, location.end())
    if match is None:
        if re.search(r":\s", user_input[location.end():]):
            raise AmbiguousBody(user_input[location.end():])
        return None

    body = match["body"].strip()
    if match["connector"] and not match["labelled"] and re.search(r":\s", body):
        raise AmbiguousBody(body)
    return body or None
