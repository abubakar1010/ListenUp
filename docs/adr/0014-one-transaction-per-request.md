# ADR 0014: One transaction per request, committed before the response

- Status: Accepted
- Date: 2026-10-03

## Context

The platform package (#25) gives every module the same database, error, idempotency and rate-limit behaviour. Three choices in it change how features must be written, and each has a failure mode that is easy to miss.

## Decision

- **One transaction per request.** Route handlers take the session through `DbSession`, which opens one transaction and commits it as soon as the handler returns, before the response is sent (`Depends(..., scope="function")`). If the commit fails, the client gets an error, never a success the database did not keep. Once the caller is known, `set_learner` sets `app.user_id` for that transaction only.
- **Idempotency keys commit with the work.** `run_once` claims the key in the request's transaction. If the request fails, the key goes with it and a retry runs again; a concurrent duplicate waits on the key's row lock and then replays the stored response.
- **Rate-limit hits commit on their own.** `RateLimiter` uses a separate short transaction for each hit. Otherwise a refused sign-in, which rolls back its request, would also roll back the count of failed attempts.
- **Unexpected errors are handled inside the request-id context.** Starlette's own catch-all runs outside every middleware, where the request id is gone, so `UnhandledErrorMiddleware` sits inside `RequestIdMiddleware`, logs the error with the id and returns a 500 problem.

## Consequences

Feature code never commits by hand inside a request. Work that must survive the request's rollback, as rate counts do, opens its own transaction through `Database.transaction()`. A handler that does slow work after its last write still holds the transaction open, so slow work goes to a background job (CLAUDE.md, "Slow work runs in background workers").
