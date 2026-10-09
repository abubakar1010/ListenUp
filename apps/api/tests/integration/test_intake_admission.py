"""Intake admission per learner (#41: D16, FR-CI-3, NFR-USE-3, System Design 4.2; ADR 0027).

- New audio per UTC day: a new clip is refused once the day's count, plus 15 minutes
  for each clip still being prepared, reaches the limit; the refusal says when it
  resets. Checked when an upload starts and again when it is confirmed.
- At most two intakes of one learner on the shared intake lane; the rest wait in the
  learner's own queue and start, oldest first, as the learner's conversions end.

The API runs as a role with only the API's rights; jobs run as the migration owner,
like the workers. Media is made with ffmpeg here where a real conversion is needed.
"""

import asyncio
import subprocess
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.main import create_app
from listenup.modules.content import jobs
from listenup.platform.config import Settings
from listenup.platform.database import Database
from listenup.platform.jobs import JobDeps, PermanentError
from listenup.platform.storage import use_storage
from tests.integration.conftest import conninfo_to_url, with_csrf
from tests.integration.intake_helpers import (
    PASSWORD,
    ClientFactory,
    FakeStorage,
    client_factory,
    confirm,
    key_of,
    learner_id,
    start,
)

LIMIT_SECONDS = 120 * 60


@pytest.fixture
def storage() -> Iterator[FakeStorage]:
    fake = FakeStorage()
    use_storage(fake)
    yield fake
    use_storage(None)


@pytest.fixture
def make_client(api_role_url: str, storage: FakeStorage) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, storage)


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client()


@pytest.fixture(autouse=True)
def no_queued_jobs(migrated_url: str) -> None:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute("DELETE FROM procrastinate.procrastinate_jobs")


def set_daily_count(
    migrated_url: str, user: str, seconds: int, day: datetime | None = None
) -> None:
    """Today's (or `day`'s) count of new audio seconds, as the conversion job keeps it."""
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO ops.rate_counters (key, window_start, count) "
            "VALUES (%s, coalesce(%s, date_bin('1 day', now(), timestamptz '2000-01-01Z')), %s) "
            "ON CONFLICT (key, window_start) DO UPDATE SET count = excluded.count",
            [f"intake:user:{user}", day, seconds],
        )


def daily_count(migrated_url: str, user: str) -> int:
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT count FROM ops.rate_counters WHERE key = %s "
            "AND window_start = date_bin('1 day', now(), timestamptz '2000-01-01Z')",
            [f"intake:user:{user}"],
        ).fetchone()
    return int(row[0]) if row else 0  # type: ignore[call-overload]


def next_utc_midnight() -> datetime:
    now = datetime.now(UTC)
    return datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1)


def add(
    client: TestClient, storage: FakeStorage, data: bytes | None = None, name: str = "talk.mp3"
) -> dict[str, str]:
    """Upload and confirm a file; `data` None leaves storage without its bytes."""
    size = len(data) if data else 1024
    target = start(client, filename=name, size=size).json()
    storage.arrive(key_of(target), size, "audio/mpeg", data)
    confirmed = confirm(client, target["upload_id"])
    assert confirmed.status_code == 201, confirmed.text
    content_id = confirmed.json()["id"]
    return {
        "content_id": content_id,
        "upload_id": target["upload_id"],
        "media_id": media_of(client, content_id),
    }


def media_of(client: TestClient, content_id: str) -> str:
    return str(client.get(f"/api/v1/contents/{content_id}").json()["media_object_id"])


def queued_jobs(migrated_url: str, user: str) -> list[str]:
    """Upload ids of the learner's conversion jobs on the shared lane, oldest first."""
    with psycopg.connect(migrated_url) as conn:
        rows = conn.execute(
            "SELECT args->>'upload_id' FROM procrastinate.procrastinate_jobs "
            "WHERE task_name = 'content.convert_upload' AND args->>'user_id' = %s "
            "AND status = 'todo' ORDER BY id",
            [user],
        ).fetchall()
    return [str(row[0]) for row in rows]


def run_job(migrated_url: str, client: TestClient, item: dict[str, str]) -> None:
    """Run the item's conversion as a worker would, and take its job off the lane."""
    user = learner_id(client)

    async def run() -> None:
        database = Database(conninfo_to_url(migrated_url), pool_size=1)
        try:
            await jobs.convert_upload(
                JobDeps(database, None, 1),
                media_object_id=item["media_id"],
                upload_id=item["upload_id"],
                user_id=user,
            )
        finally:
            await database.dispose()
            with psycopg.connect(migrated_url, autocommit=True) as conn:
                conn.execute(
                    "DELETE FROM procrastinate.procrastinate_jobs WHERE args->>'upload_id' = %s",
                    [item["upload_id"]],
                )

    asyncio.run(run())


def end_job(migrated_url: str, client: TestClient, item: dict[str, str]) -> None:
    """End a conversion quickly: its original is missing, so it fails for good."""
    with pytest.raises(PermanentError):
        run_job(migrated_url, client, item)


@pytest.fixture(scope="module")
def tone(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    path: Path = tmp_path_factory.mktemp("admission") / "tone.mp3"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=35", "-ac", "1", "-b:a", "32k", str(path)],
        check=True, timeout=60,
    )  # fmt: skip
    return path.read_bytes()


# --- New audio per day ------------------------------------------------------------------


def test_new_audio_is_accepted_just_under_the_daily_limit(
    client: TestClient, migrated_url: str
) -> None:
    set_daily_count(migrated_url, learner_id(client), LIMIT_SECONDS - 1)

    assert start(client).status_code == 201


def test_at_the_exact_limit_a_new_file_is_refused_before_upload_with_the_reset_time(
    client: TestClient, migrated_url: str, storage: FakeStorage
) -> None:
    user = learner_id(client)
    set_daily_count(migrated_url, user, LIMIT_SECONDS)

    refused = start(client)

    assert refused.status_code == 429
    problem = refused.json()
    assert problem["code"] == "daily_audio_limit"
    assert problem["detail"].startswith(
        "You have added 120 minutes of new audio today, the daily limit. "
        "You can add more after midnight UTC, in "
    )
    assert datetime.fromisoformat(problem["resets_at"]) == next_utc_midnight()
    assert (problem["used_seconds"], problem["limit_seconds"]) == (LIMIT_SECONDS, LIMIT_SECONDS)
    seconds_left = (next_utc_midnight() - datetime.now(UTC)).total_seconds()
    assert abs(int(refused.headers["Retry-After"]) - seconds_left) < 5
    # Nothing was signed or recorded.
    assert storage.signed == []
    usage = client.get("/api/v1/uploads/usage").json()["daily_audio"]
    assert usage["used_seconds"] == LIMIT_SECONDS
    assert usage["can_add"] is False


def test_over_the_limit_a_new_file_is_refused(client: TestClient, migrated_url: str) -> None:
    set_daily_count(migrated_url, learner_id(client), LIMIT_SECONDS + 600)

    assert start(client).json()["code"] == "daily_audio_limit"


def test_confirming_is_refused_when_the_day_filled_up_after_the_upload_started(
    client: TestClient, migrated_url: str, storage: FakeStorage
) -> None:
    user = learner_id(client)
    target = start(client).json()
    storage.arrive(key_of(target), 1024)
    set_daily_count(migrated_url, user, LIMIT_SECONDS)

    refused = confirm(client, target["upload_id"])

    assert refused.status_code == 429
    assert refused.json()["code"] == "daily_audio_limit"
    assert client.get("/api/v1/contents").json()["items"] == []


def test_yesterdays_count_does_not_apply_today(client: TestClient, migrated_url: str) -> None:
    user = learner_id(client)
    yesterday = next_utc_midnight() - timedelta(days=2)
    set_daily_count(migrated_url, user, 10 * LIMIT_SECONDS, day=yesterday)

    assert start(client).status_code == 201
    usage = client.get("/api/v1/uploads/usage").json()["daily_audio"]
    assert usage["used_seconds"] == 0
    assert datetime.fromisoformat(usage["resets_at"]) == next_utc_midnight()


def test_clips_in_progress_hold_15_minutes_each(
    make_client: ClientFactory, storage: FakeStorage
) -> None:
    client = make_client(intake_daily_minutes=30)
    add(client, storage)
    add(client, storage)  # 30 of 30 minutes now held for clips not prepared yet

    refused = start(client)

    assert refused.status_code == 429
    assert refused.json()["detail"].startswith(
        "The clips you are adding now may use the rest of today's 30 minutes of new audio."
    )
    assert refused.json()["clips_in_progress"] == 2
    usage = client.get("/api/v1/uploads/usage").json()["daily_audio"]
    assert usage == {
        "used_seconds": 0,
        "limit_seconds": 30 * 60,
        "clips_in_progress": 2,
        "reserved_seconds": 30 * 60,
        "can_add": False,
        "resets_at": usage["resets_at"],
    }


def test_a_playable_clip_counts_its_length_and_frees_its_reservation(
    client: TestClient, storage: FakeStorage, migrated_url: str, tone: bytes
) -> None:
    user = learner_id(client)
    item = add(client, storage, tone)
    assert client.get("/api/v1/uploads/usage").json()["daily_audio"]["clips_in_progress"] == 1

    run_job(migrated_url, client, item)

    assert daily_count(migrated_url, user) == 35
    usage = client.get("/api/v1/uploads/usage").json()["daily_audio"]
    assert (usage["used_seconds"], usage["clips_in_progress"]) == (35, 0)

    # A repeated run counts nothing more.
    run_job(migrated_url, client, item)
    assert daily_count(migrated_url, user) == 35


def test_failed_and_duplicate_files_count_nothing(
    client: TestClient, storage: FakeStorage, migrated_url: str, tone: bytes
) -> None:
    user = learner_id(client)
    end_job(migrated_url, client, add(client, storage))  # its original is missing
    assert daily_count(migrated_url, user) == 0

    run_job(migrated_url, client, add(client, storage, tone))
    run_job(migrated_url, client, add(client, storage, tone))  # the same file again

    assert daily_count(migrated_url, user) == 35


def test_another_learner_is_not_affected_by_my_limit(
    make_client: ClientFactory, migrated_url: str
) -> None:
    mine, theirs = make_client(), make_client()
    set_daily_count(migrated_url, learner_id(mine), LIMIT_SECONDS)

    assert start(mine).status_code == 429
    assert start(theirs).status_code == 201
    assert client_usage(theirs)["used_seconds"] == 0


def client_usage(client: TestClient) -> dict[str, object]:
    usage: dict[str, object] = client.get("/api/v1/uploads/usage").json()["daily_audio"]
    return usage


def test_the_daily_limit_is_read_from_configuration(
    make_client: ClientFactory, migrated_url: str
) -> None:
    client = make_client(intake_daily_minutes=10)
    set_daily_count(migrated_url, learner_id(client), 10 * 60)

    assert start(client).json()["detail"].startswith("You have added 10 minutes of new audio")


# --- Two intakes on the shared lane, the rest in the learner's own queue -------------


def test_two_intakes_go_on_the_lane_and_a_third_waits_queued(
    client: TestClient, storage: FakeStorage, migrated_url: str
) -> None:
    user = learner_id(client)
    first, second, third = (add(client, storage) for _ in range(3))

    assert queued_jobs(migrated_url, user) == [first["upload_id"], second["upload_id"]]
    shown = client.get(f"/api/v1/contents/{third['content_id']}").json()
    assert (shown["status"], shown["stage"], shown["queue_position"]) == ("pending", "queued", 1)
    waiting = client.get(f"/api/v1/contents/{first['content_id']}").json()
    assert (waiting["stage"], waiting["queue_position"]) == ("waiting", None)
    library = {i["id"]: i for i in client.get("/api/v1/library/contents").json()["items"]}
    assert library[third["content_id"]]["stage"] == "queued"
    assert library[third["content_id"]]["queue_position"] == 1

    # When one of the two ends, the queued one goes on the lane.
    end_job(migrated_url, client, first)

    assert queued_jobs(migrated_url, user) == [second["upload_id"], third["upload_id"]]
    shown = client.get(f"/api/v1/contents/{third['content_id']}").json()
    assert (shown["stage"], shown["queue_position"]) == ("waiting", None)


def test_queued_clips_start_oldest_first_with_their_positions(
    client: TestClient, storage: FakeStorage, migrated_url: str
) -> None:
    user = learner_id(client)
    items = [add(client, storage) for _ in range(5)]

    positions = [
        client.get(f"/api/v1/contents/{item['content_id']}").json()["queue_position"]
        for item in items
    ]
    assert positions == [None, None, 1, 2, 3]

    end_job(migrated_url, client, items[0])
    end_job(migrated_url, client, items[1])

    assert queued_jobs(migrated_url, user) == [items[2]["upload_id"], items[3]["upload_id"]]
    assert client.get(f"/api/v1/contents/{items[4]['content_id']}").json()["queue_position"] == 1


def test_a_finished_conversion_starts_the_next_queued_clip(
    client: TestClient, storage: FakeStorage, migrated_url: str, tone: bytes
) -> None:
    user = learner_id(client)
    first = add(client, storage, tone)
    add(client, storage, name="two.mp3")
    third = add(client, storage, name="three.mp3")

    run_job(migrated_url, client, first)

    assert third["upload_id"] in queued_jobs(migrated_url, user)


def test_a_deleted_item_frees_its_place_on_the_lane(
    client: TestClient, storage: FakeStorage, migrated_url: str
) -> None:
    user = learner_id(client)
    first, _, third = (add(client, storage) for _ in range(3))
    with psycopg.connect(migrated_url) as conn:
        conn.execute("DELETE FROM content.contents WHERE id = %s", [first["content_id"]])

    run_job(migrated_url, client, first)  # skipped: the item is gone

    assert third["upload_id"] in queued_jobs(migrated_url, user)


def test_another_learners_clip_never_waits_behind_mine(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str
) -> None:
    mine, theirs = make_client(), make_client()
    for _ in range(4):
        add(mine, storage)

    their_item = add(theirs, storage)

    assert queued_jobs(migrated_url, learner_id(theirs)) == [their_item["upload_id"]]
    shown = theirs.get(f"/api/v1/contents/{their_item['content_id']}").json()
    assert shown["stage"] == "waiting"


def test_the_running_limit_is_read_from_configuration(
    make_client: ClientFactory, storage: FakeStorage, migrated_url: str
) -> None:
    client = make_client(intake_running_limit=1)
    add(client, storage)
    second = add(client, storage)

    assert len(queued_jobs(migrated_url, learner_id(client))) == 1
    assert client.get(f"/api/v1/contents/{second['content_id']}").json()["stage"] == "queued"


# --- Rate limit per IP -------------------------------------------------------------------


def test_upload_requests_are_limited_per_ip_across_learners(
    api_role_url: str, storage: FakeStorage
) -> None:
    app = create_app(Settings(database_url=api_role_url, log_json=False, upload_ip_limit=2))
    address = ("198.51.100.4", 5000)

    def sign_up(client: TestClient) -> TestClient:
        with_csrf(client)
        email = f"learner-{uuid.uuid4().hex}@example.com"
        registered = client.post(
            "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
        )
        assert registered.status_code == 201
        return client

    # Two learners behind one address; only the first client runs the app's lifespan.
    with TestClient(app, raise_server_exceptions=False, client=address) as first:
        app.state.uploads.storage = storage
        second = TestClient(app, raise_server_exceptions=False, client=address)
        sign_up(first)
        sign_up(second)

        assert start(first).status_code == 201
        assert start(second).status_code == 201
        limited = start(second)

    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"
    assert "Retry-After" in limited.headers
