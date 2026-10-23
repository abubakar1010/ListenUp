"""Bound the requested simple-English feedback to 2-4 complete sentences (FR-BL-8)."""

import re


def validate_feedback(text: str) -> None:
    sentences = [part for part in re.split(r"[.!?]+(?:\s+|$)", text.strip()) if part.strip()]
    if not 2 <= len(sentences) <= 4 or not re.search(r"[.!?]$", text.strip()):
        raise ValueError("Invalid grading feedback")
