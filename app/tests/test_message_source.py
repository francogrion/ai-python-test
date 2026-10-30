import pytest

from message_source import AmbiguousBody, source_body


@pytest.mark.parametrize(
    ("user_input", "recipient", "body"),
    [
        ("Manda un correo a marta@app.com: Tienes un nuevo mensaje.", "marta@app.com", "Tienes un nuevo mensaje."),
        ("Recordatorio por teléfono al 699888777: cita a las 10:00", "699888777", "cita a las 10:00"),
        ("Enviar email a juan@example.com diciendo que su paquete está en camino.", "juan@example.com", "su paquete está en camino."),
        ("Avisar por SMS al 600-111-222 que la reserva ha sido confirmada.", "600-111-222", "la reserva ha sido confirmada."),
        ("Manda un mail a feda@test.com diciendo hola", "feda@test.com", "hola"),
        ("Correo para marta@domain.es indicando que ya puede recogerlo", "marta@domain.es", "ya puede recogerlo"),
        ("Send an email to ana@test.com saying that the report is ready", "ana@test.com", "the report is ready"),
        ("Escribe a ana@test.com, diciendo: hola", "ana@test.com", "hola"),
        ("SMS a 600111222 con el mensaje: tu pedido salió", "600111222", "tu pedido salió"),
        ("Notify ana@test.com that the build failed", "ana@test.com", "the build failed"),
        ("Send bob@x.io a message saying hello", "bob@x.io", "hello"),
        ("Manda a ana@test.com un mensaje diciendo que llego tarde", "ana@test.com", "llego tarde"),
        ("Recuérdale a Juan (600111222) que traiga el DNI", "600111222", "traiga el DNI"),
        ("Manda un SMS a 644555666 para decirle que llegué bien", "644555666", "llegué bien"),
        ("Send a text to 644555666 to say that I arrived", "644555666", "I arrived"),
    ],
)
def test_body_after_a_delimiter_next_to_the_recipient(user_input, recipient, body):
    assert source_body(user_input, recipient) == body


def test_recipient_is_located_ignoring_case():
    assert source_body("Mail a ANA@test.com: hola", "ana@test.com") == "hola"


def test_a_time_after_a_connector_is_not_ambiguous():
    assert source_body("Dile a ana@test.com que la cita es a las 10:00", "ana@test.com") == "la cita es a las 10:00"


def test_no_delimiter_gives_no_body():
    assert source_body("Enviar email a juan@test.com hola", "juan@test.com") is None


def test_text_before_the_recipient_is_not_a_body():
    assert source_body("Hola: escribe a ana@test.com", "ana@test.com") is None


def test_connector_inside_a_word_is_not_a_delimiter():
    assert source_body("Mail a ana@test.com quedamos mañana", "ana@test.com") is None


def test_empty_body_gives_no_body():
    assert source_body("Mail a ana@test.com: ", "ana@test.com") is None


def test_unknown_recipient_gives_no_body():
    assert source_body("Mail a ana@test.com: hola", "eva@test.com") is None


def test_a_colon_away_from_the_recipient_is_ambiguous():
    with pytest.raises(AmbiguousBody):
        source_body("Email to sara@mail.com about the invoice: it is overdue", "sara@mail.com")


def test_a_time_without_a_delimiter_is_not_ambiguous():
    assert source_body("Mail a ana@test.com nos vemos a las 10:00", "ana@test.com") is None


def test_a_connector_followed_by_a_later_colon_is_ambiguous():
    with pytest.raises(AmbiguousBody):
        source_body("Avisa a pedro@x.com que está de vacaciones: vuelve el lunes.", "pedro@x.com")
