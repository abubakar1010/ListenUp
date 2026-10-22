"""#67: real queue locks, shared cache and AI boundary validation."""

import asyncio
import json
import shutil
import uuid

import httpx
import procrastinate
import psycopg
import pytest
from sqlalchemy import text

from listenup.ai import prompt_files, text_tasks
from listenup.ai.accounting import PostgresAccounting
from listenup.ai.config import AIConfig, ProviderEntry
from listenup.ai.gateway import AIGateway
from listenup.ai.ports import Role
from listenup.ai.prompt_files import PROMPTS_DIR
from listenup.ai.providers.openai_compatible import OpenAICompatibleTextAI, version_for
from listenup.ai.registry import Registry
from listenup.modules.grading import jobs, service
from listenup.modules.practice import service as practice
from listenup.modules.transcript import jobs as transcription
from listenup.modules.transcript import service as transcript
from listenup.platform.database import Database
from listenup.platform.errors import ProblemError
from listenup.platform.jobs import (
    JobDeps,
    Lane,
    PermanentError,
    app,
    configure_runtime,
    enqueue,
    run_handler,
)
from tests.integration.conftest import conninfo_to_url
from tests.integration.dictation_helpers import REFERENCE_TEXT, seed_transcript
from tests.integration.seed import add_clip, create_learner
from tests.integration.test_key_points import POINTS
from tests.integration.test_key_points import insert as insert_cache


@pytest.fixture
async def database(migrated_url):
    with psycopg.connect(migrated_url) as conn:
        conn.execute("DELETE FROM procrastinate.procrastinate_jobs")
    database = Database(conninfo_to_url(migrated_url))
    configure_runtime(database)
    with app.replace_connector(procrastinate.PsycopgConnector(conninfo=migrated_url)):
        async with app.open_async():
            yield database
    await database.dispose()


@pytest.fixture
def clip(migrated_url, learner):
    media, content, _ = add_clip(migrated_url, learner)
    seed_transcript(migrated_url, media)
    return media, content


@pytest.fixture
def ai(database, monkeypatch):
    class Server:
        def __init__(self):
            self.calls = 0
            self.output = {
                "key_points": [{k: v for k, v in p.items() if k != "id"} for p in POINTS]
            }
            self.inputs = []
            self.entered = None
            self.release = None
            self.before_reply = None
            self.prompts_root = PROMPTS_DIR

        async def __call__(self, request):
            self.calls += 1
            self.inputs.append(json.loads(request.content))
            if self.entered is not None:
                self.entered.set()
                await self.release.wait()
            if self.before_reply is not None:
                self.before_reply()
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": json.dumps(self.output)}, "finish_reason": "stop"}
                    ]
                },
            )

    server = Server()
    provider = "p" + uuid.uuid4().hex
    entry = ProviderEntry(
        provider=provider,
        model="text-model",
        local=True,
        trains_on_inputs=False,
        accepted=True,
        retries=0,
        options={"base_url": "http://127.0.0.1:11434/v1"},
    )
    gateway = AIGateway(
        AIConfig(version=1, roles={Role.TEXT_AI: (entry,)}),
        registry=Registry(
            text_ai={
                provider: lambda e: OpenAICompatibleTextAI(
                    e, transport=httpx.MockTransport(server), prompts_root=server.prompts_root
                )
            },
            versions={provider: version_for},
        ),
        accounting=PostgresAccounting(database),
    )
    monkeypatch.setattr(jobs, "get_gateway", lambda: gateway)
    return server


async def start(database, learner, content, left=0, right=120000):
    async with database.transaction(learner) as db:
        return await practice.start_plan(db, learner, content, left, right, practice.Entry.BLIND)


async def ready(database, learner, session):
    async with database.transaction(learner) as db:
        await transcript.announce_ready(db, learner, session.id)


async def work():
    await app.run_worker_async(
        queues=[Lane.AI.value], wait=False, concurrency=2, install_signal_handlers=False
    )


def stored(url, media):
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT prompt_version, points, provider_info FROM grading.key_points "
            "WHERE media_object_id=%s ORDER BY prompt_version",
            [media],
        ).fetchall()


def queued(url):
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT queue_name, lock, args, status::text FROM procrastinate.procrastinate_jobs "
            "WHERE task_name='grading.extract_key_points' ORDER BY id"
        ).fetchall()


@pytest.mark.anyio
async def test_transcript_ready_enqueues_extraction_before_blind_submission(
    database, migrated_url, learner, clip, ai
):
    session = await start(database, learner, clip[1])
    await transcription.transcribe_passage(
        JobDeps(database, None, 1), str(session.id), str(learner)
    )
    assert len(queued(migrated_url)) == 1
    assert queued(migrated_url)[0][0] == "ai"
    await work()
    rows = stored(migrated_url, clip[0])
    assert len(rows) == 1
    assert rows[0][0:2] == ("v1", POINTS)
    assert rows[0][2]["model"] == "text-model"
    assert rows[0][2]["provider"].startswith("p")
    assert rows[0][2]["version"] == "openai-chat-v1; structured=json_schema"
    assert ai.calls == 1
    assert REFERENCE_TEXT in ai.inputs[0]["messages"][1]["content"]
    assert str(learner) not in json.dumps(ai.inputs)
    async with database.transaction(learner) as db:
        await practice.require_step(db, session.id, practice.Step.BLIND)


@pytest.mark.anyio
async def test_two_learners_share_one_ai_call(database, migrated_url, learner, clip, ai):
    other = create_learner(migrated_url)
    other_content = uuid.uuid4()
    try:
        with psycopg.connect(migrated_url) as conn:
            conn.execute(
                "UPDATE content.media_objects SET source='youtube', uploaded_by=NULL, "
                "fingerprint=%s WHERE id=%s",
                [f"youtube:{clip[0]}", clip[0]],
            )
            conn.execute(
                "INSERT INTO content.contents (id,user_id,media_object_id,title) "
                "VALUES (%s,%s,%s,'Shared')",
                [other_content, other, clip[0]],
            )
        first = await start(database, learner, clip[1])
        second = await start(database, other, other_content)
        async with asyncio.timeout(5):
            await asyncio.gather(ready(database, learner, first), ready(database, other, second))
        assert len(queued(migrated_url)) == 1
        # A second copy without producer deduplication proves the execution lock too.
        row = queued(migrated_url)[0]
        async with database.transaction() as db:
            await enqueue(db, service.EXTRACT_KEY_POINTS, lock=row[1], **row[2])
        ai.entered, ai.release = asyncio.Event(), asyncio.Event()
        worker = asyncio.create_task(work())
        try:
            async with asyncio.timeout(5):
                await ai.entered.wait()
                states = [r[3] for r in queued(migrated_url)]
                assert sorted(states) == ["doing", "todo"]
        finally:
            ai.release.set()
            await worker
        await work()  # wait=False consumers may exit while the other job holds the lock
        assert ai.calls == 1
        assert len(stored(migrated_url, clip[0])) == 1
        assert [r[3] for r in queued(migrated_url)] == ["succeeded", "succeeded"]
        await ready(database, other, second)
        await work()
        assert ai.calls == 1
        with psycopg.connect(migrated_url) as conn:
            conn.execute("DELETE FROM content.contents WHERE id=%s", [clip[1]])
        assert len(stored(migrated_url, clip[0])) == 1
    finally:
        with psycopg.connect(migrated_url) as conn:
            conn.execute("DELETE FROM identity.users WHERE id=%s", [other])
            conn.execute("DELETE FROM content.contents WHERE id=%s", [clip[1]])
            conn.execute("DELETE FROM content.media_objects WHERE id=%s", [clip[0]])


@pytest.mark.anyio
@pytest.mark.parametrize(
    "points",
    [
        POINTS[:2],
        POINTS + POINTS + POINTS[:1],
        [POINTS[1], POINTS[0], POINTS[2]],
        [POINTS[0], POINTS[0], POINTS[2]],
    ],
)
async def test_rejects_invalid_points_and_retries(
    database, migrated_url, learner, clip, ai, points
):
    session = await start(database, learner, clip[1])
    await ready(database, learner, session)
    valid = ai.output
    ai.output = {"key_points": [{k: v for k, v in p.items() if k != "id"} for p in points]}
    await work()
    assert stored(migrated_url, clip[0]) == []
    assert queued(migrated_url)[0][3] == "todo"
    ai.output = valid
    async with database.transaction() as db:
        await db.execute(
            text(
                "UPDATE procrastinate.procrastinate_jobs SET scheduled_at=now() "
                "WHERE task_name='grading.extract_key_points'"
            )
        )
    await work()
    assert ai.calls == 2
    assert stored(migrated_url, clip[0])[0][1] == POINTS


@pytest.mark.anyio
async def test_retry_after_commit_does_not_call_ai_again(database, migrated_url, learner, clip, ai):
    session = await start(database, learner, clip[1])
    await ready(database, learner, session)
    args = queued(migrated_url)[0][2]
    await run_handler(service.EXTRACT_KEY_POINTS, JobDeps(database, None, 1), **args)
    await run_handler(service.EXTRACT_KEY_POINTS, JobDeps(database, None, 2), **args)
    assert ai.calls == 1
    assert len(stored(migrated_url, clip[0])) == 1


@pytest.mark.anyio
async def test_ready_hook_checks_ownership_and_rolls_back_its_job(
    database, migrated_url, learner, clip
):
    session = await start(database, learner, clip[1])
    other = uuid.uuid4()
    async with database.transaction(other) as db:
        with pytest.raises(ProblemError) as error:
            await service.on_transcript_ready(db, other, session.id)
    assert error.value.status == 404
    with pytest.raises(RuntimeError):
        async with database.transaction(learner) as db:
            await service.on_transcript_ready(db, learner, session.id)
            raise RuntimeError("rollback")
    assert queued(migrated_url) == []


@pytest.mark.anyio
async def test_deleted_media_is_not_resurrected_after_ai(database, migrated_url, learner, clip, ai):
    session = await start(database, learner, clip[1])
    await ready(database, learner, session)

    def remove():
        with psycopg.connect(migrated_url) as conn:
            conn.execute("DELETE FROM content.contents WHERE id=%s", [clip[1]])
            conn.execute("DELETE FROM content.media_objects WHERE id=%s", [clip[0]])

    ai.before_reply = remove
    await work()
    assert ai.calls == 1
    assert stored(migrated_url, clip[0]) == []
    assert queued(migrated_url)[0][3] == "succeeded"


@pytest.mark.anyio
async def test_missing_transcript_retries_without_calling_ai(
    database, migrated_url, learner, clip, ai
):
    session = await start(database, learner, clip[1])
    await ready(database, learner, session)
    with psycopg.connect(migrated_url) as conn:
        conn.execute("DELETE FROM content.passage_transcripts WHERE media_object_id=%s", [clip[0]])
    await work()
    assert ai.calls == 0
    assert queued(migrated_url)[0][3] == "todo"


def test_worker_registers_key_point_jobs():
    from listenup.worker import JOB_MODULES

    assert "listenup.modules.grading.jobs" in JOB_MODULES


@pytest.mark.anyio
async def test_prompt_version_selects_a_distinct_cache_entry(
    database, migrated_url, learner, clip, ai, monkeypatch, tmp_path
):
    root = tmp_path / "prompts"
    shutil.copytree(PROMPTS_DIR, root)
    monkeypatch.setattr(text_tasks, "PROMPTS_DIR", root)
    monkeypatch.setattr(prompt_files, "PROMPTS_DIR", root)
    ai.prompts_root = root
    session = await start(database, learner, clip[1])
    await ready(database, learner, session)
    await work()
    old = root / "extract_key_points" / "v1.md"
    old.write_text(old.read_text().replace("status: active", "status: retired"))
    (root / "extract_key_points" / "v2.md").write_text(
        old.read_text()
        .replace("version: v1", "version: v2")
        .replace("status: retired", "status: active")
    )
    shutil.copyfile(
        root / "extract_key_points" / "v1.schema.json",
        root / "extract_key_points" / "v2.schema.json",
    )
    await ready(database, learner, session)
    await work()
    assert ai.calls == 2
    assert [r[0] for r in stored(migrated_url, clip[0])] == ["v1", "v2"]
    await ready(database, learner, session)
    await work()
    assert ai.calls == 2


@pytest.mark.anyio
async def test_an_empty_transcript_never_calls_ai(database, migrated_url, learner, clip, ai):
    with psycopg.connect(migrated_url) as conn:
        conn.execute(
            "UPDATE content.passage_transcripts SET words='{}', start_ms='{}', "
            "end_ms='{}', confidence='{}', sentence_starts='{}' WHERE media_object_id=%s",
            [clip[0]],
        )
    session = await start(database, learner, clip[1])
    await ready(database, learner, session)
    await work()
    assert ai.calls == 0
    assert stored(migrated_url, clip[0]) == []
    assert queued(migrated_url)[0][3] == "failed"


@pytest.mark.anyio
async def test_extraction_uses_only_original_words_in_the_selected_span(
    database, migrated_url, learner, clip, ai
):
    # 30 s passage: padding starts before it and a word exactly at the end is excluded.
    words = ["BEFORE", "Original", "words.", "AFTER"]
    with psycopg.connect(migrated_url) as conn:
        transcript_id = conn.execute(
            "UPDATE content.passage_transcripts SET words=%s, start_ms=%s, end_ms=%s, "
            "confidence=%s, sentence_starts=ARRAY[0] WHERE media_object_id=%s RETURNING id",
            [words, [9999, 10000, 39999, 40000], [10000, 11000, 40000, 41000], [900] * 4, clip[0]],
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO content.transcript_corrections "
            "(user_id,passage_transcript_id,word_index,corrected_text) "
            "VALUES (%s,%s,1,'Private correction')",
            [learner, transcript_id],
        )
    session = await start(database, learner, clip[1], 10000, 40000)
    await ready(database, learner, session)
    await work()
    data = ai.inputs[0]["messages"][1]["content"]
    assert "Original words." in data
    assert all(word not in data for word in ("BEFORE", "AFTER", "Private correction"))
    async with database.transaction() as db:
        span = await db.scalar(
            text("SELECT span::text FROM grading.key_points WHERE media_object_id=:media"),
            {"media": clip[0]},
        )
    assert span == "[10000,40000)"


@pytest.mark.anyio
async def test_retry_exhaustion_keeps_blind_open_and_stores_no_partial_points(
    database, migrated_url, learner, clip, ai
):
    session = await start(database, learner, clip[1])
    await ready(database, learner, session)
    ai.output = {"key_points": []}
    for _ in range(4):
        async with database.transaction() as db:
            await db.execute(
                text(
                    "UPDATE procrastinate.procrastinate_jobs SET scheduled_at=now() "
                    "WHERE task_name='grading.extract_key_points'"
                )
            )
        await work()
    assert ai.calls == 4
    assert stored(migrated_url, clip[0]) == []
    assert queued(migrated_url)[0][3] == "failed"
    async with database.transaction(learner) as db:
        await practice.require_step(db, session.id, practice.Step.BLIND)


@pytest.mark.anyio
async def test_deleted_media_before_execution_never_calls_ai(
    database, migrated_url, learner, clip, ai
):
    session = await start(database, learner, clip[1])
    await ready(database, learner, session)
    with psycopg.connect(migrated_url) as conn:
        conn.execute("DELETE FROM content.contents WHERE id=%s", [clip[1]])
        conn.execute("DELETE FROM content.media_objects WHERE id=%s", [clip[0]])
    await work()
    assert ai.calls == 0
    assert queued(migrated_url)[0][3] == "succeeded"


@pytest.mark.anyio
@pytest.mark.parametrize("count", [3, 6])
async def test_stores_the_valid_point_count_boundaries(
    database, migrated_url, learner, clip, ai, count
):
    ai.output = {
        "key_points": [
            {"kind": "main" if i == 0 else "supporting", "text": f"Point number {i}."}
            for i in range(count)
        ]
    }
    session = await start(database, learner, clip[1])
    await ready(database, learner, session)
    await work()
    points = stored(migrated_url, clip[0])[0][1]
    assert len(points) == count
    assert [p["id"] for p in points] == [f"kp{i}" for i in range(1, count + 1)]


@pytest.mark.anyio
async def test_unrelated_integrity_error_is_retried(
    database, migrated_url, learner, clip, ai, monkeypatch
):
    from listenup.modules.grading import repository

    other_media, _, _ = add_clip(migrated_url, learner)
    with psycopg.connect(migrated_url) as conn:
        insert_cache(conn, other_media)
        collision = conn.execute(
            "SELECT id FROM grading.key_points WHERE media_object_id=%s", [other_media]
        ).fetchone()[0]
    monkeypatch.setattr(repository, "uuid7", lambda: collision)
    session = await start(database, learner, clip[1])
    await ready(database, learner, session)
    await work()
    assert queued(migrated_url)[0][3] == "todo"
    assert stored(migrated_url, clip[0]) == []
    assert len(stored(migrated_url, other_media)) == 1
    assert ai.calls == 1


@pytest.mark.anyio
async def test_invalid_job_bounds_are_permanent_without_an_ai_call(database, clip, ai):
    with pytest.raises(PermanentError):
        await jobs.extract_key_points(JobDeps(database, None, 1), str(clip[0]), 1000, 1000)
    assert ai.calls == 0
