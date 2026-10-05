"""Time-ordered UUIDs (version 7) for primary keys (Database Design 1.2).

Python 3.12 has no uuid.uuid7 yet, so this follows RFC 9562 section 5.7: 48 bits of
Unix time in milliseconds, then version and variant bits, then random bits.
"""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    millis = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")  # 80 random bits, 74 of them used
    value = (millis & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version 7
    value |= (rand >> 68) << 64  # rand_a: 12 bits
    value |= 0b10 << 62  # variant
    value |= rand & ((1 << 62) - 1)  # rand_b: 62 bits
    return uuid.UUID(int=value)
