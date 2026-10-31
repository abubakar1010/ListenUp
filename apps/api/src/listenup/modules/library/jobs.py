"""Storage-first content cleanup with durable retry manifests (DR-2, ADR 0085)."""

import uuid
from typing import Any

from listenup.modules.cards import service as cards
from listenup.modules.content import service as content
from listenup.modules.identity import service as identity
from listenup.modules.practice import service as practice
from listenup.modules.shadow import service as shadow
from listenup.platform.idempotency import forget_resource_responses
from listenup.platform.jobs import JobDeps, Lane, enqueue, job
from listenup.platform.storage import get_storage

DELETE_CONTENT = "library.delete_content"
DELETE_SESSION = "library.delete_session"

identity.on_account_purge(content.require_no_media_writes)


async def give_up(deps: JobDeps, request_id: str) -> None:
    async with deps.database.transaction() as db:
        await identity.fail_content_deletion(db, uuid.UUID(request_id))


@job(Lane.BACKGROUND, DELETE_CONTENT, on_give_up=give_up)
async def delete_content(deps: JobDeps, request_id: str) -> dict[str, Any] | None:
    request = uuid.UUID(request_id)
    storage = get_storage()
    async with deps.database.transaction() as db:
        state = await identity.content_deletion_state(db, request)
        if state is None:
            return None
        learner, target = state["subject_user_id"], state["target_id"]
        report = dict(state["report"] or {})
        media = uuid.UUID(report["media_id"])
        # Account deletion uses the same guard. A retained registration is a pointer
        # to a possibly unfinished object and must not be discarded on timeout.
        await content.require_no_media_writes(db, learner, media)
        sessions = await practice.content_deletion_sessions(db, learner, target)
        card_prefixes, _ = await cards.content_deletion_objects(
            db, learner, sessions, report["card_prefixes"]
        )
        prefixes = sorted(
            set(state["storage_prefixes"])
            | set(card_prefixes)
            | set(await shadow.content_deletion_prefixes(learner, sessions))
        )
        report["card_prefixes"] = sorted(set(report["card_prefixes"]) | set(card_prefixes))
        resources = {str(target), str(media), *report.get("resource_ids", [])}
        resources.update(
            str(value)
            for value in await practice.content_deletion_resource_ids(db, learner, sessions)
        )
        resources.update(
            prefix.rstrip("/").rsplit("/", 1)[-1] for prefix in report["card_prefixes"]
        )
        report["resource_ids"] = sorted(resources)

        await identity.store_content_deletion(
            db,
            request,
            "pending" if state["status"] == "failed" else state["status"],
            report,
            prefixes,
        )
    # Manifest commits before external effects. Retried deletes of absent keys work.
    for prefix in prefixes:
        report["objects_removed"] += await storage.delete_prefix(prefix)
    for key in report["keys"]:
        await storage.delete(key)
    async with deps.database.transaction() as db:
        state = await identity.content_deletion_state(db, request)
        if state is None:
            return None
        if state["status"] != "completed":
            await content.require_no_media_writes(db, learner, media)
            removed = await forget_resource_responses(db, learner, set(report["resource_ids"]))
            await content.remove_deleted_content(db, learner, target, media, report["source"])
            removed += await forget_resource_responses(db, learner, set(report["resource_ids"]))
            report["replay_responses_removed"] = removed

        await cards.settle_content_deletion(db, learner, report.get("card_prefixes", []))
        await identity.store_content_deletion(db, request, "completed", report, prefixes)
    return report


@job(Lane.BACKGROUND, "library.reconcile_content_deletions", schedule="* * * * *")
async def reconcile_content_deletions(deps: JobDeps, timestamp: int | None = None) -> None:
    """Recover exhausted jobs and remove late signed uploads using retained manifests."""
    async with deps.database.transaction() as db:
        for request in await identity.content_deletions_to_reconcile(db):
            await enqueue(
                db,
                DELETE_CONTENT,
                unique_key=f"content-delete:{request}",
                lock=f"content-delete:{request}",
                request_id=str(request),
            )
        # Session deletions (#90) keep their manifests the same way.
        for request in await identity.content_deletions_to_reconcile(db, "session"):
            await enqueue(
                db,
                DELETE_SESSION,
                unique_key=f"session-delete:{request}",
                lock=f"session-delete:{request}",
                request_id=str(request),
            )


async def give_up_session(deps: JobDeps, request_id: str) -> None:
    async with deps.database.transaction() as db:
        await identity.fail_content_deletion(db, uuid.UUID(request_id), "session")


@job(Lane.BACKGROUND, DELETE_SESSION, on_give_up=give_up_session)
async def delete_session(deps: JobDeps, request_id: str) -> dict[str, Any] | None:
    """Delete one session's objects, then its rows (AT-20, FR-SH-17, ADR 0092).

    Like content deletion: the manifest commits first, storage runs with no transaction
    (so no row lock is held), and a short second transaction removes the rows.
    """
    request = uuid.UUID(request_id)
    storage = get_storage()
    async with deps.database.transaction() as db:
        state = await identity.content_deletion_state(db, request, "session")
        if state is None:
            return None
        learner, target = state["subject_user_id"], state["target_id"]
        # Re-hide in case a schema rollback dropped the barrier (ADR 0092).
        await practice.hide_for_deletion(db, target)
        sessions = [target]
        report = dict(state["report"] or {})
        # Card writers drain first (Reschedule); their manifest outlives the cards.
        card_prefixes, _ = await cards.content_deletion_objects(
            db, learner, sessions, report["card_prefixes"]
        )
        prefixes = sorted(
            set(state["storage_prefixes"])
            | set(card_prefixes)
            | set(await shadow.content_deletion_prefixes(learner, sessions))
        )
        report["card_prefixes"] = sorted(set(report["card_prefixes"]) | set(card_prefixes))
        resources = {str(target), *report.get("resource_ids", [])}
        resources.update(
            str(value)
            for value in await practice.content_deletion_resource_ids(db, learner, sessions)
        )
        resources.update(
            prefix.rstrip("/").rsplit("/", 1)[-1] for prefix in report["card_prefixes"]
        )
        report["resource_ids"] = sorted(resources)
        await identity.store_content_deletion(
            db,
            request,
            "pending" if state["status"] == "failed" else state["status"],
            report,
            prefixes,
        )
    for prefix in prefixes:
        report["objects_removed"] += await storage.delete_prefix(prefix)
    async with deps.database.transaction() as db:
        state = await identity.content_deletion_state(db, request, "session")
        if state is None:
            return None
        if state["status"] != "completed":
            removed = await forget_resource_responses(db, learner, set(report["resource_ids"]))
            await practice.remove_deleted_session(db, learner, target)
            removed += await forget_resource_responses(db, learner, set(report["resource_ids"]))
            report["replay_responses_removed"] = removed
        await cards.settle_content_deletion(db, learner, report.get("card_prefixes", []))
        await identity.store_content_deletion(db, request, "completed", report, prefixes)
    return report
