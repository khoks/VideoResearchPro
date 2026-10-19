"""Evaluate the code-mixing detectors on the hand-labelled set (S-1.16.2).

    # lexicon detector, free, deterministic
    ./venv/Scripts/python scripts/eval_code_mixing.py --split test

    # LLM detector: calls `code_mixing_detect` live and caches its raw
    # answers to tests/fixtures/code_mixing/llm_predictions.json, which the
    # test suite then scores without calling a provider
    ./venv/Scripts/python scripts/eval_code_mixing.py --llm --split all

Method and results: docs/notes/2026-10-19-code-mixing-detection.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import code_mixing_eval as ev  # noqa: E402
from app.services import code_mixing_service as cm  # noqa: E402

LLM_CACHE = ev.FIXTURE.parent / "llm_predictions.json"


def _majority(text: str) -> str:
    p = cm.profile_text(text)
    return "hi" if p["hi_tokens"] > p["en_tokens"] else "en"


def lexicon_predictions(units: list[dict]) -> dict[str, list[str]]:
    return {u["id"]: [t for _, t in cm.tag_tokens(u["text"])] for u in units}


def llm_predictions(
    units: list[dict], cache: dict, max_gap: int = cm.SPAN_MAX_GAP
) -> dict[str, list[str] | None]:
    out = {}
    for u in units:
        raw = cache.get(u["id"])
        out[u["id"]] = (
            None if raw is None
            else [t for _, t in cm.spans_to_tags(u["text"], raw["hi"], max_gap=max_gap)[0]]
        )
    return out


def load_provider_keys(env_file: Path) -> None:
    """Take provider keys from the .env file, not the process environment.

    Windows user-level OPENAI_API_KEY / GOOGLE_API_KEY exist on the dev box
    and shadow backend/.env under pydantic-settings precedence. Must run
    before anything imports app.config.
    """
    import os

    from dotenv import dotenv_values

    env = dotenv_values(env_file)
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        if env.get(k):
            os.environ[k] = env[k]


def run_llm(units: list[dict]) -> dict:
    from app.services.llm_routing import resolve_config

    cfg = resolve_config("code_mixing_detect")
    t0 = time.time()
    results = cm.llm_detect([u["text"] for u in units])
    elapsed = time.time() - t0
    return {
        "model": f"{cfg.provider}:{cfg.model}:{cfg.reasoning}",
        "elapsed_s": round(elapsed, 1),
        "predictions": {u["id"]: r for u, r in zip(units, results)},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=("dev", "test", "all"), default="test")
    ap.add_argument("--llm", action="store_true", help="call the LLM detector live and cache it")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--env-file", type=Path,
                    default=Path(__file__).resolve().parents[1] / ".env",
                    help="where provider keys come from (a worktree has no .env)")
    args = ap.parse_args()
    if args.llm:
        load_provider_keys(args.env_file)

    units = ev.load_units()
    if args.split != "all":
        units = [u for u in units if u["split"] == args.split]

    report: dict = {"split": args.split}
    t0 = time.perf_counter()
    lex = lexicon_predictions(units)
    report["lexicon_ms_per_unit"] = round((time.perf_counter() - t0) * 1000 / len(units), 3)
    report["lexicon"] = ev.score(units, lex)
    # T-1.16.2.2: matrix language by system-morpheme vote, against the
    # proportion-only baseline (whichever language has more words).
    report["lexicon_matrix"] = ev.matrix_accuracy(
        units, {u["id"]: cm.matrix_language(cm.tag_tokens(u["text"])) for u in units}
    )
    report["majority_matrix"] = ev.matrix_accuracy(
        units, {u["id"]: _majority(u["text"]) for u in units}
    )

    if args.llm:
        all_units = ev.load_units()
        run = run_llm(all_units)
        LLM_CACHE.write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"cached {len(run['predictions'])} LLM answers in {run['elapsed_s']}s -> {LLM_CACHE}")
    if LLM_CACHE.exists():
        cache = json.loads(LLM_CACHE.read_text(encoding="utf-8"))
        report["llm_model"] = cache["model"]
        report["llm"] = ev.score(units, llm_predictions(units, cache["predictions"]))
        # Contiguous-only span matching, for comparison: what the model's
        # answers score if its spans are taken literally as runs.
        report["llm_strict"] = ev.score(units, llm_predictions(units, cache["predictions"], 0))
        report["llm_matrix"] = ev.matrix_accuracy(
            units, {k: (v or {}).get("matrix") for k, v in cache["predictions"].items()}
        )

    if args.json:
        print(json.dumps(report, indent=1))
        return
    for name in ("lexicon", "llm", "llm_strict"):
        if name not in report:
            continue
        print(f"== {name} ({args.split}) {report.get('llm_model', '') if name.startswith('llm') else ''}")
        for grp in ("latin", "devanagari", "all"):
            s = report[name][grp]
            th, uh = s["token_hindi"], s["unit_contains_hindi"]
            print(f"  {grp:10} units={s['units']:3}  token P={th['precision']:.3f} R={th['recall']:.3f} "
                  f"F1={th['f1']:.3f}  unit P={uh['precision']:.3f} R={uh['recall']:.3f} "
                  f"(fn={uh['fn']}, fp={uh['fp']})  share MAE={s['hindi_share_mae']:.3f}")
        if report[name]["missing_units"]:
            print("  missing:", report[name]["missing_units"])
    print("matrix, system-morpheme vote:", report["lexicon_matrix"])
    print("matrix, word majority (baseline):", report["majority_matrix"])
    if "llm_matrix" in report:
        print("matrix, LLM:", report["llm_matrix"])
    print("lexicon ms/unit:", report["lexicon_ms_per_unit"])


if __name__ == "__main__":
    main()
