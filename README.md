# ListenUp

A web app for practising English listening. A learner adds a clip and works through a fixed plan: Blind, Dictation, Transcript, Card and Shadow.

## Repository layout

| Path | Contents |
| --- | --- |
| `apps/web` | React + TypeScript client (Vite) |
| `apps/api` | Python package `listenup`: FastAPI API and Procrastinate workers |
| `infra/docker`, `infra/compose` | Docker images and the local Compose stack |
| `ai-evals` | Golden sets for evaluating AI providers |
| `docs/adr` | Architecture decision records |

## Getting started

```sh
docker compose up --build          # database, storage, email, API and workers
cd apps/web && pnpm install && pnpm dev   # web client on http://localhost:5173
```

The API health check is at http://localhost:8000/api/v1/health. Development commands, design documents and contribution rules are in [CLAUDE.md](CLAUDE.md).
