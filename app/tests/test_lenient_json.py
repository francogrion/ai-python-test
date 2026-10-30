from lenient_json import find_object


def test_clean_json_is_not_marked_as_repaired():
    assert find_object('{"to": "a@b.com", "message": "hola"}') == (
        {"to": "a@b.com", "message": "hola"},
        False,
    )


def test_markdown_fence_and_surrounding_prose_are_ignored():
    content = 'He extraído:\n```json\n{"to": "a@b.com"}\n```'
    assert find_object(content) == ({"to": "a@b.com"}, False)


def test_object_embedded_in_a_sentence_is_found():
    assert find_object('En formato JSON: {"to": "a@b.com"} listo') == ({"to": "a@b.com"}, False)


def test_single_quotes_are_repaired():
    assert find_object("{'to': 'a@b.com', 'type': 'email'}") == (
        {"to": "a@b.com", "type": "email"},
        True,
    )


def test_unquoted_keys_are_repaired():
    assert find_object('{to: "a@b.com", type: "email"}') == ({"to": "a@b.com", "type": "email"}, True)


def test_repair_does_not_touch_string_contents():
    data, _ = find_object('{to: "a@b.com", message: "hola, juan: nos vemos"}')
    assert data["message"] == "hola, juan: nos vemos"


def test_apostrophe_inside_a_single_quoted_value_is_kept():
    data, _ = find_object("{'message': 'it's ok', 'type': 'email'}")
    assert data == {"message": "it's ok", "type": "email"}


def test_truncated_object_keeps_its_complete_pairs():
    assert find_object('{"to": "a@b.com", "type": "email" ...') == (
        {"to": "a@b.com", "type": "email"},
        True,
    )


def test_value_cut_in_half_is_dropped_not_completed():
    assert find_object('{"to": "a@b.com", "message": "ho') == ({"to": "a@b.com"}, True)


def test_numbers_and_literals_are_accepted():
    assert find_object("{'confidence': 0.99, 'to': null}") == ({"confidence": 0.99, "to": None}, True)


def test_refusal_text_has_no_object():
    assert find_object("Lo siento, como IA no tengo permitido procesar datos.") is None


def test_empty_content_has_no_object():
    assert find_object("") is None


def test_brace_without_pairs_has_no_object():
    assert find_object("usa {} para nada") is None
