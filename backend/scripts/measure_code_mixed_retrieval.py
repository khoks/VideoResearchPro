"""Does retrieval need an English rendering of code-mixed chunks? (T-1.16.2.5)

Same content in three scripts, so only the script varies:

1. Real Devanagari Hinglish chunks from Hindi-ASR transcripts, chunked
   exactly as ingest chunks them.
2. The same chunks romanised the way people type Hinglish (LLM).
3. The same chunks rendered in English (LLM).

For a sample of chunks the LLM also writes one English question that only
that chunk answers. Because those questions come from the same call that
writes the English rendering, they can share its wording; `question_mini`
questions, written by a different model from the Devanagari alone, remove
that coupling and are the ones reported. Each question is embedded with the production model and
ranked against the whole pool in each script; the report is recall@k and MRR
per condition. Everything the LLM produced is cached so the measurement is
re-scorable without new calls.

    ./venv/Scripts/python scripts/measure_code_mixed_retrieval.py \
        --env-file ../../backend/.env --videos Y4qO9unerGs lsf060bLH_Y cE-Ej1ycXtk
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RENDER_PROMPT = """Below are numbered transcript chunks of Indian speakers, written in Devanagari (Hindi with English words transcribed into Devanagari).

For each chunk produce two renderings:
- "english": a faithful English translation of the whole chunk. Keep technical terms and names.
- "roman": the same words written the way people TYPE Hinglish in Latin letters: Hindi words romanised casually ("mujhe nahi pata", "kar sakte hain"), English words in normal English spelling ("machine learning", "program"). Do not translate; only change the script.
{question_instruction}
Chunks:
{chunks}

Return ONLY JSON: {{"chunks": [{{"i": 0, "english": "...", "roman": "..."{question_field}}}, ...]}}"""

QUESTION_INSTRUCTION = """- "question": for the chunks marked with *, one specific English question that this chunk answers and the other chunks of the same lecture would not. A learner's question, not a quote."""


def load_env(env_file: Path) -> None:
    from dotenv import dotenv_values

    env = dotenv_values(env_file)
    for k in ("OPENAI_API_KEY",):
        if env.get(k):
            os.environ[k] = env[k]


def build_pool(db: Path, videos: list[str]) -> list[dict]:
    from app.utils.chunking import chunk_transcript

    c = sqlite3.connect(db)
    pool = []
    for vid in videos:
        row = c.execute(
            "select segments_json from transcript_cache where video_id=?", (vid,)
        ).fetchone()
        segs = json.loads(row[0])
        for ch in chunk_transcript(segs, video_metadata={"video_id": vid}):
            pool.append({"video_id": vid, "devanagari": ch["text"]})
    return pool


def render(pool: list[dict], sample: set[int], batch: int = 8) -> None:
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    from app.services.llm_service import response_text

    llm = ChatOpenAI(model="gpt-5.6-luna", temperature=0, max_tokens=12000,
                     model_kwargs={"reasoning_effort": "none"})
    for b in range(0, len(pool), batch):
        idx = list(range(b, min(b + batch, len(pool))))
        if all("english" in pool[i] for i in idx):
            continue
        marked = "\n\n".join(
            f"[{k}]{'*' if i in sample else ''} {pool[i]['devanagari']}" for k, i in enumerate(idx)
        )
        has_q = any(i in sample for i in idx)
        prompt = RENDER_PROMPT.format(
            chunks=marked,
            question_instruction=QUESTION_INSTRUCTION if has_q else "",
            question_field=', "question": "..."' if has_q else "",
        )
        raw = response_text(llm.invoke([HumanMessage(content=prompt)]))
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        for item in json.loads(raw)["chunks"]:
            i = idx[int(item["i"])]
            pool[i]["english"] = item.get("english", "")
            pool[i]["roman"] = item.get("roman", "")
            if i in sample and item.get("question"):
                pool[i]["question"] = item["question"]
        print(f"rendered {min(b + batch, len(pool))}/{len(pool)}", flush=True)


def score(pool: list[dict], question_key: str = "question") -> dict:
    import numpy as np

    from app.services.embedding_service import encode

    qs = [(i, p[question_key]) for i, p in enumerate(pool) if p.get(question_key)]
    qv = np.array(encode([q for _, q in qs]))
    out = {"questions": len(qs), "pool": len(pool)}
    for cond in ("devanagari", "roman", "english"):
        dv = np.array(encode([p[cond] for p in pool]))
        sims = qv @ dv.T / (np.linalg.norm(qv, axis=1)[:, None] * np.linalg.norm(dv, axis=1)[None, :])
        ranks = []
        for row, (i, _) in zip(sims, qs):
            order = np.argsort(-row)
            ranks.append(int(np.where(order == i)[0][0]) + 1)
        ranks = np.array(ranks)
        out[cond] = {
            "recall@1": round(float((ranks <= 1).mean()), 3),
            "recall@5": round(float((ranks <= 5).mean()), 3),
            "recall@15": round(float((ranks <= 15).mean()), 3),
            "mrr": round(float((1.0 / ranks).mean()), 3),
            "median_rank": int(np.median(ranks)),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    ap.add_argument("--db", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "videoresearchpro.db")
    ap.add_argument("--videos", nargs="+", required=True)
    ap.add_argument("--questions", type=int, default=60)
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--question-key", default="question",
                    help="'question' (written by the rendering call) or 'question_mini' "
                         "(written by a different model from the Devanagari alone)")
    args = ap.parse_args()

    if args.cache.exists():
        pool = json.loads(args.cache.read_text(encoding="utf-8"))
    else:
        pool = build_pool(args.db, args.videos)
    if not all("english" in p for p in pool):
        load_env(args.env_file)
        rng = random.Random(20261019)
        sample = set(rng.sample(range(len(pool)), min(args.questions, len(pool))))
        render(pool, sample)
        args.cache.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(score(pool, args.question_key), indent=1))


if __name__ == "__main__":
    main()
