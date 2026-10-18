"""Boundary fake only: actual quota decisions are tested against PostgreSQL."""

from datetime import UTC, datetime
from uuid import uuid4

from listenup.ai.accounting import Ticket


class FakeAccounting:
    def __init__(self):
        self.calls = []
        self.exhausted = set()
        self.ratio = 1.0
        self.tickets = {}

    async def admit(self, entry, role, task, prompt, budget, routine, **metadata):
        if entry.provider in self.exhausted:
            await self.skip(entry, role, task, prompt, "quota")
            return None
        ticket = Ticket(uuid4(), datetime.now(UTC), entry.provider)
        row = dict(
            provider=entry.provider,
            task=task,
            prompt=prompt,
            budget=budget,
            routine=routine,
            outcome="pending",
        )
        row.update(metadata)
        self.calls.append(row)
        self.tickets[ticket.id] = row
        return ticket

    async def finish(self, ticket, outcome, latency_ms, version, usage):
        self.tickets[ticket.id].update(outcome=outcome, version=version, usage=usage)

    async def skip(self, entry, role, task, prompt, outcome):
        self.calls.append(dict(provider=entry.provider, task=task, prompt=prompt, outcome=outcome))

    async def remaining(self, entry):
        return self.ratio
