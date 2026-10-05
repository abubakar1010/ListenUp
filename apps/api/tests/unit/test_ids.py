import time

from listenup.platform.ids import uuid7


def test_uuid7_has_version_7_and_the_rfc_variant() -> None:
    value = uuid7()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_uuid7_starts_with_the_current_time_in_milliseconds() -> None:
    before = time.time_ns() // 1_000_000
    millis = uuid7().int >> 80
    after = time.time_ns() // 1_000_000
    assert before <= millis <= after


def test_uuid7_values_are_unique() -> None:
    assert len({uuid7() for _ in range(10_000)}) == 10_000
