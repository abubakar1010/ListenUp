# B5 load test (local Docker Compose, not stage-0)

**Local Docker Compose run: preliminary, not stage-0 evidence (ADR 0039, #155)**

- Host: local Docker Compose; 3 cores; commit 7d86961d5c04edf254c7513e1f3c073ffbd41b20
- Load: 15 req/s mixed plus 20 Blind learners (one heartbeat per 5 s each); 20 s warm-up, 120 s measured
- Delivered: mixed 15.06 req/s, heartbeat 4.33 req/s
- Percentiles: nearest rank over every request of the measured window, failed requests included

## Latency

| Group | Requests | p50 ms | p95 ms | p99 ms | max ms | p95 answered ms | Errors | Error rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| read | 1347 | 7.3 | 16.0 | 34.0 | 292.1 | 16.0 | 0 | 0.00% |
| write | 980 | 10.3 | 47.6 | 159.2 | 236.4 | 53.3 | 84 | 8.57% |
| heartbeat | 520 | 12.7 | 49.6 | 92.9 | 109.0 | 60.1 | 84 | 16.15% |
| all | 2327 | 7.9 | 32.2 | 96.8 | 292.1 | 32.8 | 84 | 3.61% |

| Endpoint | Requests | p95 ms | Errors |
| --- | --- | --- | --- |
| DELETE /sessions/{id}/marks/{id} | 79 | 12.1 | 0 |
| GET /cards | 86 | 10.4 | 0 |
| GET /contents | 68 | 10.9 | 0 |
| GET /dictation/attempts/{id} | 68 | 34.0 | 0 |
| GET /library/contents | 162 | 12.8 | 0 |
| GET /me | 163 | 11.0 | 0 |
| GET /sessions | 147 | 16.6 | 0 |
| GET /sessions/{id} | 315 | 12.3 | 0 |
| GET /sessions/{id}/blind | 57 | 12.7 | 0 |
| GET /sessions/{id}/marks | 151 | 13.1 | 0 |
| GET /sessions/{id}/transcript | 130 | 22.0 | 0 |
| PATCH /sessions/{id}/marks/{id} | 98 | 15.2 | 0 |
| POST /blind/attempts/{id}/heartbeat | 520 | 49.6 | 84 |
| POST /sessions/{id}/blind/attempts | 20 | 195.9 | 0 |
| POST /sessions/{id}/dictation/attempts | 92 | 17.8 | 0 |
| POST /sessions/{id}/marks | 79 | 25.9 | 0 |
| PUT /dictation/attempts/{id}/draft | 92 | 15.9 | 0 |

Errors: POST /blind/attempts/{id}/heartbeat 0 (k6 error 1000) x14, POST /blind/attempts/{id}/heartbeat 0 (k6 error 1220) x70

Blind listens stopped by the server in the measured window: none
Blind attempts of the run at its end, by outcome: listened x10, unfinished x30

## CPU (share of all host cores)

| Role | Mean | p95 | Max | Samples |
| --- | --- | --- | --- | --- |
| api | 4.0% | 7.2% | 13.7% | 480 |
| db | 1.6% | 3.1% | 10.1% | 480 |
| worker | 0.2% | 0.4% | 1.6% | 480 |
| load | 0.8% | 1.4% | 1.9% | 480 |
| server | 5.8% | 9.9% | 24.4% | 480 |

## Against System Design 1.1 and 12.1

| Check | Target | Result |
| --- | --- | --- |
| Read p95 | under 200 ms | meets |
| Write p95 (heartbeats included) | under 300 ms | meets |
| Server CPU (API + DB + worker), mean | under 30% | meets |
| Error rate, reads and writes each | under 1% | misses |
| Delivered load | at least 95% of the plan | meets |

## Slowest statements (pg_stat_statements)

| Calls | Total ms | Mean ms | Max ms | Rows | Query |
| --- | --- | --- | --- | --- | --- |
| 2243 | 1282.4 | 0.57 | 30.5 | 2243 | `SELECT identity.resolve_auth_session($1)` |
| 2243 | 76.5 | 0.03 | 1.0 | 2243 | `SELECT s.user_id FROM identity.auth_sessions s JOIN identity.users u ON u.id = s.user_id WHERE s.token_hash = p_token_hash AND s.expires_at > now() AND u.status` |
| 20 | 66.6 | 3.33 | 11.4 | 20 | `SELECT unnest(procrastinate.procrastinate_defer_jobs_v1(ARRAY[ROW( $1, $2, $3, $4, $5, CAST($6 AS jsonb), $7 )::procrastinate.procrastinate_job_to_defer_v1]))` |
| 1551 | 61.5 | 0.04 | 2.2 | 1551 | `SELECT id, user_id, content_id, passage, entry, status, version, entry_locked_at, completed_at, created_at, updated_at FROM practice.sessions WHERE id = $1` |
| 2243 | 58.7 | 0.03 | 3.3 | 6729 | `SELECT kind, version, granted_at, withdrawn_at FROM identity.consents WHERE user_id = $1 AND (kind, version) IN (('terms', $2), ('privacy', $3), ('voice_recordi` |
| 25 | 57.7 | 2.31 | 10.7 | 25 | `WITH inserted_jobs AS ( INSERT INTO procrastinate_jobs (queue_name, task_name, priority, lock, queueing_lock, args, scheduled_at) SELECT (job).queue_name, (job)` |
| 1551 | 51.9 | 0.03 | 5.1 | 7755 | `SELECT step, position, status FROM practice.session_steps WHERE session_id = $1 ORDER BY position` |
| 147 | 35.0 | 0.24 | 1.1 | 11260 | `SELECT session_id, step, position, status FROM practice.session_steps WHERE session_id = ANY($1) ORDER BY session_id, position` |
| 305 | 33.8 | 0.11 | 1.3 | 305 | `UPDATE practice.blind_attempts SET last_position_ms = $1, last_heartbeat_at = $2, anchor_position_ms = $3, anchor_at = $4, buffering_ms = $5, resume_count = $6,` |
| 99 | 30.9 | 0.31 | 2.9 | 99 | `INSERT INTO ops.analytics_events (id, user_id, event_type, subject_id, step, content_id, session_id, properties) VALUES ($1, $2, $3, $4, $5, $6, $7, CAST($8 AS ` |
| 431 | 26.5 | 0.06 | 1.0 | 431 | `SELECT c.id, c.title, m.source, m.status, m.duration_ms, c.created_at, m.id, m.has_video, c.keep_video, m.error_code, CASE WHEN m.status NOT IN ('pending', 'dow` |
| 10 | 25.8 | 2.58 | 6.3 | 10 | `SELECT procrastinate_defer_periodic_job_v2($1, $2, $3, $4, $5, $6, $7, $8) AS id` |
| 230 | 23.6 | 0.10 | 0.7 | 460 | `SELECT c.id, c.title, m.source, m.status, m.duration_ms, c.created_at, CASE WHEN m.status NOT IN ($3, $4) THEN $5 WHEN m.status = $6 AND u.confirmed_at IS NOT N` |
| 69 | 23.3 | 0.34 | 3.5 | 69 | `SELECT id, status, task_name, priority, lock, queueing_lock, args, scheduled_at, queue_name, attempts, worker_id FROM procrastinate_fetch_job_v2($1::varchar[], ` |
| 20 | 21.6 | 1.08 | 8.8 | 20 | `INSERT INTO procrastinate_events(job_id, type, at) VALUES (NEW.id, $16::procrastinate_job_event_type, NEW.scheduled_at)` |
| 79 | 18.0 | 0.23 | 1.5 | 79 | `INSERT INTO practice.marks (id, session_id, user_id, word_from, word_to, at_ms, note, source, status) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT DO` |
| 436 | 17.8 | 0.04 | 2.0 | 436 | `SELECT attempt_id, user_id, media_token_hash, media_expires_at, passage_start_ms, passage_end_ms, last_position_ms, last_heartbeat_at, anchor_position_ms, ancho` |
| 162 | 15.2 | 0.09 | 0.7 | 324 | `SELECT DISTINCT ON (content_id) content_id, status FROM practice.sessions WHERE content_id = ANY($1) ORDER BY content_id, created_at DESC, id DESC` |
| 147 | 15.0 | 0.10 | 0.8 | 2252 | `SELECT id, user_id, content_id, passage, entry, status, version, entry_locked_at, completed_at, created_at, updated_at FROM practice.sessions WHERE user_id = $1` |
| 10 | 14.7 | 1.47 | 5.2 | 5 | `INSERT INTO procrastinate_periodic_defers (task_name, periodic_id, defer_timestamp) VALUES (_task_name, _periodic_id, _defer_timestamp) ON CONFLICT DO NOTHING R` |

Statements with a mean of 10 ms or more: none
