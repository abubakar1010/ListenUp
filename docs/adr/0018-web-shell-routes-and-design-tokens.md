# ADR 0018: Web shell with declarative routes, lazy pages and design tokens in Tailwind

- Status: Accepted
- Date: 2026-10-03

## Context

Issue #33 builds the web client's shell: routes for auth, library and sessions, a signed-in guard, error display (NFR-USE-3), the practice screen layout (UI-1), route-based code splitting with initial JavaScript under 200 KB compressed, and Tailwind styled from the design system (v2, 2 Oct 2026). React Router offers two styles: declarative `<Routes>` and a data router (`createBrowserRouter` with loaders, `lazy` routes and `errorElement`). Data loading is already TanStack Query's job (Architecture 2), and several stories add routes in parallel.

## Decision

- **Declarative routes in one table.** `src/App.tsx` holds every route. Layout routes provide the header (`PublicLayout`, `AppLayout`); `RequireAuth` and `RedirectIfSignedIn` are pathless guard routes. Server data stays in TanStack Query, so loaders are not needed. Each layout wraps its outlet in `RouteBoundary` (an error boundary and a Suspense fallback) instead of `errorElement`.
- **Code splitting by route** with `React.lazy`: every page except sign-in and register (where signed-out visitors land) is its own chunk. `pnpm size` fails CI when the JavaScript that `index.html` loads goes over 200 KB gzip.
- **Return after sign-in** through a `next` search parameter rather than router state, so it survives a reload. Only same-site paths are accepted (`src/auth/next.ts`).
- **Errors.** `describeError` turns any error into a title, the server's `detail`, a next step and one action (retry, reload, sign in, go to the library). The problem's `title` is the HTTP phrase, so the client picks friendlier titles by status and uses the problem's title only as a fallback. Clients still branch on `code`.
- **Design tokens as Tailwind theme variables** in `src/index.css` (`@theme`), named after the design system's tokens (`bg-surface-raised`, `text-ink-muted`, `text-title`). The dark theme redefines the same variables under `prefers-color-scheme: dark`. Radius tokens map to `rounded-sm`, `rounded-md` and `rounded-lg` because Tailwind's `rounded-s` is a logical-side utility. Fonts are self-hosted from `@fontsource` packages rather than loaded from Google Fonts, so a page view sends no request to a third party.

## Consequences

Adding a page means adding a lazy import and a `<Route>` in `App.tsx`. Pages render their own `<main>`; the skip link and focus after navigation find it without an id. A change of route moves focus to the new `<main>` only after the learner has interacted with the page, so redirects on first load behave like a fresh page. If loaders or route-level data prefetching become worth having, moving to the data router is a contained change to `App.tsx`, `main.tsx` and the test helpers.
