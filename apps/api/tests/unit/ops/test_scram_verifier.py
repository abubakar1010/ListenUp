"""SCRAM verifiers for bootstrap-roles.sql (#112, Database Design 9.1).

The expected verifier was made by PostgreSQL 16 itself (`CREATE ROLE ... PASSWORD
'pencil'`, then pg_authid.rolpassword), so it is an independent oracle.
"""

import base64
import io

import pytest

from listenup.ops.scram_verifier import main, scram_verifier

POSTGRES_PENCIL = (
    "SCRAM-SHA-256$4096:TiAH5FeboFqq88ikSO74lw==$"
    "Qbc06ul8/VSv1v33dZR1C7UACo7nSvg7bNtPYiDdg9s=:"
    "oZJlLeTqh74VGDBuOqBPKZdDsAAhSOgdXd48MKCPEx8="
)


def test_the_verifier_matches_the_one_postgresql_makes_for_the_same_salt() -> None:
    salt = base64.b64decode("TiAH5FeboFqq88ikSO74lw==")

    assert scram_verifier("pencil", salt=salt) == POSTGRES_PENCIL


def test_each_verifier_gets_a_fresh_salt() -> None:
    first, second = scram_verifier("pencil"), scram_verifier("pencil")

    assert first != second
    assert first.startswith("SCRAM-SHA-256$4096:")


def test_main_reads_the_password_from_stdin_and_prints_only_the_verifier(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(io.StringIO("pencil\n")) == 0

    printed = capsys.readouterr().out
    assert printed.startswith("SCRAM-SHA-256$4096:")
    assert "pencil" not in printed


@pytest.mark.parametrize("line", ["\n", "pässword\n", "tab\there\n"])
def test_an_empty_or_non_ascii_password_is_refused(
    line: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(io.StringIO(line)) == 2
    assert capsys.readouterr().out == ""
