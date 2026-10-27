# B5 load test (local Docker Compose, not stage-0)

**Local Docker Compose run: preliminary, not stage-0 evidence (ADR 0039, #155)**

- Host: local Docker Compose; 4 cores; commit 5db1333bf23e3d8feda7d4401b8ba983d8bce85c
- Load: 15 req/s mixed plus 20 Blind learners (one heartbeat per 5 s each); 60 s warm-up, 600 s measured
- Delivered: mixed 15.21 req/s, heartbeat 4.20 req/s
- Percentiles: nearest rank over every request of the measured window, failed requests included

## Latency

| Group | Requests | p50 ms | p95 ms | p99 ms | max ms | Errors | Error rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| read | 6623 | 11.6 | 22.4 | 29.8 | 177.5 | 0 | 0.00% |
| write | 5021 | 13.7 | 31.1 | 83.9 | 236.5 | 249 | 4.96% |
| heartbeat | 2520 | 14.6 | 30.5 | 68.0 | 218.7 | 249 | 9.88% |
| all | 11644 | 12.4 | 26.0 | 52.1 | 236.5 | 249 | 2.14% |

| Endpoint | Requests | p95 ms | Errors |
| --- | --- | --- | --- |
| DELETE /sessions/{id}/marks/{id} | 414 | 13.7 | 0 |
| GET /cards | 329 | 16.0 | 0 |
| GET /contents | 337 | 14.3 | 0 |
| GET /dictation/attempts/{id} | 339 | 14.4 | 0 |
| GET /library/contents | 694 | 15.4 | 0 |
| GET /me | 874 | 12.8 | 0 |
| GET /sessions | 781 | 19.2 | 0 |
| GET /sessions/{id} | 1612 | 15.3 | 0 |
| GET /sessions/{id}/blind | 319 | 17.9 | 0 |
| GET /sessions/{id}/marks | 663 | 15.4 | 0 |
| GET /sessions/{id}/transcript | 675 | 30.3 | 0 |
| PATCH /sessions/{id}/marks/{id} | 515 | 17.2 | 0 |
| POST /blind/attempts/{id}/heartbeat | 2520 | 30.5 | 249 |
| POST /sessions/{id}/blind/attempts | 100 | 204.9 | 0 |
| POST /sessions/{id}/dictation/attempts | 529 | 20.3 | 0 |
| POST /sessions/{id}/marks | 414 | 33.7 | 0 |
| PUT /dictation/attempts/{id}/draft | 529 | 15.8 | 0 |

Errors: POST /blind/attempts/{id}/heartbeat 0 (k6 error 1000) x80, POST /blind/attempts/{id}/heartbeat 0 (k6 error 1220) x169

Blind listens stopped by the server in the measured window: none

## CPU (share of all host cores)

| Role | Mean | p95 | Max | Samples |
| --- | --- | --- | --- | --- |
| api | 4.5% | 6.9% | 17.4% | 1200 |
| db | 1.9% | 3.1% | 13.7% | 1200 |
| worker | 0.3% | 0.9% | 4.1% | 1200 |
| load | 1.0% | 1.5% | 2.6% | 1200 |
| server | 6.6% | 10.5% | 31.9% | 1200 |

## Against System Design 1.1 and 12.1

| Check | Target | Result |
| --- | --- | --- |
| Read p95 | under 200 ms | meets |
| Write p95 (heartbeats included) | under 300 ms | meets |
| Server CPU (API + DB + worker), mean | under 30% | meets |

## Slowest statements (pg_stat_statements)

| Calls | Total ms | Mean ms | Max ms | Rows | Query |
| --- | --- | --- | --- | --- | --- |
| 11383 | 8542.9 | 0.75 | 13.1 | 11383 | `SELECT identity.resolve_auth_session($1)` |
| 11383 | 786.9 | 0.07 | 5.4 | 11383 | `SELECT s.user_id FROM identity.auth_sessions s JOIN identity.users u ON u.id = s.user_id WHERE s.token_hash = p_token_hash AND s.expires_at > now() AND u.status` |
| 11383 | 454.0 | 0.04 | 2.4 | 34149 | `SELECT kind, version, granted_at, withdrawn_at FROM identity.consents WHERE user_id = $1 AND (kind, version) IN (('terms', $2), ('privacy', $3), ('voice_recordi` |
| 8039 | 430.5 | 0.05 | 2.5 | 8039 | `SELECT id, user_id, content_id, passage, entry, status, version, entry_locked_at, completed_at, created_at, updated_at FROM practice.sessions WHERE id = $1` |
| 8039 | 393.9 | 0.05 | 3.9 | 40195 | `SELECT step, position, status FROM practice.session_steps WHERE session_id = $1 ORDER BY position` |
| 328 | 361.1 | 1.10 | 4.9 | 6888 | `SELECT c.id, c.session_id, c.slot, c.mark_id, c.written_form, c.heard_form, c.at_ms, c.created_at, s.content_id, $5 \|\| s.content_id \|\| $6 \|\| c.at_ms AS source_u` |
| 499 | 289.8 | 0.58 | 8.8 | 499 | `SELECT id, status, task_name, priority, lock, queueing_lock, args, scheduled_at, queue_name, attempts, worker_id FROM procrastinate_fetch_job_v2($1::varchar[], ` |
| 1645 | 248.6 | 0.15 | 3.5 | 1645 | `UPDATE practice.blind_attempts SET last_position_ms = $1, last_heartbeat_at = $2, anchor_position_ms = $3, anchor_at = $4, buffering_ms = $5, resume_count = $6,` |
| 2290 | 198.7 | 0.09 | 3.0 | 2290 | `SELECT c.id, c.title, m.source, m.status, m.duration_ms, c.created_at, m.id, m.has_video, c.keep_video, m.error_code, CASE WHEN m.status NOT IN ($3, $4) THEN $5` |
| 1028 | 194.7 | 0.19 | 2.1 | 11308 | `SELECT c.id, c.title, m.source, m.status, m.duration_ms, c.created_at, CASE WHEN m.status NOT IN ('pending', 'downloading') THEN NULL WHEN m.status = 'pending' ` |
| 596 | 184.6 | 0.31 | 1.8 | 596 | `INSERT INTO ops.analytics_events (id, user_id, event_type, subject_id, step, content_id, session_id, properties) VALUES ($1, $2, $3, $4, $5, $6, $7, CAST($8 AS ` |
| 2433 | 159.9 | 0.07 | 1.3 | 2433 | `SELECT attempt_id, user_id, media_token_hash, media_expires_at, passage_start_ms, passage_end_ms, last_position_ms, last_heartbeat_at, anchor_position_ms, ancho` |
| 116 | 151.0 | 1.30 | 8.3 | 116 | `SELECT unnest(procrastinate.procrastinate_defer_jobs_v1(ARRAY[ROW( $1, $2, $3, $4, $5, CAST($6 AS jsonb), $7 )::procrastinate.procrastinate_job_to_defer_v1]))` |
| 3236 | 146.3 | 0.05 | 0.3 | 3236 | `SELECT id, session_id, user_id, mode, status, started_at, finished_at FROM practice.attempts WHERE id = $1` |
| 499 | 132.4 | 0.27 | 8.6 | 166 | `WITH candidate AS ( SELECT jobs.* FROM procrastinate_jobs AS jobs WHERE -- reject the job if its lock has earlier or higher priority jobs NOT EXISTS ( SELECT 1 ` |
| 414 | 123.4 | 0.30 | 2.7 | 414 | `INSERT INTO practice.marks (id, session_id, user_id, word_from, word_to, at_ms, note, source, status) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT DO` |
| 1088 | 123.2 | 0.11 | 0.4 | 1088 | `SELECT content.passage_transcripts.id, content.passage_transcripts.media_object_id, content.passage_transcripts.span, content.passage_transcripts.origin, conten` |
| 11383 | 112.3 | 0.01 | 1.1 | 11383 | `SELECT set_config('app.user_id', $1, true)` |
| 120 | 111.9 | 0.93 | 6.0 | 120 | `WITH inserted_jobs AS ( INSERT INTO procrastinate_jobs (queue_name, task_name, priority, lock, queueing_lock, args, scheduled_at) SELECT (job).queue_name, (job)` |
| 780 | 110.5 | 0.14 | 0.7 | 81900 | `SELECT session_id, step, position, status FROM practice.session_steps WHERE session_id = ANY($1) ORDER BY session_id, position` |

Statements with a mean of 10 ms or more: none
