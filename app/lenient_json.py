"""Find a JSON object inside noisy LLM text, tolerating common malformations."""

import json
import re
from typing import Any

_KEY = re.compile(r"""\s*(?:"([^"]*)"|'([^']*)'|([A-Za-z_]\w*))\s*:\s*""")
_BARE_VALUE = re.compile(r"[^,}\s]+")


def find_object(content: str) -> tuple[dict[str, Any], bool] | None:
    """Return the first non-empty object and whether it needed repairing."""
    starts = [match.start() for match in re.finditer(r"\{", content)]

    decoder = json.JSONDecoder()
    for start in starts:
        try:
            value, _ = decoder.raw_decode(content, start)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value:
            return value, False

    for start in starts:
        pairs = _read_pairs(content, start + 1)
        if pairs:
            return pairs, True
    return None


def _read_pairs(text: str, position: int) -> dict[str, Any]:
    """Read flat key/value pairs, stopping at the first thing that is not one.

    Works on tokens rather than rewriting the text, so string contents stay
    untouched. A value cut in half is dropped, never completed.
    """
    pairs: dict[str, Any] = {}
    while True:
        key = _KEY.match(text, position)
        if key is None:
            return pairs
        value = _read_value(text, key.end())
        if value is None:
            return pairs
        pairs[next(group for group in key.groups() if group is not None)], position = value

        position = _skip_spaces(text, position)
        if text[position:position + 1] != ",":
            return pairs
        position += 1


def _read_value(text: str, position: int) -> tuple[Any, int] | None:
    if text[position:position + 1] in ('"', "'"):
        return _read_string(text, position)

    bare = _BARE_VALUE.match(text, position)
    if bare is None:
        return None
    try:
        return json.loads(bare.group()), bare.end()
    except json.JSONDecodeError:
        return None


def _read_string(text: str, position: int) -> tuple[str, int] | None:
    quote = text[position]
    for match in re.finditer(quote, text[position + 1:]):
        end = position + 1 + match.start()
        if text[end - 1] == "\\":
            continue
        # A quote only closes the string when a delimiter follows it, so an
        # apostrophe inside a single-quoted value is kept.
        next_position = _skip_spaces(text, end + 1)
        if next_position == len(text) or text[next_position] in ",}.":
            return _decode(text[position + 1:end], quote), end + 1
    return None


def _decode(raw: str, quote: str) -> str:
    if quote == "'":
        return raw
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw


def _skip_spaces(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position
