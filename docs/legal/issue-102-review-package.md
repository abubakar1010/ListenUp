# Issue #102: legal-review package

Prepared 27 October 2026. Status: **awaiting written legal advice**.

This package is factual briefing material, focused adviser questions and an unfilled
decision record. It is not legal advice. No adviser has been contacted by this
session. YouTube intake remains disabled; issue #102 is not complete.

## Scope and evidence

The source review used commit `df0a8d3da4c6323d3d7ddbe12f08bdb70160b842`.
Implementation statements below describe that snapshot, not a deployed service
or an audit of subsequent commits on main. No production settings were inspected.

Sources read:

- [Issue #102](https://github.com/abubakar1010/ListenUp/issues/102) and its comments
  (open, with no comments when reviewed).
- [PRD](../design/prd.md), especially sections 5, 7 and 8, including OQ-6.
- [SRS](../design/srs.md): C5, A4, FR-CI-2, FR-TX-4, DR-1/2,
  NFR-SEC-2/3/5 and OI-1.
- [ADR 0011](../adr/0011-server-side-youtube-download-behind-a-feature-flag.md),
  [Architecture](../design/architecture.md) and
  [System Design](../design/system-design.md), especially storage sections 6.2–6.3.
- [Legal README](README.md), all 11 owner implementation notes and 14 adviser
  questions, [Terms](terms-2026-1.md), [Privacy](privacy-2026-1.md) and
  [Voice consent](voice-2026-1.md). All three texts remain unreviewed drafts.
- Relevant content, transcript, identity/deletion, export, admin, Shadow, backup
  and AI source files identified below.

Repository-relative links resolve to the branch's current files. For the exact
reviewed evidence, use the snapshot SHA above. No current external law or YouTube
terms were independently researched.

## Owner instructions recorded during preparation

These are product intentions and business facts supplied by the owner, not
written legal clearance:

| Item | Current owner position |
| --- | --- |
| Operator | The owner personally, as an individual; formal operator name/address still to be confirmed for legal text |
| Contact | Owner's email; exact address has not been supplied for this package |
| Markets | Worldwide |
| Minimum age | Undecided; all ages considered, but no final age policy agreed |
| Hosting/storage regions | Undecided |
| YouTube | Owner wants downloading supported, subject to the existing review gate |
| Transcripts | Owner wants generation and storage supported |
| Uploaded files | Use only to provide practice features: storage, conversion, transcription and analysis |

The final upload-use instruction supersedes the earlier broad “anything” wording
and the interim “discuss broader uses later” answer. Public sharing, sale and AI
training are outside this working scope. Optional discussion does not block
review preparation or other authorized work; it does not remove legal or release
gates. The owner's answers do not satisfy issue #102's written-advice criterion.

## Factual brief

### YouTube downloading versus embedded playback

ListenUp provides private, account-based English listening exercises. The intended
YouTube path downloads media to the server for playback control. Architecture
section 3 says an embedded YouTube player cannot reliably enforce Blind's
no-pause/no-seek rules. This is a technical rationale, not permission to download.

The PRD and ADR 0011 identify downloading as conflicting with YouTube's terms,
pending OQ-6 review. This is the project's risk assessment, not received advice.
ADR 0011 requires upload-first delivery and a default-off YouTube gate until
clearance. Upload remains the fallback.

**Implemented at the reviewed snapshot:** upload intake.
`apps/api/src/listenup/platform/config.py` defaults
`youtube_intake_enabled` to false. `modules/content/api.py` accepts
`ConfirmUpload` at `POST /contents`; no YouTube URL intake path was found.
The setting was the only reference to `youtube_intake_enabled` under apps.
This does not demonstrate an operational downloader waiting for a flag flip.

**Planned:** an isolated downloader, creator-caption import, a shared download/cache
per video, and unused-playback expiry. Future intake must enforce the gate and
inherit the media sandbox. Embedded playback is an alternative requiring changes
to practice constraints and transcript sourcing, not an implemented fallback.

YouTube media files are excluded from export by design and archive policy;
links, titles and practice data may be included.

### Generating, storing and retaining third-party transcripts

**Implemented for uploads:** `modules/transcript/jobs.py` retrieves playback,
extracts missing passage audio and calls the AI gateway. Timestamped words,
confidence, sentence boundaries and provenance are cached by media and passage
span. `transcript/service.py` authorizes the session before privileged cache
reads. Learner corrections are separate overlays, not common-reference edits.

Transcripts support Dictation scoring, key-point extraction, gist feedback and
reference profiles. Card snippets create another derived use of source audio.

`ai/ai.yaml` configures local faster-whisper transcription and wav2vec2 alignment.
Hosted Groq is disabled with retention verification false; local Ollama text AI
is also disabled. `ai/policy.py` rejects providers that train on inputs and gates
hosted use on retention verification, consent, region and population. These
controls do not establish copyright permission.

**Planned YouTube path:** import creator-written captions and force-align them,
otherwise generate a transcript. Architecture excludes automatic captions.
Original references, profiles and key points would be reused across learners who
add the same video; corrections and learner work remain private.

The proposed **30-day expiry removes unused playback files, not transcripts**.
System Design retains metadata, transcripts and profiles, then re-downloads
playback on use. No fixed transcript TTL is specified. SRS DR-2 ties shared
transcript deletion to the final content reference and upload transcript deletion
to its upload. Clip deletion and orphan cleanup needed for that lifecycle remain
incomplete. Advice must address derivatives, backups and exported copies too.

### Copyrighted uploaded files

The PRD anticipates films, television, podcasts, interviews and lectures, including
material not created by the learner. Draft Terms require rights to use content,
prohibit infringement and grant processing permission only to provide ListenUp.
Their private-study wording is not a finding that an exception applies.

**Implemented safeguards:** authenticated private intake, deduplication scoped to
each learner, file/type/size checks, 500 MiB per-file and 2 GiB account limits,
daily audio admission, fail-closed ClamAV scanning before media parsing,
conversion and source-original removal after conversion. See
`modules/content/{api,service,jobs,scanner}.py`.

These do not verify copyright ownership or licence scope. Processing can create
converted media, transcripts, snippets and profiles; export can include uploaded
media. Upload-only delivery does not resolve OQ-6(c).

## Safeguards: implemented versus planned

Paths in this table are under `apps/api/src/listenup/` unless specified.

| Area | Implemented in reviewed source | Gap or qualification |
| --- | --- | --- |
| Private access | Authenticated endpoints, learner DB context/RLS and ownership checks; authorized boundary before privileged transcript-cache reads | Not a deployment audit. See identity service, platform database, content API/service and transcript service |
| Shared transcript cache | API direct cache access revoked by migration `20261015_0017_passage_transcripts.py`; workers and authorized service boundaries access it | Shared cache is not ordinary learner-owned row storage |
| Signed media links | Normal default 300 seconds, private/no-store redirects | Expiry does not prove immediate revocation after access changes |
| Account deletion | Disable immediately, end sessions, explicit seven-day restoration, then background purge with retries | Scheduled purge/failures can delay physical deletion; see identity jobs/service and ADR 0029 |
| Residual deletion data | Storage-prefix deletion and learner DB cascade | Audit records survive; ADR 0029 notes late worker-file residue and missing orphan cleanup |
| Clip/session deletion | Unconfirmed-upload cancellation exists | Library clip/session deletion remains planned under #89 |
| Uploaded originals | Deleted after conversion | Converted playback remains |
| Unconfirmed uploads | Confirmation expires after 24 hours; explicit cancellation deletes bytes | Automatic cleanup of never-confirmed stored files not demonstrated |
| YouTube playback | Intake unavailable in reviewed code | Thirty-day unused-playback cleanup not built |
| Transcript retention | Passage cache implemented | No fixed TTL; final-reference/orphan lifecycle incomplete |
| Shadow audio | Segment/round structures exist | Ninety-day recording deletion not implemented; legal README's older “empty module” note is stale |
| Voice consent withdrawal | Draft distinguishes stopping future recording from deleting existing audio | Existing-recording deletion requirements remain for advice/implementation |
| Export | Background archives, seven-day expiry, three requests per UTC day; owner download URL lasts 120 seconds | Copyright advice may require changes; see export service/jobs and ADR 0030 |
| Backups | Fourteen-day setting and pruning code | `ops/backup.py` deliberately preserves newest complete backup even if older; managed DB retention unresolved |
| Logs/login rows | Sign-in access expires after 30 days | Log retention unset; expired login-row cleanup not established |
| Usage events | IDs/typed values, no learner text; account cascade | Designed to survive clip/session deletion; pseudonymous is not necessarily anonymous |
| Takedowns | Operational admin views exist | #105 records/removal for all affected learners/re-add blocking/notifications and #181 replies/reasoned enforcement remain planned |

## Conflicts and missing owner facts

1. PRD rights wording and SRS C5 describe per-learner YouTube storage; System
   Design and the privacy draft describe shared media/transcripts. Present the
   shared-cache proposal explicitly. “One download reduces legal exposure” is
   an unverified design assertion.
2. Drafts describe unfinished deletion, retention and takedown safeguards as if
   current. They are not evidence of compliance.
3. “Deleted for good” after seven days needs qualification for asynchronous
   purge, backups, audit records and possible late files. A universal fourteen-day
   backup maximum is not established.
4. Confirm formal operator details, exact contact, operating country,
   processors/regions, final age policy, takedown contact and log retention.
   Worldwide availability is an intention, not a conclusion about applicable law.
5. Legal README records a hosted-AI disclosure mismatch: FR-BL-13 names
   transcript/key points/gist, while task schemas also allow Shadow measures and
   flagged words. Hosted processing is disabled; resolve before activation.

## Focused questions for the adviser

Please answer A, B and C separately in writing. Identify applicable jurisdictions,
platform terms/versions reviewed, assumptions, conditions and unresolved facts.

### A. YouTube downloading and embedding

1. May ListenUp fetch metadata/captions, extract audio, download and transcode
   server copies, or must playback use an authorized embed? Distinguish each
   operation and permission/licence route.
2. Does private study or shared caching change the answer? Address media,
   transcripts, profiles and key points separately.
3. If embedding is permitted, may transcripts be obtained/generated separately,
   through which mechanism, and under what restrictions?
4. What conditions must be met before YouTube intake can be considered for
   activation? Which practice controls must change?

### B. Transcript generation, storage and retention

5. May the app generate timed transcripts, import captions, retain corrections
   and derive key points, profiles and snippets? Distinguish uploads and YouTube,
   and user-owned/licensed material from other content.
6. May references be reused across learners? What attribution, access, licence
   and export restrictions apply?
7. What TTLs/deletion triggers apply to media, text and derivatives after playback
   expiry, final-reference removal, rightsholder notice or account deletion?
   Address backups and exports.
8. Does hosted AI processing require additional permission or contractual terms?

### C. Copyrighted uploads

9. Which server-side uses of films/podcasts/TV are permissible in intended
   markets? What facts or licences support any private-education exception?
10. What uploader representations, processing licence, permission evidence,
    restrictions and repeat-infringer controls are required?
11. What notice, takedown, counter-notice/reply, appeal, re-add blocking,
    record-retention and account-enforcement process is needed? Is a designated
    agent required? What deadlines apply to shared copies and derivatives?

### Related owner questions

12. Which safeguards must exist before launch, and which retention/deletion
    promises need revision?
13. Confirm privacy regimes, legal bases, age/parental requirements, voice-data
    classification, withdrawal/deletion duties, processors and transfers.
14. Review operator/contact, liability/governing-law placeholders and new-version
    re-acceptance. Address pseudonymous analytics and hosted-AI consent/payload
    disclosures identified in the legal README.

## Decision-record template

Leave unfilled until actual written advice arrives.

- Status: **Awaiting written advice**
- Adviser, qualifications and scope: [pending]
- Written advice reference/date/version and access location: [pending]
- Operator, markets, users and source snapshot considered: [pending]
- Applicable law/platform terms reviewed: [pending]
- A: YouTube conclusion and conditions: [pending]
- B: Transcript conclusion and conditions: [pending]
- C: Copyrighted-upload conclusion and conditions: [pending]
- Unresolved questions/missing facts: [pending]
- Owner decision within the advice and rationale: [pending]
- Required pre-launch controls and evidence: [pending]
- Follow-up story links/owners/dependencies: [pending]
- Proposed issue #102 outcome and ADR 0011 revisit text: [pending]
- Re-review triggers/date: [pending]
- YouTube activation decision: [separate future decision; remains off]

Conditional mappings below are planning paths, not advice or approvals:

| Possible written advice | Implementation follow-up | Acceptance evidence |
| --- | --- | --- |
| Server downloading prohibited | Keep intake off; assess authorized embed and revised practice controls | No prohibited server fetch path; approved playback specification/tests |
| Downloading restricted to permissioned sources | Verify permission/provenance; implement isolated processing and enforced default-off gate | Unauthorized admission refused; conditions recorded; sandbox/gate tests |
| Transcripts prohibited or transient only | Disable persistence/affected uses; revisit dependent modes | No prohibited cache, derivative or export residue |
| Shorter transcript retention/no sharing | Add TTL/sweeps, scoped caches and recreation prevention | Expiry, final-reference, retry/race and access tests |
| Upload restrictions needed | Revise admission, licence capture, processing/snippets and export | Advice conditions mapped to controls and refusal tests |
| Formal takedown process needed | Refine #105/#181: deadlines, all-copy removal, blocking, notices/replies and enforcement reasons | Shared/upload/derivative cases and authorization tests |
| Deletion/privacy changes needed | Complete lifecycle controls; reconcile backups/logs/audits; version legal texts under ADR 0051 | Purge evidence, accurate exceptions and re-acceptance checks |
| Advice incomplete | Record blockers and keep affected feature unavailable | No activation/completion based on silence or partial advice |

For every follow-up record the advice paragraph, owner, affected data/code,
defaults, existing-data cleanup, retry/failure behavior, access/deletion tests,
documentation changes, dependencies and release evidence.

## Handoff and validation

- Written advice on all three topics: not received in reviewed sources or this
  session. Owner product intentions do not replace it.
- Issue #102 and ADR 0011 outcome updates: not made; await advice. ADR 0011 needs
  an actual outcome/revisit section later, not a fabricated conclusion now.
- Follow-up stories: conditional proposals only; none opened.
- No feature, configuration, legal draft or product-requirement changes.
- Documentation-only change: TDD and executable suites are not applicable under
  docs/testing.md. Validate Markdown links, whitespace and scope.
- Publishing this package does not complete issue #102 or authorize YouTube.
