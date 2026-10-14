"""Wait for irreversible work to settle before propagating cancellation."""

import asyncio
from collections.abc import Awaitable

import anyio


async def finish_on_cancel[T](operation: Awaitable[T]) -> T:
    """Shield a retained task and drain it even when the caller is cancelled again.

    A cancelled caller still receives cancellation, including when the operation
    failed during draining. Preserve that failure as its cause for reconciliation.
    """
    task = asyncio.ensure_future(operation)
    cancelled: asyncio.CancelledError | None = None
    with anyio.CancelScope(shield=True):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as error:
                cancelled = error
            except Exception:
                break
    if cancelled is not None:
        if task.cancelled():
            try:
                task.result()
            except asyncio.CancelledError as inner:
                failure = inner.__cause__
        else:
            failure = task.exception()
        raise cancelled from failure
    return task.result()
