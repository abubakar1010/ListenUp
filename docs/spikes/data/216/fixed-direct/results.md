# B5 load test (local Docker Compose, not stage-0)

**Local Docker Compose run: preliminary, not stage-0 evidence (ADR 0039, #155)**

- Host: local Docker Compose; 3 cores; commit 7d86961d5c04edf254c7513e1f3c073ffbd41b20
- Load: 15 req/s mixed plus 20 Blind learners (one heartbeat per 5 s each); 20 s warm-up, 120 s measured
- Delivered: mixed 15.22 req/s, heartbeat 4.33 req/s
- Percentiles: nearest rank over every request of the measured window, failed requests included

## Latency

| Group | Requests | p50 ms | p95 ms | p99 ms | max ms | p95 answered ms | Errors | Error rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| read | 1338 | 6.7 | 13.8 | 26.2 | 147.2 | 13.8 | 0 | 0.00% |
| write | 1009 | 11.4 | 40.6 | 76.8 | 179.9 | 40.6 | 0 | 0.00% |
| heartbeat | 520 | 16.6 | 40.6 | 175.4 | 179.9 | 40.6 | 0 | 0.00% |
| all | 2347 | 7.8 | 29.7 | 66.4 | 179.9 | 29.7 | 0 | 0.00% |

| Endpoint | Requests | p95 ms | Errors |
| --- | --- | --- | --- |
| DELETE /sessions/{id}/marks/{id} | 84 | 9.3 | 0 |
| GET /cards | 75 | 10.5 | 0 |
| GET /contents | 82 | 10.7 | 0 |
| GET /dictation/attempts/{id} | 69 | 10.8 | 0 |
| GET /library/contents | 135 | 11.5 | 0 |
| GET /me | 162 | 9.4 | 0 |
| GET /sessions | 155 | 14.8 | 0 |
| GET /sessions/{id} | 330 | 10.7 | 0 |
| GET /sessions/{id}/blind | 68 | 14.8 | 0 |
| GET /sessions/{id}/marks | 135 | 10.8 | 0 |
| GET /sessions/{id}/transcript | 127 | 19.6 | 0 |
| PATCH /sessions/{id}/marks/{id} | 87 | 11.6 | 0 |
| POST /blind/attempts/{id}/heartbeat | 520 | 40.6 | 0 |
| POST /sessions/{id}/blind/attempts | 20 | 97.8 | 0 |
| POST /sessions/{id}/dictation/attempts | 107 | 15.3 | 0 |
| POST /sessions/{id}/marks | 84 | 20.3 | 0 |
| PUT /dictation/attempts/{id}/draft | 107 | 14.3 | 0 |

Blind listens stopped by the server in the measured window: none
Blind attempts of the run at its end, by outcome: listened x20, unfinished x20

## CPU (share of all host cores)

| Role | Mean | p95 | Max | Samples |
| --- | --- | --- | --- | --- |
| api | 3.8% | 6.2% | 9.4% | 480 |
| db | 1.6% | 3.1% | 6.6% | 480 |
| worker | 0.2% | 0.3% | 1.9% | 480 |
| load | 0.7% | 1.2% | 1.8% | 480 |
| server | 5.6% | 8.6% | 16.3% | 480 |

## Against System Design 1.1 and 12.1

| Check | Target | Result |
| --- | --- | --- |
| Read p95 | under 200 ms | meets |
| Write p95 (heartbeats included) | under 300 ms | meets |
| Server CPU (API + DB + worker), mean | under 30% | meets |
| Error rate, reads and writes each | under 1% | meets |
| Delivered load | at least 95% of the plan | meets |

## Slowest statements (pg_stat_statements)

| Calls | Total ms | Mean ms | Max ms | Rows | Query |
| --- | --- | --- | --- | --- | --- |
| 2347 | 1259.2 | 0.54 | 14.6 | 2347 | `SELECT identity.resolve_auth_session($1)` |
| 2347 | 82.4 | 0.04 | 1.7 | 2347 | `SELECT s.user_id FROM identity.auth_sessions s JOIN identity.users u ON u.id = s.user_id WHERE s.token_hash = p_token_hash AND s.expires_at > now() AND u.status` |
| 1591 | 52.3 | 0.03 | 1.9 | 1591 | `SELECT id, user_id, content_id, passage, entry, status, version, entry_locked_at, completed_at, created_at, updated_at FROM practice.sessions WHERE id = $1` |
| 2347 | 51.0 | 0.02 | 0.6 | 7041 | `SELECT kind, version, granted_at, withdrawn_at FROM identity.consents WHERE user_id = $1 AND (kind, version) IN (('terms', $2), ('privacy', $3), ('voice_recordi` |
| 20 | 48.0 | 2.40 | 6.4 | 20 | `SELECT unnest(procrastinate.procrastinate_defer_jobs_v1(ARRAY[ROW( $1, $2, $3, $4, $5, CAST($6 AS jsonb), $7 )::procrastinate.procrastinate_job_to_defer_v1]))` |
| 109 | 44.7 | 0.41 | 3.6 | 109 | `SELECT id, status, task_name, priority, lock, queueing_lock, args, scheduled_at, queue_name, attempts, worker_id FROM procrastinate_fetch_job_v2($1::varchar[], ` |
| 1591 | 42.1 | 0.03 | 0.6 | 7955 | `SELECT step, position, status FROM practice.session_steps WHERE session_id = $1 ORDER BY position` |
| 22 | 37.6 | 1.71 | 4.8 | 22 | `WITH inserted_jobs AS ( INSERT INTO procrastinate_jobs (queue_name, task_name, priority, lock, queueing_lock, args, scheduled_at) SELECT (job).queue_name, (job)` |
| 360 | 37.1 | 0.10 | 1.3 | 360 | `UPDATE practice.blind_attempts SET last_position_ms = $1, last_heartbeat_at = $2, anchor_position_ms = $3, anchor_at = $4, buffering_ms = $5, resume_count = $6,` |
| 155 | 36.3 | 0.23 | 0.8 | 11820 | `SELECT session_id, step, position, status FROM practice.session_steps WHERE session_id = ANY($1) ORDER BY session_id, position` |
| 445 | 30.2 | 0.07 | 0.7 | 445 | `SELECT c.id, c.title, m.source, m.status, m.duration_ms, c.created_at, m.id, m.has_video, c.keep_video, m.error_code, CASE WHEN m.status NOT IN ('pending', 'dow` |
| 104 | 26.7 | 0.26 | 2.7 | 104 | `INSERT INTO ops.analytics_events (id, user_id, event_type, subject_id, step, content_id, session_id, properties) VALUES ($1, $2, $3, $4, $5, $6, $7, CAST($8 AS ` |
| 217 | 26.4 | 0.12 | 3.0 | 434 | `SELECT c.id, c.title, m.source, m.status, m.duration_ms, c.created_at, CASE WHEN m.status NOT IN ($3, $4) THEN $5 WHEN m.status = $6 AND u.confirmed_at IS NOT N` |
| 565 | 19.7 | 0.03 | 0.7 | 520 | `SELECT attempt_id, user_id, media_token_hash, media_expires_at, passage_start_ms, passage_end_ms, last_position_ms, last_heartbeat_at, anchor_position_ms, ancho` |
| 135 | 19.1 | 0.14 | 7.6 | 270 | `SELECT DISTINCT ON (content_id) content_id, status FROM practice.sessions WHERE content_id = ANY($1) ORDER BY content_id, created_at DESC, id DESC` |
| 109 | 18.5 | 0.17 | 1.0 | 47 | `WITH candidate AS ( SELECT jobs.* FROM procrastinate_jobs AS jobs WHERE -- reject the job if its lock has earlier or higher priority jobs NOT EXISTS ( SELECT 1 ` |
| 84 | 18.3 | 0.22 | 1.0 | 84 | `INSERT INTO practice.marks (id, session_id, user_id, word_from, word_to, at_ms, note, source, status) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT DO` |
| 160 | 18.0 | 0.11 | 1.8 | 160 | `UPDATE practice.blind_attempts SET last_position_ms = $1, last_heartbeat_at = $2, anchor_position_ms = $3, anchor_at = $4, buffering_ms = $5, resume_count = $6,` |
| 2347 | 13.8 | 0.01 | 1.5 | 2347 | `SELECT set_config('app.user_id', $1, true)` |
| 155 | 13.6 | 0.09 | 0.4 | 2364 | `SELECT id, user_id, content_id, passage, entry, status, version, entry_locked_at, completed_at, created_at, updated_at FROM practice.sessions WHERE user_id = $1` |

Statements with a mean of 10 ms or more: none
