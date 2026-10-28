# ADR 0072: praat-parselmouth is compiled in a throwaway stage, so worker-media runs on arm64

- Status: Accepted
- Date: 2026-10-28
- Story: [#232](https://github.com/abubakar1010/ListenUp/issues/232)
- Requirements: NFR-AI-3, NFR-SEC-1; ADR 0028 (speech libraries only in the media image), ADR 0049 (media sandbox), ADR 0070 (Arm stage 0 host), ADR 0071 (multi-arch images)

## Context

`praat-parselmouth` 0.4.7, the latest release, publishes no Linux arm64 wheel, so building `worker-media` for arm64 compiled it from the sdist and failed for lack of a C++ compiler (evidenced on #232). A compiler in the runtime image is not acceptable: the media worker handles untrusted uploads (ADR 0049), and a toolchain gives code that escapes the sandbox more to work with and adds hundreds of megabytes.

## Decision

1. **A `parselmouth-wheel` stage builds the wheel.** It starts from `base`, installs `build-essential` and `cmake`, and runs `pip wheel --no-deps` for the exact version in `uv.lock` (`ARG PARSELMOUTH_VERSION`, checked against the lock by `tests/unit/test_backend_dockerfile.py`). On amd64 pip downloads the published wheel; on arm64 it compiles.
2. **`worker-media` installs that wheel and never builds.** `uv sync --no-install-package praat-parselmouth` skips the sdist, then `uv pip install --no-deps` installs the wheel from a bind mount of the stage (no image layer, no index). The runtime chain contains no compiler; a test fails if one appears in any runtime stage.
3. **All six images are multi-arch.** `worker-media` joins the release matrix and the Deploy check's native arm64 job as `linux/amd64,linux/arm64`; `AMD64_ONLY` in `test_release_workflow.py` is empty.
4. **The release reuses the native build's layers.** Compiling Praat under QEMU would run on every release, so the Release job also reads the Deploy check's `arm64-<image>` cache scope. The first release after a cache miss compiles under QEMU and is slow.

## Consequences

- The version in the Dockerfile must move with `uv.lock`; the test catches a mismatch.
- A new upstream arm64 wheel would make the stage pointless, not wrong: pip would download it. The stage can then be dropped.
- Measured on a development machine (see the pull request): the compile and the arm64 image numbers. The Deploy check's native build records the real CI figure.
- `worker-media` on arm64 is built and imports on arm64 but not yet benchmarked; B1 to B4 on the host (#233) do that.
