import pytest

from listenup.ai.evals.paths import needs_smoke


@pytest.mark.parametrize(
    "path",
    [
        "apps/api/src/listenup/ai/prompts/grade_gist/v2.md",
        "apps/api/src/listenup/ai/prompts/grade_gist/v2.schema.json",
        "apps/api/src/listenup/ai/providers/fake.py",
        "apps/api/src/listenup/ai/ai.yaml",
    ],
)
def test_smoke_path_selection(path):
    assert needs_smoke([path])


@pytest.mark.parametrize(
    "path",
    [
        "apps/api/src/listenup/ai/ai.fake.yaml",
        "apps/api/src/listenup/ai/gateway.py",
        "apps/api/src/listenup/ai/providers_extra.py",
        "apps/api/src/listenup/ai/prompts_old/v1.md",
        "apps/web/src/App.tsx",
        ".github/workflows/ci.yml",
        "ai-evals/fixtures/gist.json",
    ],
)
def test_unrelated_paths_do_not_run_smoke(path):
    assert not needs_smoke([path])


def test_empty_diff_does_not_run_smoke():
    assert not needs_smoke([])
