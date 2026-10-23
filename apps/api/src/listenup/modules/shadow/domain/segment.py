"""Shadow segment rules (FR-SH-1, C3, D8). Times are absolute, half-open ms.

Use the longest permitted window to maximize mark coverage; ties choose the
earliest start. Sorted marks and a sliding pointer keep the search O(n log n).
"""


def validate(passage_start: int, passage_end: int, start: int, end: int) -> None:
    duration = passage_end - passage_start
    if not (duration >= 30_000 and passage_start <= start < end <= passage_end):
        raise ValueError("segment_span")
    if duration <= 60_000:
        valid = (start, end) == (passage_start, passage_end)
    else:
        valid = 60_000 <= end - start <= 90_000
    if not valid:
        raise ValueError("segment_span")


def propose(passage_start: int, passage_end: int, marks: list[int]) -> tuple[int, int, int]:
    length = min(90_000, passage_end - passage_start)
    validate(passage_start, passage_end, passage_start, passage_start + length)
    points = sorted(m for m in marks if passage_start <= m < passage_end)
    # A mark enters a half-open window at mark - length + 1 ms. Consider those
    # starts to find the earliest maximum, including marks exactly at the end.
    candidates = sorted(
        {
            passage_start,
            *[max(passage_start, min(m - length + 1, passage_end - length)) for m in points],
        }
    )
    left = right = 0
    best = (passage_start, passage_start + length, 0)
    for start in candidates:
        while left < len(points) and points[left] < start:
            left += 1
        while right < len(points) and points[right] < start + length:
            right += 1
        if right - left > best[2]:
            best = (start, start + length, right - left)
    return best
