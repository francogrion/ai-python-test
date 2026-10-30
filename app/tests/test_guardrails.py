import pytest

from guardrails import Accepted, Rejected, check_input, extract_notification

K6_EMAIL = "Manda un correo a marta@app.com: Tienes un nuevo mensaje."


def accepted(content, user_input=K6_EMAIL):
    result = extract_notification(content, user_input)
    assert isinstance(result, Accepted), result
    return result


def rejected(content, user_input=K6_EMAIL):
    result = extract_notification(content, user_input)
    assert isinstance(result, Rejected), result
    return result


def test_clean_answer_needs_no_repairs():
    result = accepted('{"to": "marta@app.com", "message": "Tienes un nuevo mensaje.", "type": "email"}')
    assert result.notification.model_dump() == {
        "to": "marta@app.com",
        "message": "Tienes un nuevo mensaje.",
        "type": "email",
    }
    assert result.repairs == ()


@pytest.mark.parametrize(
    "keys",
    [("Recipient", "body", "channel"), ("To", "Message", "Type"), ("destination", "text", "method")],
)
def test_key_aliases_are_normalized(keys):
    to, message, channel = keys
    result = accepted(f'{{"{to}": "marta@app.com", "{message}": "Tienes un nuevo mensaje.", "{channel}": "email"}}')
    assert result.notification.to == "marta@app.com"
    assert "key_alias" in result.repairs


def test_unknown_keys_are_dropped():
    result = accepted(
        '{"to": "marta@app.com", "message": "Tienes un nuevo mensaje.", "type": "email", "confidence": 0.99}'
    )
    assert "dropped_keys" in result.repairs


def test_repaired_json_is_reported():
    result = accepted("{'to': 'marta@app.com', 'message': 'Tienes un nuevo mensaje.', 'type': 'email'}")
    assert "json_repaired" in result.repairs


def test_missing_type_follows_the_recipient():
    result = accepted('{"to": "marta@app.com", "message": "Tienes un nuevo mensaje."}')
    assert result.notification.type == "email"
    assert "type_inferred" in result.repairs


def test_channel_impossible_for_the_recipient_is_corrected():
    result = accepted('{"to": "marta@app.com", "message": "Tienes un nuevo mensaje.", "type": "sms"}')
    assert result.notification.type == "email"
    assert "type_corrected" in result.repairs


def test_phone_recipient_goes_by_sms():
    result = accepted('{"to": "600-111-222", "message": "hola", "type": "sms"}', "SMS al 600-111-222: hola")
    assert result.notification.type == "sms"


def test_missing_recipient_is_taken_from_the_input():
    result = accepted('{"message": "Tienes un nuevo mensaje.", "type": "email"}')
    assert result.notification.to == "marta@app.com"
    assert "recipient_from_input" in result.repairs


def test_invented_recipient_is_replaced_by_the_one_in_the_input():
    result = accepted('{"to": "hacker@evil.com", "message": "Tienes un nuevo mensaje.", "type": "email"}')
    assert result.notification.to == "marta@app.com"
    assert "recipient_from_input" in result.repairs


def test_recipient_is_sent_as_the_user_wrote_it():
    result = accepted('{"to": "ana@test.com", "message": "hola", "type": "email"}', "Mail a Ana@Test.com: hola")
    assert result.notification.to == "Ana@Test.com"


def test_recipient_is_ambiguous_when_several_fit_and_the_model_gives_none():
    result = rejected('{"message": "hola"}', "Mail a ana@test.com y eva@test.com: hola")
    assert (result.reason, result.retryable) == ("ambiguous_recipient", True)


def test_model_choice_among_several_recipients_is_kept():
    result = accepted(
        '{"to": "ana@test.com", "message": "llama a eva@test.com", "type": "email"}',
        "Mail a ana@test.com: llama a eva@test.com",
    )
    assert result.notification.to == "ana@test.com"


@pytest.mark.parametrize(
    "user_input",
    [
        "Mail a ana@test.com y eva@test.com: hola",
        "Mail a ana@test.com y eva@test.com hola",
        "SMS al 600111222 y a ana@test.com: hola",
    ],
)
def test_choosing_one_of_several_addressees_is_final(user_input):
    result = rejected('{"to": "ana@test.com", "message": "hola", "type": "email"}', user_input)
    assert (result.reason, result.retryable) == ("multiple_recipients", False)


def test_the_last_of_several_addressees_is_also_rejected():
    result = rejected(
        '{"to": "eva@test.com", "message": "hola", "type": "email"}',
        "Mail a ana@test.com y eva@test.com: hola",
    )
    assert result.reason == "multiple_recipients"


def test_a_contact_inside_a_body_without_delimiter_is_not_an_addressee():
    result = accepted(
        '{"to": "ana@test.com", "message": "habla con eva@test.com", "type": "email"}',
        "Mail a ana@test.com habla con eva@test.com",
    )
    assert result.notification.to == "ana@test.com"


def test_input_without_recipient_is_final():
    result = rejected('{"to": "x@y.com", "message": "hola"}', "Avisa a Pedro: hola")
    assert (result.reason, result.retryable) == ("no_recipient", False)


def test_source_casing_is_restored_without_counting_as_a_repair():
    result = accepted('{"to": "marta@app.com", "message": "tienes un nuevo mensaje.", "type": "email"}')
    assert result.notification.message == "Tienes un nuevo mensaje."
    assert result.repairs == ()


def test_fragment_of_the_body_is_replaced_by_the_full_body():
    result = accepted(
        '{"to": "699888777", "message": "00", "type": "sms"}',
        "Recordatorio por teléfono al 699888777: cita a las 10:00",
    )
    assert result.notification.message == "cita a las 10:00"
    assert "message_from_source" in result.repairs


def test_command_returned_as_message_is_replaced_by_the_body():
    result = accepted(
        '{"to": "juan@example.com", "message": "enviar email a juan@example.com diciendo que su pa", "type": "email"}',
        "Enviar email a juan@example.com diciendo que su paquete está en camino.",
    )
    assert result.notification.message == "su paquete está en camino."


def test_without_delimiter_a_message_found_in_the_input_is_accepted():
    result = accepted('{"to": "ana@test.com", "message": "nos vemos", "type": "email"}', "Mail a ana@test.com nos vemos")
    assert result.notification.message == "nos vemos"


def test_without_delimiter_the_whole_command_is_unverified():
    result = rejected(
        '{"to": "ana@test.com", "message": "mail a ana@test.com nos vemos", "type": "email"}',
        "Mail a ana@test.com nos vemos",
    )
    assert (result.reason, result.retryable) == ("message_unverified", False)


def test_without_delimiter_an_invented_message_is_unverified():
    result = rejected('{"to": "ana@test.com", "message": "hola", "type": "email"}', "Mail a ana@test.com nos vemos")
    assert (result.reason, result.retryable) == ("message_unverified", False)


def test_without_delimiter_a_missing_message_is_worth_asking_again():
    result = rejected('{"to": "ana@test.com", "type": "email"}', "Mail a ana@test.com nos vemos")
    assert (result.reason, result.retryable) == ("missing_message", True)


def test_ambiguous_body_is_final():
    result = rejected(
        '{"to": "pedro@x.com", "message": "vuelve el lunes", "type": "email"}',
        "Avisa a pedro@x.com que está de vacaciones: vuelve el lunes.",
    )
    assert (result.reason, result.retryable) == ("ambiguous_message", False)


@pytest.mark.parametrize(
    "refusal",
    [
        "Lo siento, como IA no tengo permitido procesar datos de contacto personales.",
        "Refused: Content analysis flagged sensitive information.",
        "",
    ],
)
def test_text_without_json_is_worth_asking_again(refusal):
    result = rejected(refusal)
    assert (result.reason, result.retryable) == ("no_json", True)


def test_non_text_values_are_treated_as_missing():
    result = accepted('{"to": 123, "message": null, "type": ["email"]}')
    assert result.notification.to == "marta@app.com"


def test_check_input_rejects_a_request_without_recipient():
    assert check_input("Avisa a Pedro") == Rejected("no_recipient", retryable=False)


def test_check_input_lets_a_request_with_recipient_through():
    assert check_input(K6_EMAIL) is None
