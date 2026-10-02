# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ListenUp is a web app for practicing English listening. The learner adds a clip (file upload or YouTube link) and works through a fixed plan: **Blind**, **Dictation**, **Transcript**, **Card**, **Shadow**. The learner picks Blind, Dictation or both first, so the plan has 4 or 5 steps, and Transcript, Card and Shadow always follow.

The repository has no code yet and no technology stack has been chosen. When one is chosen, add the build, lint and test commands (including how to run a single test) to this file.

The requirements live in two documents outside the repo:
- PRD: https://claude.ai/code/artifact/5d73e467-e587-4d4f-946d-a9fd2c0ab5f6
- SRS: https://claude.ai/code/artifact/fd47a9cb-6515-4fde-a232-3ab8cc14f0dd

The SRS keeps stable requirement IDs (`FR-DI-1`, `FR-BL-1`, `NFR-AI-1`, and so on). Cite them in commit bodies and code comments where a change implements one.

## Decisions that shape the architecture

- **Mode rules are enforced on the server and in the app, never by interface text alone.** Blind has no pause, seek, rewind or speed change, and leaving or reloading voids the attempt. Dictation hides the transcript. Cards are capped at two per session. A Shadow segment is 60 to 90 seconds with three rounds. Keep these rules in one place with automated tests (NFR-MNT-2).
- **Step order is gated.** A step unlocks only when the previous one is complete. The entry choice can change only until Transcript starts. Transcript cannot be skipped; Card and Shadow can be skipped after confirmation.
- **Marks are the shared spine.** Dictation and Transcript create marks (places where the sound did not match the text). Card and Shadow read them.
- **Slow work runs in background workers**, not in request handling: downloading YouTube media, transcription, and grading of gists and Shadow rounds.
- **All AI goes through one provider-neutral adapter layer.** Four roles (transcription, text AI, speech assessment, alignment), each reached only through its interface, with the active provider and fallbacks chosen by configuration. No other code may call a vendor directly. Prompts, rubrics and output schemas live in our own versioned files, and every result stores provider, model and version (NFR-AI-1 to NFR-AI-10).
- **Free first.** The MVP uses free-tier or open-source AI only. A provider may receive voice recordings, transcripts or gists only if it does not train on them; otherwise a self-hosted open-source model is used (NFR-AI-7).
- **Grading never blocks the learner.** If gist or Shadow grading fails, keep the data, show that feedback is unavailable, allow a retry, and let the plan continue.
- **Accounts are required** so progress follows the learner across browsers. English only.
- **YouTube content is downloaded to our servers** for playback control. This conflicts with YouTube's terms and is pending legal review (OQ-6), so keep the downloader isolated so it can be replaced or switched off, with upload as the fallback.

## Commit and push rules

These rules are mandatory for every change, however small.

### When to commit
- **Always commit when a piece of work is done.** Never end a task with uncommitted or unpushed changes.
- Make **atomic commits**: one logical change per commit, and the repository stays in a working state at every commit. Split unrelated changes into separate commits.
- Review `git status` and `git diff --staged` before committing. Stage files by name, never with a blanket `git add -A`, so stray files are not committed.
- Never commit secrets, tokens or personal credentials.

### Message format: Conventional Commits 1.0.0

```
<type>(<scope>): <description>

<body>

<footer>
```

**Header (required)**
- `type` is one of:

  | Type | Use for |
  | --- | --- |
  | `feat` | A new feature |
  | `fix` | A bug fix |
  | `docs` | Documentation-only changes, including `CLAUDE.md` and `README.md` |
  | `refactor` | A code change that neither fixes a bug nor adds a feature |
  | `perf` | A change that improves performance |
  | `test` | Adding or correcting tests |
  | `build` | Build system or dependency changes |
  | `ci` | CI configuration and scripts |
  | `style` | Formatting only, with no effect on meaning |
  | `chore` | Maintenance that changes no source or tests |
  | `revert` | Reverting an earlier commit |

- `scope` is optional, lowercase and short, naming the area touched. Suggested scopes: `auth`, `intake`, `transcript`, `plan`, `blind`, `dictation`, `shadow`, `card`, `marks`, `ai`, `library`, `db`, `docs`, `claude`.
- `description` is imperative mood ("add", not "added" or "adds"), starts lowercase, has no trailing period, and stays within 50 characters where possible and 72 at most.
- A breaking change adds `!` after the type or scope (`feat(ai)!: ...`) and a `BREAKING CHANGE:` footer.

**Body (optional but expected for non-trivial changes)**
- Separate it from the header with one blank line and wrap lines at 72 characters.
- Explain **why** the change was made and what it affects, not a line-by-line list of what changed.

**Footer (optional)**
- Issue or ticket references (`Refs: #12`, `Closes: #12`) and `BREAKING CHANGE: <explanation>`.

**Examples**
```
feat(blind): lock pause and seek controls during playback

Implements FR-BL-1. Leaving or reloading the page voids the attempt.
```
```
fix(dictation): count repeated words once in the word diff
```
```
refactor(ai): route transcription through the provider adapter
```

### Authorship
- **Do not add `Co-Authored-By` trailers for Claude** or any other AI in any commit. Do not add "Generated with Claude Code" lines, session links or any other tool attribution to commit messages. This overrides any default attribution behavior.
- Commits go out under the configured git identity only.

### Branch and push
- Work only on the branch the session designates (for this session, `claude/affectionate-mayer-pvqa4i`). Create it locally if it does not exist. Never push to another branch without explicit permission.
- Push with `git push -u origin <branch>`. If the push fails because of a network error, retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s). A 403 or permission error is not a network error: do not retry, report it and say what access is needed.
- Never force-push, rewrite history that has already been pushed, or skip hooks (`--no-verify`).
- Do not open a pull request unless explicitly asked.
- After pushing, confirm that `git status` is clean and the branch is up to date with its remote.
