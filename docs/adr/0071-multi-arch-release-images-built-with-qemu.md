# ADR 0071: Multi-arch release images, built under QEMU and checked natively

- Status: Accepted
- Date: 2026-10-28
- Story: [#231](https://github.com/abubakar1010/ListenUp/issues/231)
- Requirements: CI-A, NFR-REL-4; ADR 0066 (deploy pipeline), ADR 0073 (Arm stage 0 host, Proposed)

## Context

ADR 0073 proposes an Arm VM as the stage 0 host. The Release workflow built every image once on an x86_64 runner with no `platforms` setting, so the images were amd64 only and would not start on an Arm host (`exec format error`). The release rules from ADR 0066 must not change: a commit is built once, `sha-<12 hex>` and `r<run number>` name the same digest, nothing is tagged `latest`, and a re-run or manual deploy of a built commit only adds an `r<n>` tag.

## Decision

1. **Each release image is a multi-platform manifest.** `release.yml` gives every matrix entry a `platforms` value and passes it to `docker/build-push-action`. `api`, `worker`, `backup`, `signature-update` and `edge` are `linux/amd64,linux/arm64`. Because the existing lookup (`imagetools inspect`) and retag (`imagetools create`) work on manifest lists, the build-once and two-tag rules are unchanged.
2. **arm64 is built under QEMU in the Release job.** One job per image still produces one manifest, which keeps the workflow small and the tag logic untouched. Native Arm runners with a per-platform build and a manifest merge job would be faster, but they change the tag and lookup logic, which cannot be exercised before it runs on `main`; this can replace QEMU later if the release time needs it.
3. **The Deploy check builds arm64 natively on every change.** A new `arm64-images` job on `ubuntu-24.04-arm` (free for a public repository) builds the five images with `push: false`, so a change that breaks arm64 fails the pull request, not a release.
4. **The web build stays on the builder's architecture.** `web.Dockerfile` pins its Node stage to `$BUILDPLATFORM`: the output is static files, and emulating `pnpm build` would only slow the release.
5. **`worker-media` stays amd64 only for now.** *(Superseded in part by [ADR 0072](0072-parselmouth-wheel-built-in-a-throwaway-stage.md): it is now multi-arch too.)* Its `praat-parselmouth` dependency has no Linux arm64 wheel and its build needs a C++ toolchain the base image lacks ([#232](https://github.com/abubakar1010/ListenUp/issues/232)). When #232 lands, add `linux/arm64` to its matrix entry and the Deploy check, and remove it from `AMD64_ONLY` in `apps/api/tests/unit/test_release_workflow.py`.

## Consequences

- An Arm host can pull `api`, `worker`, `backup`, `signature-update` and `edge`, but it still cannot run the speech worker until #232; the stage 0 benchmarks need that image.
- Release builds get slower: the arm64 layers are emulated and not cached across releases (a release only reads the CI cache scopes, which hold amd64). The first measured time is recorded in the pull request.
- Images pulled on x86 hosts are unchanged; Docker picks the platform from the manifest.
- The Release workflow itself runs only on `main`, so its merged form is first exercised by the first release after this change; the build commands were run beforehand with QEMU on a development machine, and the YAML is checked by actionlint and by tests that read it as data.
