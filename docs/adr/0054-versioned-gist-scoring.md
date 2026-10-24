# ADR 0054: Gist scoring from a versioned rubric

- Status: Accepted for story #68; level boundaries approved by the owner in-session
- Date: 2026-10-23
- Requirements: FR-BL-6 to FR-BL-9, FR-BL-12 to FR-BL-14; AT-10 to AT-13
- Related: ADRs 0037, 0041, 0046, 0053; SRS 5.2.1, Architecture 5.4/7.3, Database Design 6

## Decision

Gist submission creates a pending `grading.gist_grades` row and queues
`grading.grade_gist` on the AI lane in the same transaction that completes Blind.
The API registers the job when queueing; it does not rely on worker imports.
Producer deduplication and the execution lock use the attempt. The worker reads
only the named learner's submitted Blind gist, the original passage transcript
and the active extraction version's shared key points. Missing references use
the lane's existing retries; unavailable states and learner retries remain #70.

Call the existing `text_tasks.run_task` helper. Its gateway retains provider
eligibility, admission, input fitting and provenance validation. No learner
identity enters `CallContext`; absent verified hosted-routing context, the
gateway cannot select a hosted provider. This story enables no provider.
Only transcript, key points with local `kp1`-`kp6` labels, and gist enter the
nonce-delimited data message. Instructions stay in the system message.

Publish a new `grade_gist/v2.md` and its schema, together with
`v2.rubric.json`. The released v1 body and schema remain unchanged; only its
front-matter lifecycle status becomes retired, as required by ADR 0046's
exactly-one-active-version rule. Regenerate the manifest, which also locks the
rubric. Future rubric changes need a new version rather than an in-place edit.

The model returns dimension scores, covered point labels, wrong claims and
feedback. Grading rejects unknown covered labels and feedback outside two to
four complete sentences. Code reads the rubric's integer percentage weights
(50/30/20, D3), computes the weighted score and rounds to the nearest integer,
with halves rounded up. The rubric also stores the owner-approved inclusive
lower bounds: Fair 50, Good 70, Excellent 90; lower scores are Needs work.

Store the key-point reference, dimensions, overall, level, covered labels,
wrong claims, feedback, rubric version and provider/model/deployment/prompt
provenance, including trimmed reference field names. A ready row requires
overall, level, feedback, rubric version and complete provenance at the database
boundary. The learner/attempt composite FK, RLS and cascading parent deletion
preserve ownership. Grades join the existing data-export contributor list.

A conditional pending-to-ready update and `grade.ready` publication share one
transaction. A retry after commit neither invokes AI again nor repeats the
event. Account inactivity and removal during inference prevent storing a result;
inference holds no long-running database transaction. The queue lock prevents
concurrent duplicate inference; a crash before commit can still require a new call.

## Evidence and limits

AT-10 to AT-13 replay explicit synthetic response fixtures through
`ai.fake.yaml`, the production gateway/accounting and the real job/database.
A separate mock-HTTP adapter test checks the actual delimited provider payload.
Fixtures test pipeline semantics, not comprehension quality or injection
resistance of a live model. Like the existing ADR 0046 recordings, they are
clearly marked hand-authored; no genuine provider recordings or credentials
are available here. Provider acceptance still needs actual recordings and the
teacher/golden-set evaluation in #109 (which depends on #68); no live provider
is called in CI.

No result endpoint, web display, review/cards/shadow change or #70 failure flow
belongs to this decision. See the story's validation record for commands,
red/green chronology, coverage and remaining review gates.
