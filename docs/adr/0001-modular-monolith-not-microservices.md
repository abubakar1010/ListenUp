# ADR 0001: Modular monolith, not microservices

- Status: Accepted
- Date: 2026-10-03
- Source: [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13)

## Context

ListenUp is built by one small team and deployed as one unit. The domain has clear areas (identity, content, practice modes, grading, AI) that must stay separable.

## Decision

Build one Python backend split into business modules under `listenup/modules/`. Modules call each other only through their `service.py`; `domain/` packages import no framework. CI enforces this with import-linter (Architecture 4.3).

## Consequences

One deploy, one database, simple local setup. A module can later be split into a service as a packaging change. Revisit when a module needs independent scaling, release cycle or ownership.
