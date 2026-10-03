"""The Blind step through the API (#62, #63, #65; FR-BL-1 to FR-BL-5; ADR 0024).

The app connects as the API role, so row-level security applies. The server's clock
is a fake the tests move by hand, so heartbeats can be judged without waiting. Media
goes to the fake storage, so nothing here needs S3.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from listenup.modules.blind.api import server_now
from tests.integration.intake_helpers import (
    ClientFactory,
    FakeStorage,
    client_factory,
    learner_id,
)

PASSAGE = {"start_ms": 10_000, "end_ms": 40_000}  # 30 s, the shortest passage
START, END = PASSAGE["start_ms"], PASSAGE["end_ms"]
SENTENCES_3 = "Cities plant trees on streets. Shade cools the air. Roots can break pipes."


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)

    def advance(self, ms: int) -> None:
        self.now += timedelta(milliseconds=ms)


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def make_client(api_role_url: str, storage: FakeStorage) -> Iterator[ClientFactory]:
    yield from client_factory(api_role_url, storage)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def client(make_client: ClientFactory, clock: Clock) -> TestClient:
    return with_clock(make_client(), clock)


def with_clock(client: TestClient, clock: Clock) -> TestClient:
    client.app.dependency_overrides[server_now] = lambda: clock.now  # type: ignore[attr-defined]
    return client


def add_clip(url: str, user: str) -> tuple[str, str]:
    """A playable 10-minute clip with its playback file; returns (content id, media id)."""
    media_id, content_id = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO content.media_objects (id, fingerprint, source, uploaded_by, status, "
            "duration_ms, playback_key, peaks_key) "
            "VALUES (%s, %s, 'upload', %s, 'playable', 600000, %s, %s)",
            [
                media_id,
                f"upload:{user}:{media_id}",
                user,
                f"users/{user}/media/{media_id}/playback.mp4",
                f"users/{user}/media/{media_id}/peaks.json",
            ],
        )
        conn.execute(
            "INSERT INTO content.contents (id, user_id, media_object_id, title) "
            "VALUES (%s, %s, %s, 'Why cities plant street trees')",
            [content_id, user, media_id],
        )
    return str(content_id), str(media_id)


def start_session(client: TestClient, migrated_url: str, entry: str = "blind") -> str:
    content_id, _ = add_clip(migrated_url, learner_id(client))
    response = client.post(
        "/api/v1/sessions", json={"content_id": content_id, "passage": PASSAGE, "entry": entry}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def start_attempt(client: TestClient, session_id: str) -> dict[str, object]:
    response = client.post(f"/api/v1/sessions/{session_id}/blind/attempts")
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def attempt_id(started: dict[str, object]) -> str:
    attempt = started["attempt"]
    assert isinstance(attempt, dict)
    return str(attempt["id"])


def beat(client: TestClient, attempt: str, position: int, state: str = "playing", **extra: object):
    response = client.post(
        f"/api/v1/blind/attempts/{attempt}/heartbeat",
        json={"position_ms": position, "state": state, **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()


def play(client: TestClient, clock: Clock, attempt: str, start: int, end: int) -> dict[str, object]:
    """Play from `start` to `end` in real time, one beat every 5 s; returns the last answer."""
    position = start
    answer: dict[str, object] = {}
    while position < end:
        step = min(5_000, end - position)
        clock.advance(step)
        position += step
        answer = beat(client, attempt, position, "ended" if position >= end else "playing")
        assert answer["action"] == "continue", answer
    return answer


def blind_step(client: TestClient, session_id: str) -> dict[str, object]:
    response = client.get(f"/api/v1/sessions/{session_id}/blind")
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


@pytest.fixture
def session_id(client: TestClient, migrated_url: str) -> str:
    return start_session(client, migrated_url)


# -- starting and the attempt-bound media (#62) ---------------------------------------


def test_starting_returns_an_attempt_with_its_own_media_url(
    client: TestClient, session_id: str
) -> None:
    started = start_attempt(client, session_id)

    attempt = started["attempt"]
    assert isinstance(attempt, dict)
    assert attempt["status"] == "active"
    assert attempt["position_ms"] == START
    assert (attempt["passage_start_ms"], attempt["passage_end_ms"]) == (START, END)
    assert attempt["listen_complete"] is False
    assert started["heartbeat_interval_ms"] == 5_000
    assert started["resume_delay_ms"] == 3_000
    assert str(started["media_url"]).startswith(f"/api/v1/blind/attempts/{attempt['id']}/media/")
    step = blind_step(client, session_id)
    assert step["step_status"] == "open"
    assert step["attempt"] == attempt


def test_one_attempt_is_live_at_a_time(client: TestClient, session_id: str) -> None:
    first = start_attempt(client, session_id)

    again = client.post(f"/api/v1/sessions/{session_id}/blind/attempts")

    assert again.status_code == 409
    assert again.json()["code"] == "attempt_active"
    assert again.json()["attempt_id"] == attempt_id(first)


def test_a_plan_without_blind_has_no_blind_attempts(client: TestClient, migrated_url: str) -> None:
    session_id = start_session(client, migrated_url, entry="dictation")

    response = client.post(f"/api/v1/sessions/{session_id}/blind/attempts")

    assert response.status_code == 409
    assert response.json()["code"] == "step_not_in_plan"


def test_the_media_url_redirects_to_storage_for_the_window_only(
    client: TestClient, session_id: str, storage: FakeStorage, clock: Clock
) -> None:
    started = start_attempt(client, session_id)

    response = client.get(str(started["media_url"]), follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["location"].startswith("http://storage.test/bucket/users/")
    key, ttl = storage.downloads[-1]
    assert key.endswith("/playback.mp4")
    # The passage's 30 s plus 60 s of grace: never the storage's default lifetime.
    assert ttl == 90

    clock.advance(30_000)
    client.get(str(started["media_url"]), follow_redirects=False)
    assert storage.downloads[-1][1] == 60

    clock.advance(60_000)
    expired = client.get(str(started["media_url"]), follow_redirects=False)
    assert expired.status_code == 410
    assert expired.json()["code"] == "media_expired"


def test_the_media_is_refused_with_another_token(client: TestClient, session_id: str) -> None:
    started = start_attempt(client, session_id)

    response = client.get(
        f"/api/v1/blind/attempts/{attempt_id(started)}/media/not-the-token", follow_redirects=False
    )

    assert response.status_code == 404
    assert response.json()["code"] == "media_not_found"


def test_the_media_is_refused_once_the_attempt_ended(client: TestClient, session_id: str) -> None:
    started = start_attempt(client, session_id)
    client.post(f"/api/v1/blind/attempts/{attempt_id(started)}/void", json={"reason": "left_page"})

    response = client.get(str(started["media_url"]), follow_redirects=False)

    assert response.status_code == 410
    assert response.json()["code"] == "media_expired"


def test_another_learner_gets_nothing(
    client: TestClient, session_id: str, make_client: ClientFactory, clock: Clock
) -> None:
    started = start_attempt(client, session_id)
    other = with_clock(make_client(), clock)
    attempt = attempt_id(started)

    assert other.get(f"/api/v1/sessions/{session_id}/blind").json()["code"] == "session_not_found"
    for response in (
        other.get(str(started["media_url"]), follow_redirects=False),
        other.post(
            f"/api/v1/blind/attempts/{attempt}/heartbeat",
            json={"position_ms": START, "state": "playing"},
        ),
        other.post(f"/api/v1/blind/attempts/{attempt}/void", json={"reason": "left_page"}),
        other.post(f"/api/v1/blind/attempts/{attempt}/gist", json={"text": SENTENCES_3}),
    ):
        assert response.status_code == 404
        assert response.json()["code"] == "attempt_not_found"
    assert blind_step(client, session_id)["attempt"] == started["attempt"]


# -- heartbeats (#63) -------------------------------------------------------------------


def test_beats_in_step_with_the_clock_continue(
    client: TestClient, session_id: str, clock: Clock
) -> None:
    attempt = attempt_id(start_attempt(client, session_id))

    answer = play(client, clock, attempt, START, START + 15_000)

    assert answer["attempt"]["position_ms"] == START + 15_000  # type: ignore[index]
    assert answer["attempt"]["status"] == "active"  # type: ignore[index]


@pytest.mark.parametrize(
    ("advance", "position", "extra", "reason"),
    [
        (5_000, START + 5_000, {"visible": False}, "left_page"),
        (5_000, START + 9_000, {}, "too_fast"),
        (20_000, START + 20_000, {}, "missed_heartbeat"),
        (5_000, START - 5_000, {}, "seek"),
        (5_000, END + 5_000, {}, "seek"),
        (
            7_000,
            START + 5_000,
            {"state": "interrupted", "interruption": "device", "interruption_ms": 6_000},
            "interrupted",
        ),
    ],
)
def test_a_refused_beat_voids_the_attempt(
    client: TestClient,
    session_id: str,
    clock: Clock,
    advance: int,
    position: int,
    extra: dict[str, object],
    reason: str,
) -> None:
    attempt = attempt_id(start_attempt(client, session_id))
    clock.advance(advance)

    answer = beat(client, attempt, position, **extra)

    assert answer["action"] == "stop"
    assert answer["attempt"]["status"] == "voided"
    assert answer["attempt"]["void_reason"] == reason
    assert blind_step(client, session_id)["attempt"]["void_reason"] == reason  # type: ignore[index]


def test_a_jump_backwards_is_a_seek(client: TestClient, session_id: str, clock: Clock) -> None:
    attempt = attempt_id(start_attempt(client, session_id))
    play(client, clock, attempt, START, START + 10_000)
    clock.advance(5_000)

    answer = beat(client, attempt, START + 2_000)

    assert answer["attempt"]["void_reason"] == "seek"


def test_buffering_under_20_seconds_does_not_void(
    client: TestClient, session_id: str, clock: Clock
) -> None:
    attempt = attempt_id(start_attempt(client, session_id))
    for _ in range(3):
        clock.advance(5_000)
        answer = beat(client, attempt, START, "buffering", buffering_ms=5_000)
        assert answer["action"] == "continue"

    answer = play(client, clock, attempt, START, START + 10_000)

    assert answer["attempt"]["status"] == "active"
    assert answer["attempt"]["resume_count"] == 0


def test_a_network_stall_resumes_once_from_three_seconds_before(
    client: TestClient, session_id: str, clock: Clock
) -> None:
    attempt = attempt_id(start_attempt(client, session_id))
    play(client, clock, attempt, START, START + 10_000)
    clock.advance(40_000)  # the beats could not get through

    answer = beat(client, attempt, START + 12_000, "interrupted", interruption="network")

    assert answer["action"] == "resume"
    assert answer["resume_from_ms"] == START + 9_000
    assert answer["resume_delay_ms"] == 3_000
    assert answer["attempt"]["resume_count"] == 1
    assert answer["attempt"]["resume_stop_ms"] == START + 12_000
    # Waiting for the audio, the 3 s count, then playing on from the resume point.
    clock.advance(2_000)
    assert beat(client, attempt, START + 9_000, "resuming")["action"] == "continue"
    answer = play(client, clock, attempt, START + 9_000, START + 20_000)
    assert answer["attempt"]["status"] == "active"


def test_a_second_interruption_voids(client: TestClient, session_id: str, clock: Clock) -> None:
    attempt = attempt_id(start_attempt(client, session_id))
    play(client, clock, attempt, START, START + 5_000)
    clock.advance(1_000)
    assert (
        beat(client, attempt, START + 6_000, "interrupted", interruption="device")["action"]
        == "resume"
    )
    play(client, clock, attempt, START + 3_000, START + 13_000)
    clock.advance(1_000)

    answer = beat(client, attempt, START + 14_000, "interrupted", interruption="network")

    assert answer["action"] == "stop"
    assert answer["attempt"]["void_reason"] == "interrupted"


def test_a_beat_after_the_attempt_ended_says_stop(
    client: TestClient, session_id: str, clock: Clock
) -> None:
    attempt = attempt_id(start_attempt(client, session_id))
    client.post(f"/api/v1/blind/attempts/{attempt}/void", json={"reason": "reload"})
    clock.advance(5_000)

    answer = beat(client, attempt, START + 5_000)

    assert answer["action"] == "stop"
    assert answer["attempt"]["void_reason"] == "reload"


def test_leaving_the_page_voids_and_a_new_attempt_can_start(
    client: TestClient, session_id: str, clock: Clock, migrated_url: str
) -> None:
    attempt = attempt_id(start_attempt(client, session_id))
    clock.advance(4_000)
    beat(client, attempt, START + 4_000)

    with psycopg.connect(migrated_url, autocommit=True) as listener:
        listener.execute("LISTEN user_events")
        response = client.post(
            f"/api/v1/blind/attempts/{attempt}/void", json={"reason": "left_page"}
        )
        events = [json.loads(n.payload) for n in listener.notifies(timeout=2, stop_after=1)]

    assert response.status_code == 200
    assert response.json()["status"] == "voided"
    assert response.json()["void_reason"] == "left_page"
    assert response.json()["position_ms"] == START + 4_000
    assert events == [
        {"u": learner_id(client), "t": "attempt.voided", "r": attempt},
    ]
    restarted = start_attempt(client, session_id)
    assert attempt_id(restarted) != attempt
    assert blind_step(client, session_id)["attempt"] == restarted["attempt"]


def test_the_browser_cannot_report_a_server_reason(client: TestClient, session_id: str) -> None:
    attempt = attempt_id(start_attempt(client, session_id))

    response = client.post(f"/api/v1/blind/attempts/{attempt}/void", json={"reason": "too_fast"})

    assert response.status_code == 422


# -- the gist (#65) ---------------------------------------------------------------------


def gist(client: TestClient, attempt: str, text: str, key: str | None = None) -> httpx.Response:
    return client.post(
        f"/api/v1/blind/attempts/{attempt}/gist",
        json={"text": text},
        headers={"Idempotency-Key": key} if key else {},
    )


def test_the_gist_is_refused_before_the_whole_passage_played(
    client: TestClient, session_id: str, clock: Clock
) -> None:
    attempt = attempt_id(start_attempt(client, session_id))
    play(client, clock, attempt, START, START + 20_000)

    response = gist(client, attempt, SENTENCES_3)

    assert response.status_code == 409
    assert response.json()["code"] == "listen_incomplete"


def test_a_forged_end_position_is_too_fast_and_gets_no_gist(
    client: TestClient, session_id: str, clock: Clock
) -> None:
    attempt = attempt_id(start_attempt(client, session_id))
    clock.advance(5_000)

    answer = beat(client, attempt, END, "ended")

    assert answer["attempt"]["void_reason"] == "too_fast"
    assert gist(client, attempt, SENTENCES_3).json()["code"] == "attempt_closed"


def test_two_sentences_are_refused_and_three_complete_the_step(
    client: TestClient, session_id: str, clock: Clock
) -> None:
    attempt = attempt_id(start_attempt(client, session_id))
    answer = play(client, clock, attempt, START, END)
    assert answer["attempt"]["listen_complete"] is True

    short = gist(client, attempt, "Cities plant trees on streets. Shade cools the air.")
    assert short.status_code == 422
    assert short.json()["code"] == "gist_too_short"
    assert short.json()["sentences"] == 2
    assert short.json()["detail"] == "2 of 3 sentences. Write one more, then submit."

    done = gist(client, attempt, f"  {SENTENCES_3}\n", key="gist-1")

    assert done.status_code == 201, done.text
    body = done.json()
    assert body["attempt"]["status"] == "submitted"
    assert body["attempt"]["gist_text"] == SENTENCES_3
    assert body["open_step"] == "transcript"
    session = client.get(f"/api/v1/sessions/{session_id}").json()
    assert session["steps"][0] == {"step": "blind", "position": 1, "status": "done"}
    assert session["open_step"] == "transcript"
    assert session["version"] == body["session_version"]
    assert blind_step(client, session_id)["step_status"] == "done"


def test_the_same_idempotency_key_submits_one_gist(
    client: TestClient, session_id: str, clock: Clock
) -> None:
    attempt = attempt_id(start_attempt(client, session_id))
    play(client, clock, attempt, START, END)

    first = gist(client, attempt, SENTENCES_3, key="gist-1")
    again = gist(client, attempt, SENTENCES_3, key="gist-1")
    other_key = gist(client, attempt, SENTENCES_3, key="gist-2")

    assert first.status_code == again.status_code == 201
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json() == first.json()
    assert other_key.status_code == 409
    assert other_key.json()["code"] == "attempt_closed"


def test_leaving_after_the_whole_passage_keeps_the_attempt(
    client: TestClient, session_id: str, clock: Clock
) -> None:
    """The gist form is safe to leave: a reload shows it again (final UI D04)."""
    attempt = attempt_id(start_attempt(client, session_id))
    play(client, clock, attempt, START, END)

    left = client.post(f"/api/v1/blind/attempts/{attempt}/void", json={"reason": "reload"})

    assert left.json()["status"] == "active"
    assert left.json()["void_reason"] is None
    step = blind_step(client, session_id)["attempt"]
    assert step["listen_complete"] is True  # type: ignore[index]
    clock.advance(600_000)  # the draft may wait; the server time only grows
    assert gist(client, attempt, SENTENCES_3).status_code == 201


def test_a_long_gist_is_refused(client: TestClient, session_id: str, clock: Clock) -> None:
    attempt = attempt_id(start_attempt(client, session_id))
    play(client, clock, attempt, START, END)

    response = gist(client, attempt, "Trees are good. " * 200)

    assert response.status_code == 422
    assert response.json()["code"] == "gist_too_long"
