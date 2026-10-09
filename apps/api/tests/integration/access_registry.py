"""Who may call each API route: the registry of the cross-learner access test (#34).

NFR-SEC-2: a learner reads and changes only their own content, sessions and
recordings. `test_access_cross_learner.py` signs in two learners, A and B, gives A a
full set of data with the fixture script (`seed.py`: a clip, a pending upload and a
session at each step), and then calls every route in this registry three ways:

- signed out: every route that is not `Public` answers 401 `not_signed_in`;
- as learner B, with B's own CSRF token: the answer is the one registered below, no
  id or email of A's appears in it, and none of A's rows or stored files change;
- as learner A, for GET routes: a success, and every id in `a_sees` is in the answer,
  so a check that B sees nothing is never passing only because A had nothing.

The test lists the app's routes from `app.routes` and the OpenAPI schema, so a new
route is picked up on its own; a route that is missing here fails the test with a
message that points to this file, and so does an entry whose route no longer exists.

Registering a route takes one entry. Pick the kind that says what B must get:

    # A path that names one of A's resources: B gets 404 with this code.
    ("GET", "/api/v1/sessions/{session_id}"): Owned(
        "session_not_found", params=lambda w: {"session_id": w.a.sessions["dictation"]}
    ),
    # A list, or anything that answers about the caller only: B gets 200 without A's ids.
    ("GET", "/api/v1/sessions"): Scoped(a_sees=lambda w: w.a.sessions.values()),
    # No sign-in needed: say why.
    ("GET", "/api/v1/health"): Public("liveness probe; returns no learner data"),

`w` is the `World`: `w.a` is learner A's `SeededLearner` and `w.owner_url` reaches
the database as its owner, for a fixture that needs to make more of A's data with
the functions in `seed.py`. When a route needs data the fixture script does not
make yet, add it to `seed.py` so every route and the local seed share it.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import httpx

from tests.integration.seed import SeededLearner


@dataclass(frozen=True)
class World:
    """What the fixtures see: learner A's seeded data and the owner connection."""

    a: SeededLearner
    a_email: str
    owner_url: str

    def secrets_of_a(self) -> list[str]:
        """Strings that must never reach learner B: A's ids and email."""
        return [*self.a.ids(), self.a_email]


Params = Callable[[World], dict[str, object]]
Body = Callable[[World], dict[str, object]]
Check = Callable[[World, httpx.Response], str | None]


def no_params(world: World) -> dict[str, object]:
    return {}


@dataclass(frozen=True)
class Public:
    """Callable without signing in. `reason` says why that is safe."""

    reason: str


@dataclass(frozen=True)
class Owned:
    """The request names one of A's resources (in the path or the body).

    B gets `status` (404, as if it did not exist) with problem `code`, and nothing of
    A's changes. `params` fills the path template; `body` is the JSON body, if any.
    """

    code: str
    params: Params = no_params
    body: Body | None = None
    status: int = 404


@dataclass(frozen=True)
class Scoped:
    """Answers about the caller's own data only: a list, the account, a create.

    B gets `status`; none of A's ids or email appear in the answer and none of A's
    data changes. `a_sees` names ids A's own answer must contain (GET only), so the
    check cannot pass on an empty list. `check` adds a route-specific test of B's
    answer and returns a message when it fails.
    """

    status: int = 200
    body: Body | None = None
    a_sees: Callable[[World], Iterable[object]] | None = None
    check: Check | None = None


@dataclass(frozen=True)
class Stream:
    """A Server-Sent Events stream: the signed-out call is checked with the others,
    and what B receives is checked over a real server by the named test."""

    covered_by: str


Entry = Public | Owned | Scoped | Stream


def _usage_counts_only_b(world: World, response: httpx.Response) -> str | None:
    # GET routes run before any write of B's, so B has stored nothing yet.
    used = response.json().get("used_bytes")
    return None if used == 0 else f"B's storage use is {used}, which counts A's uploads"


def _deletion_summary_counts_only_b(world: World, response: httpx.Response) -> str | None:
    found = response.json()
    expected = {"clips": 0, "practice_sessions": 0, "cards": 0, "recordings": 0}
    return None if found == expected else f"B's deletion summary counts A's data: {found}"


def _new_upload(world: World) -> dict[str, object]:
    return {"filename": "b-clip.mp3", "content_type": "audio/mpeg", "size_bytes": 1_000_000}


REGISTRY: dict[tuple[str, str], Entry] = {
    # -- platform ----------------------------------------------------------------------
    ("GET", "/api/v1/health"): Public("liveness probe; returns only the status and version"),
    ("GET", "/api/v1/events"): Stream(
        "test_access_cross_learner.py::test_events_of_a_never_reach_b"
    ),
    # -- identity ----------------------------------------------------------------------
    ("POST", "/api/v1/auth/register"): Public("creates an account; nobody is signed in yet"),
    ("POST", "/api/v1/auth/login"): Public("signs in; nobody is signed in yet"),
    ("POST", "/api/v1/auth/logout"): Public(
        "ends the caller's own login session, if any; signed out it only clears the cookie"
    ),
    ("POST", "/api/v1/auth/password-reset"): Public(
        "the learner has forgotten the password; same answer whether the email exists"
    ),
    ("POST", "/api/v1/auth/password-reset/confirm"): Public(
        "authorised by the one-time token from the email, not by a login session"
    ),
    ("GET", "/api/v1/me"): Scoped(a_sees=lambda w: [w.a.user_id]),
    ("GET", "/api/v1/me/deletion-summary"): Scoped(check=_deletion_summary_counts_only_b),
    # B can only ever delete B's own account; with a wrong password nothing happens.
    ("DELETE", "/api/v1/me"): Scoped(
        status=403, body=lambda w: {"password": "not B's password", "confirm": True}
    ),
    # -- content: uploads and intake ---------------------------------------------------
    ("GET", "/api/v1/uploads/usage"): Scoped(check=_usage_counts_only_b),
    ("POST", "/api/v1/uploads"): Scoped(status=201, body=_new_upload),
    ("DELETE", "/api/v1/uploads/{upload_id}"): Owned(
        "upload_not_found", params=lambda w: {"upload_id": w.a.pending_upload_id}
    ),
    # A's confirmed upload: confirming it again would answer with A's content item.
    ("POST", "/api/v1/contents"): Owned(
        "upload_not_found", body=lambda w: {"upload_id": str(w.a.confirmed_upload_id)}
    ),
    ("GET", "/api/v1/contents"): Scoped(a_sees=lambda w: [w.a.content_id]),
    ("GET", "/api/v1/contents/{content_id}"): Owned(
        "content_not_found", params=lambda w: {"content_id": w.a.content_id}
    ),
    # -- practice sessions -------------------------------------------------------------
    ("POST", "/api/v1/sessions"): Owned(
        "content_not_found",
        body=lambda w: {
            "content_id": str(w.a.content_id),
            "passage": {"start_ms": 0, "end_ms": 60_000},
            "entry": "both",
        },
    ),
    ("GET", "/api/v1/sessions"): Scoped(a_sees=lambda w: w.a.sessions.values()),
    ("GET", "/api/v1/sessions/{session_id}"): Owned(
        "session_not_found", params=lambda w: {"session_id": w.a.sessions["dictation"]}
    ),
    ("PATCH", "/api/v1/sessions/{session_id}/entry"): Owned(
        "session_not_found",
        params=lambda w: {"session_id": w.a.sessions["dictation"]},
        body=lambda w: {"entry": "blind", "version": 0},
    ),
    ("POST", "/api/v1/sessions/{session_id}/steps/{step}/skip"): Owned(
        "session_not_found",
        params=lambda w: {"session_id": w.a.sessions["card"], "step": "card"},
        body=lambda w: {"confirmed": True, "version": 0},
    ),
    # -- blind -------------------------------------------------------------------------
    ("GET", "/api/v1/sessions/{session_id}/blind"): Owned(
        "session_not_found", params=lambda w: {"session_id": w.a.sessions["blind"]}
    ),
    ("POST", "/api/v1/sessions/{session_id}/blind/attempts"): Owned(
        "session_not_found", params=lambda w: {"session_id": w.a.sessions["blind"]}
    ),
    ("POST", "/api/v1/blind/attempts/{attempt_id}/heartbeat"): Owned(
        "attempt_not_found",
        params=lambda w: {"attempt_id": w.a.blind_attempt_id},
        body=lambda w: {"position_ms": 0, "state": "playing", "visible": True},
    ),
    ("POST", "/api/v1/blind/attempts/{attempt_id}/void"): Owned(
        "attempt_not_found",
        params=lambda w: {"attempt_id": w.a.blind_attempt_id},
        body=lambda w: {"reason": "left_page"},
    ),
    # B holds A's attempt id and A's valid token, and still gets nothing.
    ("GET", "/api/v1/blind/attempts/{attempt_id}/media/{token}"): Owned(
        "attempt_not_found",
        params=lambda w: {"attempt_id": w.a.blind_attempt_id, "token": w.a.blind_media_token},
    ),
    ("POST", "/api/v1/blind/attempts/{attempt_id}/gist"): Owned(
        "attempt_not_found",
        params=lambda w: {"attempt_id": w.a.blind_attempt_id},
        body=lambda w: {"text": "One two three. Four five six. Seven eight nine."},
    ),
    # -- dictation ---------------------------------------------------------------------
    ("POST", "/api/v1/sessions/{session_id}/dictation/attempts"): Owned(
        "session_not_found", params=lambda w: {"session_id": w.a.sessions["dictation"]}
    ),
    ("PUT", "/api/v1/dictation/attempts/{attempt_id}/draft"): Owned(
        "attempt_not_found",
        params=lambda w: {"attempt_id": w.a.dictation_attempt_id},
        body=lambda w: {"draft_text": "B was here", "draft_version": 1},
    ),
    # -- media -------------------------------------------------------------------------
    ("GET", "/api/v1/media/{media_object_id}"): Owned(
        "media_not_found", params=lambda w: {"media_object_id": w.a.media_id}
    ),
    ("GET", "/api/v1/media/{media_object_id}/peaks"): Owned(
        "media_not_found", params=lambda w: {"media_object_id": w.a.media_id}
    ),
    # -- data export -------------------------------------------------------------------
    ("POST", "/api/v1/me/exports"): Scoped(status=202),
    ("GET", "/api/v1/me/exports/latest"): Scoped(a_sees=lambda w: [w.a.export_id]),
    # B holds the id of A's ready export and still gets no link to it.
    ("GET", "/api/v1/me/exports/{export_id}/download"): Owned(
        "export_not_found", params=lambda w: {"export_id": w.a.export_id}
    ),
    # -- library -----------------------------------------------------------------------
    ("GET", "/api/v1/library/contents"): Scoped(a_sees=lambda w: [w.a.content_id]),
}
