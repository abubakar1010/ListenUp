"""Half-open millisecond ranges for the shared passage cache (System Design 5.1)."""

Span = tuple[int, int]


def padded_span(start: int, end: int, duration: int) -> Span:
    if not 0 <= start < end <= duration:
        raise ValueError("passage must fit the media")
    return max(0, start - 5000), min(duration, end + 5000)


def missing_spans(wanted: Span, cached: list[Span]) -> list[Span]:
    cursor, end = wanted
    missing: list[Span] = []
    for left, right in sorted(cached):
        if right <= cursor:
            continue
        if left >= end:
            break
        if left > cursor:
            missing.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < end:
        missing.append((cursor, end))
    return missing
