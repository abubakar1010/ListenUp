# ADR 0002: Python for the API and the workers

- Status: Accepted
- Date: 2026-10-03
- Source: [Software Architecture, section 13.1](https://claude.ai/code/artifact/6a30920f-b6a0-4131-a486-f2044c71bb13)

## Context

Speech and media tooling (Whisper-family transcription, forced alignment, phoneme models, Praat, yt-dlp) is Python-first.

## Decision

Write the API (FastAPI, Pydantic v2, SQLAlchemy 2) and the workers in Python 3.12, in one package.

## Consequences

One backend language and shared domain code between API and workers. Type safety comes from mypy in strict mode.
