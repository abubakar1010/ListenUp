## Story

Closes #

## What changed and why

## Decisions

<!-- Each significant decision with its ADR, or "None". -->

## Not done

<!-- Acceptance criteria not met, with the reason, or "None". -->

## Checklist (docs/workflow.md)

- [ ] Every acceptance criterion is covered by a test or a documentation-only check
- [ ] Backend checks pass (format, lint, mypy, import contracts, full pytest), or no backend change; service-dependent skips are reported
- [ ] Migrations checked (upgrade, check, downgrade and back), or no schema change
- [ ] Generated API client refreshed and new routes in the access registry, or no API change
- [ ] Web checks pass (lint, format, types, tests, build, size, e2e), or no web change
- [ ] ADR added for each significant decision; area conventions updated in docs/conventions.md
- [ ] Relevant checks and their outcomes are described; unrun checks have reasons
- [ ] Fresh-session review in Claude Code or Codex done and its findings fixed
- [ ] Owner questions resolved and required CI green before the owner merges
