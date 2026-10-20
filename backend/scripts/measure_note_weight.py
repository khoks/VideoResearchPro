"""S-8.5.2: retrieval-level measurement of NOTE_RETRIEVAL_WEIGHT.

Pre-registered in docs/notes/2026-10-19-s852-note-weight-measurement.md;
the notes, questions, metrics and decision rule live there and are copied
here verbatim. No LLM calls: the original question only, no sub-queries.

Reads a COPY of a Chroma store (never the user's own) and the reference
job's approved document ids from a database opened read-only. Writes the
synthetic notes into the copy's notes collection under a synthetic tenant.

    python scripts/measure_note_weight.py \
        --chroma-copy <scratch dir with a copy of data/chroma> \
        --database <path to videoresearchpro.db> \
        --job 0d4db8c3-5f3a-482e-aa00-784d94bb548c \
        --out <results.json>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TENANT = "measure-s852"
NOTES = {
    "N1": "My view: context engineering is mostly about pruning, not adding. Every time I stuffed more docs into the window the agent got worse; trimming to the three files it actually edits fixed it.",
    "N2": "I stopped using most MCP servers. A plain CLI the agent can call is easier to debug and burns far fewer tokens on tool descriptions.",
    "N3": "Writing the spec first only works if the spec is short. Two pages at most, or the agent drifts and I end up reviewing the spec instead of the code.",
    "N4": "Multi-agent setups failed for me when the agents shared one scratchpad. Giving each sub-agent its own context and a single orchestrator is what worked.",
    "N5": "Long contexts degrade quietly. I now restart the session after roughly 100k tokens instead of trusting the model to remember the early instructions.",
    "N6": "Sourdough: feed the starter with rye the night before and bake covered for the first twenty minutes.",
    "N7": "Marathon plan: long run on Sundays, add two kilometres a week, rest week every fourth week.",
    "N8": "Remember to file the property tax return before the end of the month.",
    "N9": "Lisbon trip: tram 28 is packed by ten; walk up to the castle early instead.",
    "N10": "The fiddle-leaf fig wants bright indirect light and water only when the top soil is dry.",
}
OFF_TOPIC = {"N6", "N7", "N8", "N9", "N10"}
QUESTIONS = {
    "Q1": "What is context engineering and how should I manage what goes into an agent's context window?",
    "Q2": "Should I use MCP servers with coding agents, and what are the alternatives?",
    "Q3": "How does spec-driven development work with AI coding agents?",
    "Q4": "What orchestration patterns make multi-agent systems work in practice?",
    "Q5": "Why does LLM performance degrade as the input context gets longer?",
    "Q6": "How do I set up a local agentic coding workflow?",
    "Q7": "How can I reduce errors when using Cursor or other AI IDEs?",
    "Q8": "What are the main agentic AI design patterns?",
    "Q9": "How do self-improving agents learn from their own feedback?",
    "Q10": "What does an AI engineering workflow look like at a product company?",
}
PAIRED = {"Q1": "N1", "Q2": "N2", "Q3": "N3", "Q4": "N4", "Q5": "N5"}
WEIGHTS = [1.0, 1.5, 2.0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chroma-copy", required=True)
    ap.add_argument("--database", required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from app.config import settings

    settings.CHROMA_PERSIST_DIR = args.chroma_copy
    settings.NOTES_INDEX_ENABLED = True

    from app.agents import qa_agent
    from app.models.note import Note
    from app.services import chroma_service, note_index

    con = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)
    doc_ids = [r[0] for r in con.execute(
        "select document_id from job_documents where job_id = ? and approved = 1", (args.job,)
    )]
    con.close()
    assert doc_ids, "no approved documents for that job"

    col = note_index.get_notes_collection()
    existing = col.get(where={"tenant_id": TENANT})["ids"]
    if existing:
        col.delete(ids=existing)
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    note_ids = {}
    notes, metas = [], []
    for nid, body in NOTES.items():
        note = Note(id=f"s852-{nid}", tenant_id=TENANT, target_type="job", target_id=args.job,
                    body_md=body, motivation="commenting", created_at=now, updated_at=now)
        note_ids[note.id] = nid
        notes.append(note)
        metas.append(note_index.note_metadata(note, None))
    col.upsert(ids=[note_index.note_vector_id(n.id) for n in notes],
               documents=[n.body_md for n in notes], metadatas=metas)

    def label(chunk: dict) -> str:
        m = chunk["metadata"]
        if m.get("source_type") == "note":
            return note_ids.get(m.get("note_id"), "note?")
        return f"chunk:{m.get('document_id')}:{m.get('chunk_index')}"

    per_question = {}
    for qid, question in QUESTIONS.items():
        baseline = chroma_service.query_collection(
            question, n_results=settings.RAG_TOP_K, document_ids=doc_ids,
            distance_threshold=settings.RAG_DISTANCE_THRESHOLD,
        )
        base_labels = [label(c) for c in baseline]
        base_channels = {c["metadata"].get("channel_name") for c in baseline}
        all_notes = note_index.query_notes(question, TENANT, distance_threshold=float("inf"),
                                           n_results=len(NOTES))
        raw = {note_ids[n["metadata"]["note_id"]]: round(n["distance"], 4) for n in all_notes}
        row = {
            "top_chunk_distance": round(baseline[0]["distance"], 4) if baseline else None,
            "note_raw_distances": raw,
            "baseline_size": len(baseline),
            "weights": {},
        }
        for w in WEIGHTS:
            settings.NOTE_RETRIEVAL_WEIGHT = w
            merged = qa_agent._with_notes(baseline, question, TENANT, None, {})
            labels = [label(c) for c in merged]
            notes_in = [x for x in labels if x.startswith("N")]
            channels = {c["metadata"].get("channel_name") for c in merged if c["metadata"].get("source_type") != "note"}
            paired = PAIRED.get(qid)
            row["weights"][str(w)] = {
                "notes_in": notes_in,
                "paired_rank": (labels.index(paired) + 1) if paired and paired in labels else None,
                "off_topic_in": [n for n in notes_in if n in OFF_TOPIC],
                "displaced": len([x for x in base_labels if x not in labels]),
                "channel_delta": len(channels) - len(base_channels),
            }
        per_question[qid] = row

    summary = {}
    for w in WEIGHTS:
        k = str(w)
        paired_rows = [per_question[q]["weights"][k] for q in PAIRED]
        ranks = [r["paired_rank"] for r in paired_rows if r["paired_rank"]]
        all_rows = [per_question[q]["weights"][k] for q in QUESTIONS]
        summary[k] = {
            "M1_paired_recall": sum(1 for r in paired_rows if r["paired_rank"]) / len(paired_rows),
            "M2_paired_mean_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
            "M3_off_topic_leaks": sum(len(r["off_topic_in"]) for r in all_rows),
            "M4_mean_displaced": round(sum(r["displaced"] for r in all_rows) / len(all_rows), 2),
            "M5_mean_channel_delta": round(sum(r["channel_delta"] for r in all_rows) / len(all_rows), 2),
            "unpaired_question_note_hits": {q: per_question[q]["weights"][k]["notes_in"]
                                            for q in QUESTIONS if q not in PAIRED},
        }
    result = {"job": args.job, "documents": len(doc_ids), "top_k": settings.RAG_TOP_K,
              "threshold": settings.RAG_DISTANCE_THRESHOLD, "summary": summary,
              "per_question": per_question}
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    col.delete(ids=[note_index.note_vector_id(n.id) for n in notes])


if __name__ == "__main__":
    main()
