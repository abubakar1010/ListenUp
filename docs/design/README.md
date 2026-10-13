# Design documents

The files in this folder are the source of truth for ListenUp's design. They were exported from the Claude Docs on 2026-10-09 without content changes. From now on, change them by pull request; the Claude Docs are no longer edited. The first line of each file gives the Claude Docs original it came from.

| File | Covers |
| --- | --- |
| [prd.md](prd.md) | Product requirements: the problem, goals and non-goals, target users, the five practice modes and their rules, content intake, and the success metrics |
| [srs.md](srs.md) | Software requirements with stable IDs (FR-*, NFR-*, DR-*, AT-*): accounts, intake, transcripts, the plan and sessions, each mode, AI roles, and the acceptance tests |
| [architecture.md](architecture.md) | Software architecture: the stack, components and their boundaries, key flows, the API table, the repository layout and deployment |
| [system-design.md](system-design.md) | System design: capacity and cost estimates, the job system and its lanes, speech and storage efficiency, the data layer, real-time updates, failure modes and scaling stages |
| [database-design.md](database-design.md) | Database design: the full schema with DDL, constraints, indexes, row-level security and access rules, and data retention |
| [ux-decisions.md](ux-decisions.md) | UX decision log: every UI and UX decision behind the final interface (UX-01 to UX-36), the product decisions D1 to D18, and the audit findings with their fixes |

## Visual documents (not copied here)

These are visual, so they stay in Claude as published artifacts. Open them from these links.

- Final UI: https://claude.ai/artifact/SvknZCah3F9zuyBQyTNvov. Every screen and state from the wireframes at 1280 and 360 px in light and dark, with an interaction spec beside each screen.
- Design system v2: https://claude.ai/artifact/LsijobynKEzf1P5fvyYiRw. The design tokens for light and dark themes, type, spacing and motion, and the 19 components with their usage guidelines.
