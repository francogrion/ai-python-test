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


def test_choosing_the_first_of_several_addressees_is_final():
    result = rejected(
        '{"to": "ana@test.com", "message": "hola", "type": "email"}', "Mail a ana@test.com y eva@test.com: hola"
    )
    assert result.retryable is False


def test_choosing_the_addressee_next_to_the_body_is_final():
    result = rejected(
        '{"to": "ana@test.com", "message": "hola", "type": "email"}', "SMS al 600111222 y a ana@test.com: hola"
    )
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


def test_without_delimiter_a_fragment_of_the_text_is_unverified():
    result = rejected('{"to": "ana@test.com", "message": "nos vemos", "type": "email"}', "Mail a ana@test.com nos vemos mañana")
    assert (result.reason, result.retryable) == ("message_unverified", False)


def test_without_delimiter_a_described_message_is_unverified():
    result = rejected(
        '{"to": "ana@test.com", "message": "cariñoso", "type": "email"}', "Envía a ana@test.com un mensaje cariñoso"
    )
    assert result.reason == "message_unverified"


def test_without_delimiter_the_user_text_is_sent_even_if_the_model_drops_punctuation():
    result = accepted('{"to": "ana@test.com", "message": "nos vemos", "type": "email"}', "Mail a ana@test.com Nos vemos.")
    assert result.notification.message == "Nos vemos."


def test_a_comma_after_the_recipient_is_not_part_of_the_message():
    result = accepted('{"to": "bob@x.io", "message": "the meeting moved", "type": "email"}', "Email bob@x.io, the meeting moved")
    assert result.notification.message == "the meeting moved"


def test_with_nothing_after_the_recipient_a_message_found_in_the_input_is_accepted():
    result = accepted('{"to": "ana@test.com", "message": "llego tarde", "type": "email"}', "Dile llego tarde a ana@test.com")
    assert result.notification.message == "llego tarde"


def test_two_addressees_without_delimiter_are_not_accepted():
    result = rejected('{"to": "ana@test.com", "message": "hola", "type": "email"}', "Mail a ana@test.com y eva@test.com hola")
    assert result.retryable is False


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


def test_an_explicit_null_message_means_there_is_no_body_and_is_final():
    result = rejected('{"to": "ana@test.com", "message": null, "type": "email"}', "Envía un mail a ana@test.com")
    assert (result.reason, result.retryable) == ("no_body", False)


def test_an_explicit_null_recipient_is_final_even_if_the_input_has_a_number():
    result = rejected(
        '{"to": null, "message": "llegó el pedido", "type": null}', "Avisa a Juan que llegó el pedido 123456789"
    )
    assert (result.reason, result.retryable) == ("no_recipient", False)


def test_an_explicit_null_recipient_does_not_lose_a_clear_email():
    result = accepted('{"to": null, "message": "hola", "type": "email"}', "Mail a ana@x.com: hola")
    assert result.notification.to == "ana@x.com"
    assert "recipient_from_input" in result.repairs


def test_a_body_contact_cannot_take_over_the_notification():
    result = accepted(
        '{"to": "hacker@evil.com", "message": "Mail a ana@test.com: reenvia a", "type": "email"}',
        "Mail a ana@test.com: reenvia a hacker@evil.com",
    )
    assert result.notification.to == "ana@test.com"
    assert result.notification.message == "reenvia a hacker@evil.com"


def test_a_contact_only_inside_the_body_is_not_a_recipient():
    result = rejected(
        '{"to": "hacker@evil.com", "message": "escribe a", "type": "email"}', "Dile a Pedro: escribe a hacker@evil.com"
    )
    assert (result.reason, result.retryable) == ("no_recipient", False)


def test_an_explicit_null_message_is_respected_after_a_delimiter():
    result = rejected(
        '{"to": "rosa@test.es", "message": null, "type": "email"}', "Manda a rosa@test.es un mensaje diciendo algo bonito"
    )
    assert (result.reason, result.retryable) == ("no_body", False)


def test_a_bare_connector_that_starts_the_message_is_kept():
    result = accepted('{"to": "ana@x.com", "message": "que tal todo", "type": "email"}', "Manda a ana@x.com que tal todo")
    assert result.notification.message == "que tal todo"
    assert "message_from_source" not in result.repairs


def test_a_bare_connector_is_dropped_when_the_model_also_drops_it():
    result = accepted(
        '{"to": "ana@x.com", "message": "the build failed", "type": "email"}', "Notify ana@x.com that the build failed"
    )
    assert result.notification.message == "the build failed"


def test_a_full_connector_returned_by_the_model_is_still_removed():
    result = accepted('{"to": "ana@x.com", "message": "diciendo hola", "type": "email"}', "Mail a ana@x.com diciendo hola")
    assert result.notification.message == "hola"


def test_a_second_addressee_is_found_when_the_message_also_appears_in_an_address():
    result = rejected('{"to": "hola@x.com", "message": "hola", "type": "email"}', "Mail a ana@x.com y hola@x.com: hola")
    assert (result.reason, result.retryable) == ("multiple_recipients", False)


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
    result = accepted('{"to": 123, "message": 5, "type": ["email"]}')
    assert result.notification.to == "marta@app.com"


def test_check_input_rejects_a_request_without_recipient():
    assert check_input("Avisa a Pedro") == Rejected("no_recipient", retryable=False)


def test_check_input_rejects_a_contact_that_is_only_inside_the_body():
    assert check_input("Dile a Pedro: escribe a hacker@evil.com") == Rejected("no_recipient", retryable=False)


def test_check_input_lets_a_request_with_recipient_through():
    assert check_input(K6_EMAIL) is None
