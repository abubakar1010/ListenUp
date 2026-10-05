"""Argon2id password hashing (NFR-SEC-1).

Hashing takes tens of milliseconds of CPU on purpose, so it runs in a worker thread
and never blocks the event loop.
"""

import anyio.to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()  # Argon2id with the library's current recommended parameters

# Verified against when the email is unknown, so a wrong email takes as long as a
# wrong password and response times do not reveal which accounts exist.
_DUMMY_HASH = _hasher.hash("listenup-timing-equaliser")


async def hash_password(password: str) -> str:
    return await anyio.to_thread.run_sync(_hasher.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    def verify() -> bool:
        try:
            return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
        except (VerificationError, InvalidHashError):
            return False

    return await anyio.to_thread.run_sync(verify)


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
