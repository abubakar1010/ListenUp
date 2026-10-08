from listenup.modules.admin.domain.roles import is_admin

ADMINS = ("Ops@Example.com", " lead@example.com ")


def test_a_listed_verified_email_is_an_admin() -> None:
    assert is_admin("ops@example.com", True, ADMINS)
    assert is_admin("LEAD@example.com ", True, ADMINS)


def test_an_unlisted_email_is_not_an_admin() -> None:
    assert not is_admin("learner@example.com", True, ADMINS)
    assert not is_admin("ops@example.com.evil", True, ADMINS)


def test_an_unverified_address_is_never_an_admin() -> None:
    assert not is_admin("ops@example.com", False, ADMINS)


def test_an_empty_list_has_no_admins() -> None:
    assert not is_admin("ops@example.com", True, ())
    assert not is_admin("", True, ("", " "))
