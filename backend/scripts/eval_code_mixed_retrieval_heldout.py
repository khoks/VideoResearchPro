"""Retrieval on held-out Hindi sources through the PRODUCTION renderer (T-1.16.2.6).

Replicates D-084's measurement on sources nothing was tuned on, but renders
with the deployed path (`code_mixing_service.render_english`, use case
`code_mixing_render_english`) rather than the measurement script's own call.
Questions are written by a different model (gpt-5.4-mini) from the original
chunk text alone. Reports recall@k and MRR for the original vectors against
the rendered ones, over the pool of all chunks.

    ./venv/Scripts/python scripts/eval_code_mixed_retrieval_heldout.py \\
        --env-file ../../backend/.env --db ../../backend/data/videoresearchpro.db \\
        --videos QSlta0EnGJo GSA8jvzIjjQ --cache heldout_retrieval.json
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

QUESTION_PROMPT = (
    "Below is a chunk of a lecture or conversation transcript in Hindi (it may mix in English). "
    "Write ONE specific question, in English, that a listener might ask and that this chunk "
    "answers. Use your own words; do not translate the chunk. Return only the question.\n\n{chunk}"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", type=Path, required=True)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--videos", nargs="+", required=True)
    ap.add_argument("--questions", type=int, default=50)
    ap.add_argument("--cache", type=Path, required=True)
    args = ap.parse_args()

    from dotenv import dotenv_values

    env = dotenv_values(args.env_file)
    for k in ("OPENAI_API_KEY",):
        if env.get(k):
            os.environ[k] = env[k]

    import numpy as np

    from app.services import chroma_service
    from app.services import code_mixing_service as cm
    from app.utils.chunking import chunk_transcript

    if args.cache.exists():
        pool = json.loads(args.cache.read_text(encoding="utf-8"))
    else:
        db = sqlite3.connect(args.db)
        pool = []
        for vid in args.videos:
            segs = json.loads(db.execute(
                "select segments_json from transcript_cache where video_id=?", (vid,)
            ).fetchone()[0])
            for ch in chunk_transcript(segs, video_metadata={"video_id": vid, "document_id": vid}):
                pool.append({"video_id": vid, "text": ch["text"], "meta": ch["metadata"]})
        rendered = cm.render_english([p["text"] for p in pool])
        for p, en in zip(pool, rendered):
            p["english"] = en
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI

        from app.services.llm_service import response_text

        mini = ChatOpenAI(model="gpt-5.4-mini", temperature=0, max_tokens=300,
                          model_kwargs={"reasoning_effort": "none"})
        rng = random.Random(20261019)
        for i in rng.sample(range(len(pool)), min(args.questions, len(pool))):
            pool[i]["question"] = response_text(mini.invoke(
                [HumanMessage(content=QUESTION_PROMPT.format(chunk=pool[i]["text"]))]
            )).strip()
        args.cache.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")

    ef = chroma_service._get_embedding_function()
    qs = [(i, p["question"]) for i, p in enumerate(pool) if p.get("question")]
    qv = np.array(ef([q for _, q in qs]))
    needs = [cm.needs_english_rendering(p["meta"]) for p in pool]
    rendered_ok = sum(1 for p, n in zip(pool, needs) if n and p.get("english"))
    report = {
        "pool": len(pool), "questions": len(qs),
        "chunks_needing_rendering": sum(needs), "rendered": rendered_ok,
    }
    conditions = {
        "original": [p["text"] for p in pool],
        # What production stores: the rendering where the chunk needs one and
        # it succeeded, the original otherwise.
        "production": [p["english"] if (n and p.get("english")) else p["text"] for p, n in zip(pool, needs)],
    }
    for name, texts in conditions.items():
        dv = np.array(ef(texts))
        # L2, as the collection measures it.
        d = ((qv[:, None, :] - dv[None, :, :]) ** 2).sum(-1)
        ranks = np.array([int(np.where(np.argsort(row) == i)[0][0]) + 1 for row, (i, _) in zip(d, qs)])
        report[name] = {
            "recall@1": round(float((ranks <= 1).mean()), 3),
            "recall@5": round(float((ranks <= 5).mean()), 3),
            "recall@15": round(float((ranks <= 15).mean()), 3),
            "mrr": round(float((1.0 / ranks).mean()), 3),
        }
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
