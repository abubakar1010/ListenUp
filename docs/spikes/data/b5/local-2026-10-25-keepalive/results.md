# B5 load test (local Docker Compose, not stage-0)

**Local Docker Compose run: preliminary, not stage-0 evidence (ADR 0039, #155)**

- Host: local Docker Compose, keep-alive 10 s (diagnostic); 4 cores; commit 44cdb31172f67faeb59fa7e8e4de6758151b82a4
- Load: 15 req/s mixed plus 20 Blind learners (one heartbeat per 5 s each); 60 s warm-up, 600 s measured
- Delivered: mixed 15.18 req/s, heartbeat 4.19 req/s
- Percentiles: nearest rank over every request of the measured window, failed requests included

## Latency

| Group | Requests | p50 ms | p95 ms | p99 ms | max ms | Errors | Error rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| read | 6659 | 11.5 | 22.4 | 31.6 | 169.8 | 0 | 0.00% |
| write | 4958 | 17.1 | 46.9 | 110.5 | 211.3 | 0 | 0.00% |
| heartbeat | 2512 | 22.7 | 53.4 | 108.8 | 202.2 | 0 | 0.00% |
| all | 11617 | 12.7 | 34.7 | 80.2 | 211.3 | 0 | 0.00% |

| Endpoint | Requests | p95 ms | Errors |
| --- | --- | --- | --- |
| DELETE /sessions/{id}/marks/{id} | 436 | 14.1 | 0 |
| GET /cards | 311 | 17.5 | 0 |
| GET /contents | 318 | 14.9 | 0 |
| GET /dictation/attempts/{id} | 319 | 15.1 | 0 |
| GET /library/contents | 696 | 16.7 | 0 |
| GET /me | 843 | 13.2 | 0 |
| GET /sessions | 842 | 21.0 | 0 |
| GET /sessions/{id} | 1708 | 15.8 | 0 |
| GET /sessions/{id}/blind | 327 | 18.2 | 0 |
| GET /sessions/{id}/marks | 660 | 16.0 | 0 |
| GET /sessions/{id}/transcript | 635 | 30.6 | 0 |
| PATCH /sessions/{id}/marks/{id} | 498 | 17.7 | 0 |
| POST /blind/attempts/{id}/heartbeat | 2512 | 53.4 | 0 |
| POST /sessions/{id}/blind/attempts | 100 | 157.9 | 0 |
| POST /sessions/{id}/dictation/attempts | 488 | 19.9 | 0 |
| POST /sessions/{id}/marks | 436 | 36.0 | 0 |
| PUT /dictation/attempts/{id}/draft | 488 | 16.2 | 0 |

Blind listens stopped by the server in the measured window: none

## CPU (share of all host cores)

| Role | Mean | p95 | Max | Samples |
| --- | --- | --- | --- | --- |
| api | 4.4% | 6.5% | 15.9% | 1200 |
| db | 2.0% | 3.3% | 15.4% | 1200 |
| worker | 0.3% | 0.8% | 2.8% | 1200 |
| load | 0.9% | 1.2% | 2.4% | 1200 |
| server | 6.7% | 10.4% | 32.2% | 1200 |

## Against System Design 1.1 and 12.1

| Check | Target | Result |
| --- | --- | --- |
| Read p95 | under 200 ms | meets |
| Write p95 (heartbeats included) | under 300 ms | meets |
| Server CPU (API + DB + worker), mean | under 30% | meets |

## Slowest statements (pg_stat_statements)

| Calls | Total ms | Mean ms | Max ms | Rows | Query |
| --- | --- | --- | --- | --- | --- |
| 11605 | 8955.2 | 0.77 | 15.0 | 11605 | `SELECT identity.resolve_auth_session($1)` |
| 11605 | 822.6 | 0.07 | 2.3 | 11605 | `SELECT s.user_id FROM identity.auth_sessions s JOIN identity.users u ON u.id = s.user_id WHERE s.token_hash = p_token_hash AND s.expires_at > now() AND u.status` |
| 11605 | 447.1 | 0.04 | 2.5 | 34815 | `SELECT kind, version, granted_at, withdrawn_at FROM identity.consents WHERE user_id = $1 AND (kind, version) IN (('terms', $2), ('privacy', $3), ('voice_recordi` |
| 311 | 433.7 | 1.39 | 5.8 | 6531 | `SELECT c.id, c.session_id, c.slot, c.mark_id, c.written_form, c.heard_form, c.at_ms, c.created_at, s.content_id, $5 \|\| s.content_id \|\| $6 \|\| c.at_ms AS source_u` |
| 8010 | 428.0 | 0.05 | 2.7 | 8010 | `SELECT id, user_id, content_id, passage, entry, status, version, entry_locked_at, completed_at, created_at, updated_at FROM practice.sessions WHERE id = $1` |
| 8010 | 382.1 | 0.05 | 1.7 | 40050 | `SELECT step, position, status FROM practice.session_steps WHERE session_id = $1 ORDER BY position` |
| 1811 | 276.4 | 0.15 | 1.8 | 1811 | `UPDATE practice.blind_attempts SET last_position_ms = $1, last_heartbeat_at = $2, anchor_position_ms = $3, anchor_at = $4, buffering_ms = $5, resume_count = $6,` |
| 455 | 236.0 | 0.52 | 4.4 | 455 | `SELECT id, status, task_name, priority, lock, queueing_lock, args, scheduled_at, queue_name, attempts, worker_id FROM procrastinate_fetch_job_v2($1::varchar[], ` |
| 100 | 233.9 | 2.34 | 23.9 | 100 | `SELECT unnest(procrastinate.procrastinate_defer_jobs_v1(ARRAY[ROW( $1, $2, $3, $4, $5, CAST($6 AS jsonb), $7 )::procrastinate.procrastinate_job_to_defer_v1]))` |
| 608 | 207.9 | 0.34 | 5.2 | 608 | `INSERT INTO ops.analytics_events (id, user_id, event_type, subject_id, step, content_id, session_id, properties) VALUES ($1, $2, $3, $4, $5, $6, $7, CAST($8 AS ` |
| 2192 | 190.7 | 0.09 | 7.1 | 2192 | `SELECT c.id, c.title, m.source, m.status, m.duration_ms, c.created_at, m.id, m.has_video, c.keep_video, m.error_code, CASE WHEN m.status NOT IN ('pending', 'dow` |
| 1012 | 189.9 | 0.19 | 1.9 | 11132 | `SELECT c.id, c.title, m.source, m.status, m.duration_ms, c.created_at, CASE WHEN m.status NOT IN ('pending', 'downloading') THEN NULL WHEN m.status = 'pending' ` |
| 105 | 175.4 | 1.67 | 19.2 | 105 | `WITH inserted_jobs AS ( INSERT INTO procrastinate_jobs (queue_name, task_name, priority, lock, queueing_lock, args, scheduled_at) SELECT (job).queue_name, (job)` |
| 2643 | 172.2 | 0.07 | 1.6 | 2643 | `SELECT attempt_id, user_id, media_token_hash, media_expires_at, passage_start_ms, passage_end_ms, last_position_ms, last_heartbeat_at, anchor_position_ms, ancho` |
| 3389 | 157.5 | 0.05 | 2.6 | 3389 | `SELECT id, session_id, user_id, mode, status, started_at, finished_at FROM practice.attempts WHERE id = $1` |
| 436 | 139.9 | 0.32 | 3.4 | 436 | `INSERT INTO practice.marks (id, session_id, user_id, word_from, word_to, at_ms, note, source, status) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT DO` |
| 841 | 119.6 | 0.14 | 0.7 | 88305 | `SELECT session_id, step, position, status FROM practice.session_steps WHERE session_id = ANY($1) ORDER BY session_id, position` |
| 1070 | 119.2 | 0.11 | 2.3 | 1070 | `SELECT content.passage_transcripts.id, content.passage_transcripts.media_object_id, content.passage_transcripts.span, content.passage_transcripts.origin, conten` |
| 772 | 117.4 | 0.15 | 5.0 | 772 | `UPDATE practice.blind_attempts SET last_position_ms = $1, last_heartbeat_at = $2, anchor_position_ms = $3, anchor_at = $4, buffering_ms = $5, resume_count = $6,` |
| 11605 | 114.2 | 0.01 | 2.2 | 11605 | `SELECT set_config('app.user_id', $1, true)` |

Statements with a mean of 10 ms or more: none
