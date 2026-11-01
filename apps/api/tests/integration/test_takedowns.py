"""Takedowns of uploaded media (#105, SRS 2.2, OI-1, NFR-USE-3; ADR 0098).

An administrator records a takedown by the file's SHA-256; a background job removes
every learner's copy of that file (playback, peaks, original and card snippets) while
their sessions, marks and cards stay, and tells each learner. Intake refuses the file
afterwards. The API runs as `api_role_url` (only `listenup_api`'s rights, so
row-level security applies) and the jobs as `listenup_worker`.
"""

import asyncio
import hashlib
import json
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.modules.content import jobs as content_jobs
from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps, PermanentError, Reschedule, run_handler
from listenup.platform.storage import use_storage
from tests.integration.conftest import conninfo_to_url
from tests.integration.intake_helpers import (
    ClientFactory,
    FakeStorage,
    client_factory,
    learner_id,
)
from tests.integration.seed import seed_learner_data
from tests.integration.test_admin import AdminFactory, accounts  # noqa: F401 (fixture)
from tests.integration.test_conversion import Media, add_file, media, media_row, run_job  # noqa: F401

FILE = b"a recording a rights holder sent us"
SHA = hashlib.sha256(FILE).hexdigest()
FINGERPRINT = f"upload:{SHA}"


def body(**overrides: object) -> dict[str, object]:
    return {
        "fingerprint": FINGERPRINT,
        "grounds": "copyright",
        "reason": "Notice 2026-11-01 from the publisher of this talk; ownership checked.",
        **overrides,
    }


@pytest.fixture
def storage() -> Iterator[FakeStorage]:
    fake = FakeStorage()
    use_storage(fake)
    yield fake
    use_storage(None)


@pytest.fixture
def make_client(api_role_url: str, storage: FakeStorage) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, storage)


def worker_url(migrated_url: str) -> str:
    return conninfo_to_url(migrated_url) + "?options=-c%20role%3Dlistenup_worker"


def run(migrated_url: str, name: str, **args: object) -> Any:
    """Run a job handler as a worker would, with the workers' role."""

    async def go() -> Any:
        from listenup.modules.admin import jobs  # noqa: F401 (registers the job)

        database = Database(worker_url(migrated_url), pool_size=1)
        try:
            return await run_handler(name, JobDeps(database, None, 1), **args)
        finally:
            await database.dispose()

    return asyncio.run(go())


def apply(migrated_url: str, takedown_id: str) -> Any:
    return run(migrated_url, "admin.apply_takedown", takedown_id=takedown_id)


def queued_takedown_jobs(migrated_url: str) -> list[dict[str, Any]]:
    with psycopg.connect(migrated_url) as conn:
        rows = conn.execute(
            "SELECT args FROM procrastinate.procrastinate_jobs "
            "WHERE task_name = 'admin.apply_takedown' AND status = 'todo'"
        ).fetchall()
    return [{"takedown_id": row[0]["takedown_id"]} for row in rows]


def clear_queue(migrated_url: str) -> None:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM procrastinate.procrastinate_jobs "
            "WHERE task_name IN ('admin.apply_takedown', 'admin.reconcile_takedowns')"
        )


def clear_takedowns(migrated_url: str) -> None:
    """Takedowns are global, so each test starts without them (and their media links)."""
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("UPDATE content.media_objects SET takedown_id = NULL, status = 'failed' "
                     "WHERE takedown_id IS NOT NULL")  # fmt: skip
        conn.execute("DELETE FROM ops.takedowns")


@pytest.fixture(autouse=True)
def no_takedowns(migrated_url: str) -> Iterator[None]:
    clear_takedowns(migrated_url)
    clear_queue(migrated_url)
    yield
    clear_takedowns(migrated_url)
    clear_queue(migrated_url)


class Library:
    """A learner's seeded clip of `FILE` (or another file), with its stored objects."""

    def __init__(
        self, migrated_url: str, storage: FakeStorage, client: TestClient, sha: str = SHA
    ) -> None:
        self.client = client
        self.user = uuid.UUID(learner_id(client))
        self.seed = seed_learner_data(migrated_url, self.user)
        self.media = self.seed.media_id
        prefix = f"users/{self.user}/media/{self.media}/"
        self.playback, self.peaks = prefix + "playback.mp4", prefix + "peaks.json"
        self.original = f"users/{self.user}/uploads/{self.seed.confirmed_upload_id}.mp3"
        self.snippet = f"users/{self.user}/cards/{self.seed.card_id}/snippet.m4a"
        with psycopg.connect(migrated_url) as conn:
            conn.execute(
                "UPDATE content.media_objects SET fingerprint = %s WHERE id = %s",
                [f"upload:{self.user}:{sha}", self.media],
            )
            conn.execute(
                "UPDATE practice.cards SET audio_status = 'ready', snippet_key = %s, "
                "snippet_span = int4range(0, 4000) WHERE id = %s",
                [self.snippet, self.seed.card_id],
            )
        for key in (self.playback, self.peaks, self.original, self.snippet):
            storage.arrive(key, 10, data=b"0123456789")

    @property
    def keys(self) -> tuple[str, ...]:
        return (self.playback, self.peaks, self.original, self.snippet)


def counts(migrated_url: str, user: uuid.UUID) -> tuple[int, ...]:
    """The learner's own practice data, which a takedown keeps."""
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT (SELECT count(*) FROM content.contents WHERE user_id = %(u)s),"
            " (SELECT count(*) FROM practice.sessions WHERE user_id = %(u)s),"
            " (SELECT count(*) FROM practice.marks WHERE user_id = %(u)s),"
            " (SELECT count(*) FROM practice.cards WHERE user_id = %(u)s),"
            " (SELECT count(*) FROM practice.shadow_rounds"
            "   WHERE user_id = %(u)s AND recording_key IS NOT NULL)",
            {"u": user},
        ).fetchone()
    assert row is not None
    return tuple(int(value) for value in row)


# -- Only administrators ---------------------------------------------------------------


def test_a_learner_cannot_record_a_takedown(
    accounts: AdminFactory,  # noqa: F811
    migrated_url: str,
) -> None:
    learner = accounts(admin=False)
    unverified = accounts(admin=True, verified=False)

    for client in (learner, unverified):
        answer = client.post("/api/v1/admin/takedowns", json=body())
        assert answer.status_code == 404
        assert answer.json()["code"] == "not_found"

    with psycopg.connect(migrated_url) as conn:
        assert conn.execute("SELECT count(*) FROM ops.takedowns").fetchone() == (0,)
    assert queued_takedown_jobs(migrated_url) == []


def test_an_admin_records_a_takedown_and_queues_its_removal(
    accounts: AdminFactory,  # noqa: F811
    migrated_url: str,
) -> None:
    admin = accounts()

    answer = admin.post(
        "/api/v1/admin/takedowns",
        json=body(fingerprint=f"upload:{SHA.upper()}"),
        headers={"Idempotency-Key": "takedown-1"},
    )

    assert answer.status_code == 202, answer.text
    recorded = answer.json()
    assert recorded["fingerprint"] == FINGERPRINT  # hex is stored in lower case
    assert recorded["grounds"] == "copyright"
    assert recorded["actioned_at"] is None
    assert "reason" not in recorded
    assert answer.headers["Cache-Control"] == "private, no-store"
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT id::text, fingerprint, grounds, reason FROM ops.takedowns"
        ).fetchall()
    assert row == [(recorded["id"], FINGERPRINT, "copyright", body()["reason"])]
    assert queued_takedown_jobs(migrated_url) == [{"takedown_id": recorded["id"]}]

    # The same request again is answered from the first one.
    again = admin.post(
        "/api/v1/admin/takedowns",
        json=body(fingerprint=f"upload:{SHA.upper()}"),
        headers={"Idempotency-Key": "takedown-1"},
    )
    assert again.status_code == 202
    assert again.json()["id"] == recorded["id"]


def test_a_second_takedown_of_the_same_file_is_refused(
    accounts: AdminFactory,  # noqa: F811
    migrated_url: str,
) -> None:
    admin = accounts()
    first = admin.post("/api/v1/admin/takedowns", json=body()).json()

    second = admin.post("/api/v1/admin/takedowns", json=body(grounds="other_rights"))

    assert second.status_code == 409
    assert second.json()["code"] == "takedown_exists"
    assert second.json()["takedown_id"] == first["id"]
    assert len(queued_takedown_jobs(migrated_url)) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"fingerprint": SHA},  # no source kind
        {"fingerprint": f"upload:{SHA[:-1]}"},  # too short
        {"fingerprint": f"upload:{SHA[:-1]}g"},  # not hex
        {"fingerprint": "youtube:dQw4w9WgXcQ"},  # YouTube waits for #38
        {"grounds": "boring"},
        {"reason": ""},
        {"reason": "x" * 2001},
    ],
)
def test_an_invalid_takedown_is_refused(
    accounts: AdminFactory,  # noqa: F811
    migrated_url: str,
    overrides: dict[str, object],
) -> None:
    admin = accounts()

    answer = admin.post("/api/v1/admin/takedowns", json=body(**overrides))

    assert answer.status_code == 422
    with psycopg.connect(migrated_url) as conn:
        assert conn.execute("SELECT count(*) FROM ops.takedowns").fetchone() == (0,)


# -- Removal for every learner ---------------------------------------------------------


def record(admin: TestClient, **overrides: object) -> str:
    answer = admin.post("/api/v1/admin/takedowns", json=body(**overrides))
    assert answer.status_code == 202, answer.text
    return str(answer.json()["id"])


@pytest.fixture
def listener(migrated_url: str) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("LISTEN user_events")
        yield conn


def events(conn: psycopg.Connection[tuple[object, ...]]) -> list[tuple[str, str, str]]:
    return [
        (payload["u"], payload["t"], payload["r"])
        for payload in (json.loads(note.payload) for note in conn.notifies(timeout=1.0))
    ]


def test_a_takedown_removes_the_file_for_every_learner_and_keeps_their_practice(
    accounts: AdminFactory,  # noqa: F811
    make_client: ClientFactory,
    storage: FakeStorage,
    migrated_url: str,
    listener: psycopg.Connection[tuple[object, ...]],
) -> None:
    a = Library(migrated_url, storage, make_client())
    b = Library(migrated_url, storage, make_client())
    other = Library(migrated_url, storage, make_client(), sha="0" * 64)
    kept = {learner.user: counts(migrated_url, learner.user) for learner in (a, b)}
    takedown = record(accounts())

    report = apply(migrated_url, takedown)

    for learner in (a, b):
        row = media_row(migrated_url, str(learner.media))
        assert row is not None
        assert row["status"] == "removed"
        assert row["playback_key"] is None and row["peaks_key"] is None
        assert not any(key in storage.objects for key in learner.keys)
        # Sessions, marks, cards and the learner's own recordings stay (#105 notes).
        assert counts(migrated_url, learner.user) == kept[learner.user]
    with psycopg.connect(migrated_url) as conn:
        cards = conn.execute(
            "SELECT audio_status, snippet_key FROM practice.cards WHERE id = ANY(%s)",
            [[a.seed.card_id, b.seed.card_id]],
        ).fetchall()
        actioned = conn.execute(
            "SELECT actioned_at IS NOT NULL, report FROM ops.takedowns WHERE id = %s",
            [takedown],
        ).fetchone()
    assert cards == [("unavailable", None), ("unavailable", None)]
    assert actioned == (True, report)
    assert report == {"media_removed": 2, "learners": 2, "objects_removed": 6}
    # Another file is untouched.
    assert media_row(migrated_url, str(other.media))["status"] == "playable"  # type: ignore[index]
    assert all(key in storage.objects for key in other.keys)
    # Each affected learner hears about their own clip, and only they do.
    told = {(user, kind, resource) for user, kind, resource in events(listener)}
    assert (str(a.user), "content.ready", str(a.seed.content_id)) in told
    assert (str(b.user), "content.ready", str(b.seed.content_id)) in told
    assert not any(user == str(other.user) for user, _, _ in told)

    # Running it again changes nothing and reports the same.
    assert apply(migrated_url, takedown) == report


def test_the_learner_is_told_in_plain_words_and_the_clip_cannot_be_played(
    accounts: AdminFactory,  # noqa: F811
    make_client: ClientFactory,
    storage: FakeStorage,
    migrated_url: str,
) -> None:
    mine = Library(migrated_url, storage, make_client())
    apply(migrated_url, record(accounts(), grounds="other_rights"))
    client = mine.client
    # The seed's Blind listen would refuse whole-clip playback first (ADR 0033).
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE practice.attempts SET status = 'voided', finished_at = now() WHERE id = %s",
            [mine.seed.blind_attempt_id],
        )

    item = client.get(f"/api/v1/contents/{mine.seed.content_id}")
    library = client.get("/api/v1/library/contents")
    play = client.get(f"/api/v1/media/{mine.media}", follow_redirects=False)
    peaks = client.get(f"/api/v1/media/{mine.media}/peaks", follow_redirects=False)
    plan = client.post(
        "/api/v1/sessions",
        json={
            "content_id": str(mine.seed.content_id),
            "entry": "blind",
            "passage": {"start_ms": 0, "end_ms": 60_000},
        },
    )
    card_audio = client.get(f"/api/v1/cards/{mine.seed.card_id}/audio", follow_redirects=False)

    assert item.status_code == 200
    detail = item.json()
    assert detail["status"] == "removed"
    assert detail["media_url"] is None and detail["peaks_url"] is None
    assert detail["removal"]["grounds"] == "other_rights"
    message = detail["removal"]["message"]
    assert "removed" in message and "rights" in message
    assert "sessions, marks and cards are kept" in message
    # The administrator's own note never reaches the learner.
    assert "Notice 2026-11-01" not in item.text
    assert [entry["status"] for entry in library.json()["items"]] == ["removed"]
    for answer in (play, peaks):
        assert answer.status_code == 410
        assert answer.json()["code"] == "media_removed"
    assert plan.status_code == 409
    assert plan.json()["code"] == "content_not_ready"
    assert "removed" in plan.json()["detail"]
    assert card_audio.status_code == 409


def test_removal_waits_for_a_conversion_still_writing_the_file(
    accounts: AdminFactory,  # noqa: F811
    make_client: ClientFactory,
    storage: FakeStorage,
    migrated_url: str,
) -> None:
    mine = Library(migrated_url, storage, make_client())
    writer = uuid.uuid4()
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO content.media_writes (id, media_object_id, user_id, owner) "
            "VALUES (%s, %s, %s, 'worker:1')",
            [writer, mine.media, mine.user],
        )
    takedown = record(accounts())

    with pytest.raises(Reschedule):
        apply(migrated_url, takedown)

    # The clip is unavailable at once, but nothing is deleted under a live writer.
    assert media_row(migrated_url, str(mine.media))["status"] == "removed"  # type: ignore[index]
    assert all(key in storage.objects for key in mine.keys)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        assert conn.execute(
            "SELECT actioned_at FROM ops.takedowns WHERE id = %s", [takedown]
        ).fetchone() == (None,)
        conn.execute("DELETE FROM content.media_writes WHERE id = %s", [writer])

    apply(migrated_url, takedown)
    assert not any(key in storage.objects for key in mine.keys)


def test_unfinished_takedowns_are_queued_again(
    accounts: AdminFactory,  # noqa: F811
    migrated_url: str,
) -> None:
    takedown = record(accounts())
    clear_queue(migrated_url)

    run(migrated_url, "admin.reconcile_takedowns", timestamp=0)

    assert queued_takedown_jobs(migrated_url) == [{"takedown_id": takedown}]
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("UPDATE ops.takedowns SET actioned_at = now()")
    clear_queue(migrated_url)
    run(migrated_url, "admin.reconcile_takedowns", timestamp=0)
    assert queued_takedown_jobs(migrated_url) == []


def test_a_removed_clip_leaves_the_export_without_its_files(
    accounts: AdminFactory,  # noqa: F811
    make_client: ClientFactory,
    storage: FakeStorage,
    migrated_url: str,
) -> None:
    from listenup.modules.content import service as content

    mine = Library(migrated_url, storage, make_client())
    apply(migrated_url, record(accounts()))
    # Even if the original upload's row were still there, a removed clip exports no file.
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE content.uploads SET storage_key = %s WHERE id = %s",
            [mine.original, mine.seed.confirmed_upload_id],
        )

    async def collect() -> Any:
        database = Database(worker_url(migrated_url), pool_size=1)
        try:
            async with database.transaction() as db:
                return await content.export_data(db, mine.user)
        finally:
            await database.dispose()

    part = asyncio.run(collect())
    assert all(str(mine.media) not in file.key for file in part.files)
    assert all(file.key != mine.original for file in part.files)


# -- Intake refuses the file afterwards ------------------------------------------------


def test_intake_refuses_a_file_that_was_taken_down(
    accounts: AdminFactory,  # noqa: F811
    make_client: ClientFactory,
    storage: FakeStorage,
    media: Media,  # noqa: F811
    migrated_url: str,
) -> None:
    sha = hashlib.sha256(media.mp3.read_bytes()).hexdigest()
    apply(migrated_url, record(accounts(), fingerprint=f"upload:{sha}"))
    client = make_client()

    added = add_file(client, storage, media.mp3, migrated_url)
    with pytest.raises(PermanentError):
        run_job(migrated_url, added)

    row = media_row(migrated_url, added.media_id)
    assert row is not None
    assert (row["status"], row["error_code"]) == ("failed", "source_taken_down")
    assert row["playback_key"] is None
    assert added.source_key not in storage.objects  # the original is deleted
    detail = client.get(f"/api/v1/contents/{added.content_id}").json()
    assert detail["error_code"] == "source_taken_down"
    assert "can't be added again" in detail["error_detail"]


def test_a_takedown_recorded_during_a_conversion_still_stops_it(
    accounts: AdminFactory,  # noqa: F811
    make_client: ClientFactory,
    storage: FakeStorage,
    media: Media,  # noqa: F811
    migrated_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The takedown commits after the job checked the file's hash but before the job
    stores the playback file: the job's last transaction checks again."""
    sha = hashlib.sha256(media.mp3.read_bytes()).hexdigest()
    admin = accounts()
    client = make_client()
    added = add_file(client, storage, media.mp3, migrated_url)
    convert = content_jobs.ffmpeg.convert

    async def convert_then_take_down(*args: Any, **kwargs: Any) -> Any:
        record(admin, fingerprint=f"upload:{sha}")
        return await convert(*args, **kwargs)

    monkeypatch.setattr(content_jobs.ffmpeg, "convert", convert_then_take_down)
    with pytest.raises(PermanentError):
        run_job(migrated_url, added)

    row = media_row(migrated_url, added.media_id)
    assert row is not None
    assert (row["status"], row["error_code"]) == ("failed", "source_taken_down")
    user = learner_id(client)
    assert not any(key.startswith(f"users/{user}/media/") for key in storage.objects)


def test_a_learner_whose_copy_was_removed_is_refused_rather_than_merged(
    accounts: AdminFactory,  # noqa: F811
    make_client: ClientFactory,
    storage: FakeStorage,
    media: Media,  # noqa: F811
    migrated_url: str,
) -> None:
    """The takedown check runs before the duplicate check: the removed copy must not
    swallow the new item as a duplicate (ADR 0022) instead of refusing it."""
    sha = hashlib.sha256(media.mp3.read_bytes()).hexdigest()
    client = make_client()
    first = add_file(client, storage, media.mp3, migrated_url)
    run_job(migrated_url, first)
    apply(migrated_url, record(accounts(), fingerprint=f"upload:{sha}"))

    again = add_file(client, storage, media.mp3, migrated_url)
    with pytest.raises(PermanentError):
        run_job(migrated_url, again)

    assert media_row(migrated_url, first.media_id)["status"] == "removed"  # type: ignore[index]
    detail = client.get(f"/api/v1/contents/{again.content_id}")
    assert detail.status_code == 200
    assert detail.json()["error_code"] == "source_taken_down"
