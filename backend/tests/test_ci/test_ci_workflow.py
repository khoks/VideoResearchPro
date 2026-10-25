"""T-8.8.4.3 — what .github/workflows/ci.yml promises that a green run cannot show.

GitHub Actions has no dry run, and both properties below fail silently: CI
stays green while it gets slower or stops covering a commit. So they are read
out of the workflow file here.

  * The model cache is saved only from a download step that finished. A cache
    key is immutable: a save after a cancelled or failed download (``always()``
    fires on both) pins a partial copy, and every later run restores it, skips
    the download and fetches the missing models at test time, for good.
  * Only pull-request runs cancel each other. A push to master runs in a
    concurrency group of its own, so every merge commit gets a full result
    even when merges land minutes apart. A shared group with
    ``cancel-in-progress`` off is not enough: a third run in the group still
    replaces the second one's pending run.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

_CI_YML = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
_EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(_CI_YML.read_text(encoding="utf-8"))


def _evaluate(expression: str, github: SimpleNamespace):
    """Evaluate the subset of the GitHub expression language the workflow
    uses: ``github.*`` lookups, ``==``, ``&&`` and ``||``. Python's ``and`` /
    ``or`` return an operand, exactly as GitHub's do, so ``a && b || c``
    means the same thing in both."""
    python = expression.replace("&&", " and ").replace("||", " or ")
    return eval(python, {"__builtins__": {}}, {"github": github})  # noqa: S307


def _render(value, github: SimpleNamespace):
    """A workflow value as GitHub sees it at run time: a value that is one
    whole ``${{ }}`` keeps the expression's type, anything else is a string."""
    if not isinstance(value, str):
        return value
    whole = _EXPR.fullmatch(value.strip())
    if whole:
        return _evaluate(whole.group(1), github)
    return _EXPR.sub(lambda m: str(_evaluate(m.group(1), github)), value)


def _concurrency(workflow: dict, *, event_name: str, ref: str, run_id: int):
    github = SimpleNamespace(event_name=event_name, ref=ref, run_id=run_id,
                             sha=f"sha{run_id}", workflow="CI")
    block = workflow["concurrency"]
    return _render(block["group"], github), bool(_render(block["cancel-in-progress"], github))


def _backend_steps(workflow: dict) -> list[dict]:
    return workflow["jobs"]["backend"]["steps"]


def _step(steps: list[dict], uses_prefix: str) -> tuple[int, dict]:
    found = [(i, s) for i, s in enumerate(steps) if str(s.get("uses", "")).startswith(uses_prefix)]
    assert len(found) == 1, f"expected exactly one {uses_prefix} step, found {len(found)}"
    return found[0]


def _gating_download(steps: list[dict], save: dict) -> tuple[int, dict]:
    """The step whose success the cache save waits for."""
    condition = str(save.get("if", ""))
    found = [(i, s) for i, s in enumerate(steps)
             if s.get("id") and f"steps.{s['id']}.outcome == 'success'" in condition]
    assert len(found) == 1, (
        "the model-cache save must be gated on its download step's outcome being 'success'; "
        f"its condition is {condition!r}"
    )
    return found[0]


def _job_env(workflow: dict) -> dict:
    return {**workflow.get("env", {}), **workflow["jobs"]["backend"].get("env", {})}


def _resolved(value: str, env: dict) -> str:
    """Substitute ``${{ env.NAME }}`` so two steps can be compared on the
    value they resolve to, however each spells it."""
    return re.sub(r"\$\{\{\s*env\.(\w+)\s*\}\}", lambda m: str(env[m.group(1)]), value)


# ── concurrency ──────────────────────────────────────────────────────────


def test_a_new_push_to_a_pull_request_cancels_the_run_it_supersedes(workflow) -> None:
    first = _concurrency(workflow, event_name="pull_request", ref="refs/pull/7/merge", run_id=1)
    second = _concurrency(workflow, event_name="pull_request", ref="refs/pull/7/merge", run_id=2)
    assert first[0] == second[0], "two runs of one pull request must share a group"
    assert second[1] is True, "a pull request's newer run must cancel the older one"


def test_pull_requests_do_not_cancel_each_other(workflow) -> None:
    one = _concurrency(workflow, event_name="pull_request", ref="refs/pull/7/merge", run_id=1)
    other = _concurrency(workflow, event_name="pull_request", ref="refs/pull/8/merge", run_id=2)
    assert one[0] != other[0]


def test_every_push_to_master_runs_to_completion(workflow) -> None:
    """Two merges minutes apart: neither run is cancelled, and neither is left
    pending where a third merge's run could replace it."""
    groups = set()
    for run_id in (101, 102, 103):
        group, cancels = _concurrency(workflow, event_name="push", ref="refs/heads/master", run_id=run_id)
        assert cancels is False, "a push to master must never cancel another run"
        groups.add(group)
    assert len(groups) == 3, f"pushes to master share a concurrency group: {sorted(groups)}"


def test_a_push_to_master_never_lands_in_a_pull_requests_group(workflow) -> None:
    push, _ = _concurrency(workflow, event_name="push", ref="refs/heads/master", run_id=101)
    pr, _ = _concurrency(workflow, event_name="pull_request", ref="refs/pull/7/merge", run_id=102)
    assert push != pr


# ── model cache ──────────────────────────────────────────────────────────


def test_the_model_cache_is_saved_only_after_its_download_step_succeeded(workflow) -> None:
    steps = _backend_steps(workflow)
    _, save = _step(steps, "actions/cache/save@")
    condition = str(save.get("if", ""))
    for status_function in ("always()", "cancelled()", "failure()"):
        assert status_function not in condition, (
            f"the model-cache save runs on {status_function}: a cancelled or failed "
            "download would be saved under an immutable key"
        )

    _, download = _gating_download(steps, save)
    _, restore = _step(steps, "actions/cache/restore@")
    assert restore.get("id") and f"steps.{restore['id']}.outputs.cache-hit" in str(download.get("if", "")), (
        "the download step must run only on a cache miss"
    )


def test_the_download_step_fills_every_cached_path_before_the_save(workflow) -> None:
    """The save sits between the download and the tests, so what it stores is
    exactly what the download step wrote. That step must therefore fetch both
    models the cache lists, not leave one to a test that may never run."""
    steps = _backend_steps(workflow)
    save_index, save = _step(steps, "actions/cache/save@")
    download_index, download = _gating_download(steps, save)
    pytest_index = next(i for i, s in enumerate(steps) if "pytest" in str(s.get("run", "")))
    assert download_index < save_index < pytest_index

    paths = str(save["with"]["path"])
    script = str(download["run"])
    if "huggingface" in paths:
        assert "SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')" in script
    if ".cache/chroma" in paths:
        assert "DefaultEmbeddingFunction" in script, (
            "~/.cache/chroma is cached but the download step does not fetch Chroma's default ONNX model"
        )


def test_restore_and_save_use_the_same_key_and_paths(workflow) -> None:
    steps = _backend_steps(workflow)
    env = _job_env(workflow)
    _, restore = _step(steps, "actions/cache/restore@")
    _, save = _step(steps, "actions/cache/save@")
    assert _resolved(restore["with"]["key"], env) == _resolved(save["with"]["key"], env)
    assert restore["with"]["path"] == save["with"]["path"]
