"""Absolute half-open snippet windows, bounded to 3-6 seconds (FR-CA-2)."""


def snippet_window(start: int, end: int, duration: int) -> tuple[int, int]:
    if not 0 <= start < end <= duration or end - start > 6000 or duration < 3000:
        raise ValueError("Choose a marked phrase lasting at most six seconds.")
    length = max(3000, min(6000, end - start + 1000))
    left = max(0, min(start - (length - (end - start)) // 2, duration - length))
    return left, left + length
