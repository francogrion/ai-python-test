import time

from recipients import find_addressees, find_recipients, is_email, same_recipient


def test_finds_an_email():
    assert find_recipients("Manda un mail a Ana.Lopez@test.com diciendo hola") == ["Ana.Lopez@test.com"]


def test_finds_phones_in_the_formats_people_write():
    assert find_recipients("SMS al 600-111-222: hola") == ["600-111-222"]
    assert find_recipients("teléfono 699888777: hola") == ["699888777"]
    assert find_recipients("llama al 612 345 678 ya") == ["612 345 678"]
    assert find_recipients("avisa al +34600111222") == ["+34600111222"]


def test_times_and_dates_are_not_phones():
    assert find_recipients("cita a las 10:00 del 2026-10-30") == []


def test_digits_inside_an_email_are_not_a_phone():
    assert find_recipients("a user600111222@test.com") == ["user600111222@test.com"]


def test_trailing_sentence_dot_is_not_part_of_the_email():
    assert find_recipients("Escribe a ana@test.com.") == ["ana@test.com"]


def test_all_distinct_recipients_are_returned_in_order():
    assert find_recipients("a ana@test.com y al 600111222") == ["ana@test.com", "600111222"]


def test_the_same_recipient_written_twice_counts_once():
    assert find_recipients("a ANA@test.com, repito ana@test.com") == ["ANA@test.com"]


def test_no_recipient():
    assert find_recipients("Avisa a Pedro de que no hay clase") == []


def test_emails_compare_ignoring_case():
    assert same_recipient("ANA@test.com", "ana@test.com")


def test_phones_compare_by_digits():
    assert same_recipient("600-111-222", "600111222")


def test_different_recipients_do_not_match():
    assert not same_recipient("ana@test.com", "eva@test.com")
    assert not same_recipient("600111222", "600111223")
    assert not same_recipient("ana@test.com", "600111222")


def test_a_date_with_a_time_is_not_a_phone():
    assert find_recipients("Recuerda la cita del 2026-11-03 10:00") == []


def test_a_long_text_without_recipients_is_scanned_in_linear_time():
    start = time.perf_counter()
    assert find_recipients("a" * 200_000) == []
    assert time.perf_counter() - start < 0.5


def test_addressees_are_the_contacts_before_the_body():
    assert find_addressees("Mail a ana@test.com: llama a eva@test.com") == ["ana@test.com"]
    assert find_addressees("Dile a Pedro: escribe a eva@test.com") == []


def test_a_time_does_not_end_the_addressee_part():
    assert find_addressees("A las 10:00 avisa a ana@test.com") == ["ana@test.com"]


def test_is_email():
    assert is_email("ana@test.com")
    assert not is_email("600111222")
