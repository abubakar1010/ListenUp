"""Turn a database password into a SCRAM-SHA-256 verifier (#112, Database Design 9.1).

infra/deploy/bootstrap-roles.sql takes verifiers, never passwords: a statement that
carries a plain password is written to the server log when it fails (and on every run
where the provider logs DDL), while a verifier is safe to log. The password is read
from standard input, so it stays out of the shell history and the process list:

    printf '%s' "$API_PW" | python -m listenup.ops.scram_verifier

prints `SCRAM-SHA-256$4096:<salt>$<StoredKey>:<ServerKey>`, the format PostgreSQL
stores (RFC 5802, RFC 7677). Passwords are printable ASCII, which SASLprep leaves
unchanged, so the verifier matches what the server computes at sign-in.
"""

import base64
import hashlib
import hmac
import os
import sys
from typing import TextIO

ITERATIONS = 4096  # PostgreSQL's scram_iterations default


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def scram_verifier(password: str, *, salt: bytes | None = None) -> str:
    salt = os.urandom(16) if salt is None else salt
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    return f"SCRAM-SHA-256${ITERATIONS}:{_b64(salt)}${_b64(stored_key)}:{_b64(server_key)}"


def main(stdin: TextIO = sys.stdin) -> int:
    password = stdin.readline().rstrip("\r\n")
    if not password or not all(" " <= char <= "~" for char in password):
        print("error: the password must be non-empty printable ASCII", file=sys.stderr)
        return 2
    print(scram_verifier(password))
    return 0


if __name__ == "__main__":
    sys.exit(main())
