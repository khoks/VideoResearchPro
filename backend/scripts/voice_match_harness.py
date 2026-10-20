"""Voice-match harness (S-3.3.4), the gate for S-3.4 ("speak as me").

Implements the procedure pre-registered in
docs/notes/2026-10-19-voice-match-preregistration.md, which fixes the
material, the conditions, the judges and the pass rule. Do not change any of
them here without a new pre-registration.

Modes:

    # Tiers (i) and (ii) plus the quality guard, on the synthetic writers.
    python scripts/voice_match_harness.py run --out ../docs/notes/2026-10-19-voice-match-result.json

    # Tier (iii), when a real user has the material: build the blinded pairs
    # from a COPY of a database, then score the user's answers.
    python scripts/voice_match_harness.py user-pairs --db copy.db --tenant <id> --out pairs.json --key key.json
    python scripts/voice_match_harness.py user-score --key key.json --answers answers.json

Keys come from ``--env-file`` (default backend/.env beside this script), read
before the app is imported, as in scripts/judge_pair.py.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import re
import sys
import tempfile
import time

BACKEND = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = BACKEND / "tests" / "fixtures" / "echo_voice"
sys.path.insert(0, str(BACKEND))

SEED = 3304
DRAFTER = ("openai", "gpt-5.5", "low")
JUDGES = (("anthropic", "claude-sonnet-5", "off"), ("google", "gemini-3.6-flash", "low"))


def _load_env(argv: list[str]) -> None:
    from dotenv import dotenv_values

    path = BACKEND / ".env"
    for i, arg in enumerate(argv):
        if arg == "--env-file" and i + 1 < len(argv):
            path = pathlib.Path(argv[i + 1])
    for k, v in (dotenv_values(path) or {}).items():
        if v is not None and (k.endswith("_API_KEY") or k.startswith("LLM_")):
            os.environ[k] = v


def _scratch_env() -> str:
    tmp = tempfile.mkdtemp(prefix="voice-harness-")
    os.environ["DATABASE_URL"] = f"sqlite:///{pathlib.Path(tmp, 'harness.db').as_posix()}"
    os.environ["CHROMA_PERSIST_DIR"] = str(pathlib.Path(tmp, "chroma"))
    os.environ["ECHO_SIGNAL_EXTRACTION"] = "off"
    return tmp


# ---------------------------------------------------------------------------
# Prompts (fixed by the pre-registration)

NEUTRAL = """{situation}

Write a short note of 40 to 90 words in {language} reacting to this. Reply with the note only."""

VOICE = """You are drafting a note as a specific person, in their voice. Below is what is known about how they write and think, and five things they actually wrote. Match their style: word choice, sentence length, punctuation, register, and the way they frame a point. Do not copy their sentences and do not mention the samples.

How they write and think:
{trait_card}

Things they wrote:
{exemplars}

Situation:
{situation}

Write a short note of 40 to 90 words in {language} reacting to this, as this person. Reply with the note only."""

JUDGE_VOICE = """Here are samples written by one person:

{samples}

Here are two drafts.

Draft A:
{a}

Draft B:
{b}

Which draft was more likely written by the person who wrote the samples? Answer A, B or UNSURE. Say UNSURE when they are about equally plausible. Reply with one word: A, B or UNSURE."""

JUDGE_QUALITY = """Someone wrote a short note reacting to this situation:
{situation}

Draft A:
{a}

Draft B:
{b}

Ignoring whose voice it is, which is the better note: clearer, more coherent, more useful to its reader? Reply with one word: A, B or TIE."""


def _client(cfg, max_tokens):
    from app.services.llm_routing import UseCaseConfig
    from app.services.llm_service import _build_from_config

    # Temperature 1.0, every provider's default: claude-sonnet-5 refuses an
    # explicit 0 ("temperature is deprecated for this model"), which stopped
    # the first launch at its first judge call, before any verdict.
    return _build_from_config(UseCaseConfig(*cfg), temperature=1.0, max_tokens=max_tokens)


def _ask(client, prompt: str) -> tuple[str, int, int]:
    from langchain_core.messages import HumanMessage

    from app.services.llm_service import response_text

    for attempt in range(3):
        try:
            r = client.invoke([HumanMessage(content=prompt)])
            usage = getattr(r, "usage_metadata", None) or {}
            return response_text(r).strip(), int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                raise
            print(f"  retry after {type(e).__name__}: {e}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def _verdict(raw: str, allowed: tuple[str, ...]) -> str:
    m = re.search(r"\b(" + "|".join(allowed) + r")\b", raw.upper())
    return m.group(1) if m else "UNPARSED"


# ---------------------------------------------------------------------------
# Building blocks


def _exemplars(notes: list[str], k: int = 5) -> list[str]:
    """Style diversity, not topic: spread over the mean-sentence-length range."""
    from app.services import echo_stylometry as stylo

    ranked = sorted(notes, key=lambda t: stylo.profile(t).mean_sentence_words)
    if len(ranked) <= k:
        return ranked
    idx = sorted({round(i * (len(ranked) - 1) / (k - 1)) for i in range(k)})
    return [ranked[i] for i in idx]


def _trait_card(db, tenant_id: str, situation: str) -> list[str]:
    from app.models.voice_signal import VoiceSignal
    from app.services import echo_personal_vectors as pv

    hits = pv.query_personal_context(tenant_id, situation, n=8, kinds=["signal"])
    lines = [h.text.split("\nExamples:")[0] for h in hits]
    cadence = (
        db.query(VoiceSignal)
        .filter(VoiceSignal.tenant_id == tenant_id, VoiceSignal.signal_type == "cadence", VoiceSignal.suppressed_at.is_(None))
        .all()
    )
    for c in cadence:
        line = f"style · cadence: {c.value}"
        if line not in lines:
            lines.append(line)
    return lines


def _setup_writer(db, name: str, persona: dict) -> str:
    from app.models.job import Job
    from app.models.library_qa_exchange import LibraryQAExchange
    from app.services import auth_service, note_service

    user = auth_service.create_user(db, email=f"{name}-{time.time_ns()}@example.com", password="pw" * 8)
    user.tier = "studio"
    job_id = f"job-{user.id[:8]}"
    db.add(Job(id=job_id, tenant_id=user.id, job_type="topic", topic="t", status="completed"))
    db.commit()
    for text in persona["notes"]:
        note_service.create_note(db, user.id, target_type="job", target_id=job_id, body_md=text)
    for q in persona["questions"]:
        db.add(LibraryQAExchange(tenant_id=user.id, question=q, answer="(answer)"))
    db.commit()
    return user.id


def run(out: pathlib.Path | None) -> dict:
    _scratch_env()
    from app.database import Base, SessionLocal, engine
    from app.services import echo_personal_vectors as pv
    from app.services import echo_signal_extraction as ex
    from app.services import echo_stylometry as stylo
    from app.services.model_pricing import pricing_for

    Base.metadata.create_all(engine)
    personas = json.loads((FIXTURES / "personas.json").read_text(encoding="utf-8"))["personas"]
    prompts = json.loads((FIXTURES / "draft_prompts.json").read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    drafter = _client(DRAFTER, 1200)
    judges = {f"{p}:{m}": _client((p, m, r), 2000 if p == "google" else 200) for p, m, r in JUDGES}
    held = {n: stylo.combine(stylo.profile(t) for t in p["held_out"]) for n, p in personas.items()}
    spend: dict[str, list[int]] = {}

    def charge(model: str, t_in: int, t_out: int) -> None:
        s = spend.setdefault(model, [0, 0])
        s[0] += t_in
        s[1] += t_out

    items = []
    db = SessionLocal()
    try:
        for name, persona in personas.items():
            tenant = _setup_writer(db, name, persona)
            report = ex.run(db, tenant)
            charge(report.model or "?", report.tokens_in, report.tokens_out)
            pv.sync_tenant(db, tenant)
            exemplars = _exemplars(persona["notes"])
            language = prompts["languages"][name]
            print(f"{name}: extracted {report.counts.created} signals; exemplars {len(exemplars)}")
            for situation in prompts["prompts"][name]:
                card = _trait_card(db, tenant, situation)
                n_text, t_in, t_out = _ask(drafter, NEUTRAL.format(situation=situation, language=language))
                charge(DRAFTER[1], t_in, t_out)
                v_prompt = VOICE.format(
                    trait_card="\n".join(f"- {line}" for line in card) or "- (nothing learned yet)",
                    exemplars="\n\n".join(f"[{i + 1}] {e}" for i, e in enumerate(exemplars)),
                    situation=situation,
                    language=language,
                )
                v_text, t_in, t_out = _ask(drafter, v_prompt)
                charge(DRAFTER[1], t_in, t_out)
                sims = {o: stylo.similarity(stylo.profile(v_text), held[o]) for o in personas}
                n_sims = {o: stylo.similarity(stylo.profile(n_text), held[o]) for o in personas}
                v_first = rng.random() < 0.5
                a, b = (v_text, n_text) if v_first else (n_text, v_text)
                item = {
                    "writer": name,
                    "situation": situation,
                    "neutral": n_text,
                    "voice": v_text,
                    "trait_card": card,
                    "v_is": "A" if v_first else "B",
                    "s_v": sims[name],
                    "s_n": n_sims[name],
                    "v_attributed_to": max(sims, key=sims.get),
                    "n_attributed_to": max(n_sims, key=n_sims.get),
                    "voice_verdicts": {},
                    "quality_verdicts": {},
                }
                samples = "\n\n".join(f"- {t}" for t in persona["held_out"])
                for jname, client in judges.items():
                    raw, t_in, t_out = _ask(client, JUDGE_VOICE.format(samples=samples, a=a, b=b))
                    charge(jname.split(":", 1)[1], t_in, t_out)
                    item["voice_verdicts"][jname] = _verdict(raw, ("A", "B", "UNSURE"))
                    raw, t_in, t_out = _ask(client, JUDGE_QUALITY.format(situation=situation, a=a, b=b))
                    charge(jname.split(":", 1)[1], t_in, t_out)
                    item["quality_verdicts"][jname] = _verdict(raw, ("A", "B", "TIE"))
                items.append(item)
                print(f"  {situation[:50]}... s(V)={item['s_v']:.3f} s(N)={item['s_n']:.3f} voice={item['voice_verdicts']} quality={item['quality_verdicts']} V={item['v_is']}")
    finally:
        db.close()

    result = score(items)
    cost = 0.0
    for model, (t_in, t_out) in spend.items():
        price = pricing_for(model)
        if price:
            cost += t_in / 1e6 * price.input_per_m + t_out / 1e6 * price.output_per_m
    result["spend"] = {"tokens": spend, "cost_usd": round(cost, 4)}
    result["config"] = {"drafter": ":".join(DRAFTER), "judges": [":".join(j) for j in JUDGES], "seed": SEED}
    print(json.dumps({k: v for k, v in result.items() if k != "items"}, indent=2))
    if out:
        out.write_text(json.dumps({**result, "items": items}, indent=2, ensure_ascii=False), encoding="utf-8")
        print("wrote", out)
    return result


def score(items: list[dict]) -> dict:
    """The pre-registered pass rule, applied as written."""
    def v_wins(verdict: str, v_is: str) -> bool | None:
        if verdict in ("UNSURE", "UNPARSED"):
            return None
        return verdict == v_is

    voice_all = [(it["writer"], j, v_wins(v, it["v_is"])) for it in items for j, v in it["voice_verdicts"].items()]
    decided = [w for _, _, w in voice_all if w is not None]
    pooled = sum(decided) / len(decided) if decided else 0.0
    abstain = sum(1 for _, _, w in voice_all if w is None) / len(voice_all) if voice_all else 1.0
    per_judge = {}
    for j in {j for _, j, _ in voice_all}:
        d = [w for _, jj, w in voice_all if jj == j and w is not None]
        per_judge[j] = {"v_share": round(sum(d) / len(d), 3) if d else None, "decided": len(d)}
    per_writer = {}
    for wname in {w for w, _, _ in voice_all}:
        d = [w for ww, _, w in voice_all if ww == wname and w is not None]
        per_writer[wname] = {"v_share": round(sum(d) / len(d), 3) if d else None, "decided": len(d)}

    quality = []
    for it in items:
        for v in it["quality_verdicts"].values():
            quality.append("tie" if v == "TIE" else ("unparsed" if v == "UNPARSED" else ("v" if v == it["v_is"] else "n")))
    q_ok_share = sum(1 for q in quality if q in ("v", "tie")) / len(quality) if quality else 0.0

    tier1_wins = sum(1 for it in items if it["s_v"] > it["s_n"])
    attributed = {
        "v_correct": sum(1 for it in items if it["v_attributed_to"] == it["writer"]),
        "n_correct": sum(1 for it in items if it["n_attributed_to"] == it["writer"]),
        "of": len(items),
    }

    rules = {
        "voice_1_pooled_v_share_ge_0.70": pooled >= 0.70,
        "voice_2_each_judge_ge_0.60": all(pj["v_share"] is not None and pj["v_share"] >= 0.60 for pj in per_judge.values()),
        "voice_3_abstain_le_0.50": abstain <= 0.50,
        "voice_4_no_writer_below_half": all(pw["v_share"] is not None and pw["v_share"] >= 0.5 for pw in per_writer.values()),
        "quality_guard_v_or_tie_ge_0.40": q_ok_share >= 0.40,
        "tier1_sv_gt_sn_ge_12_of_18": tier1_wins >= 12,
    }
    voice_pass = all(v for k, v in rules.items() if k.startswith("voice_"))
    return {
        "voice": {"pooled_v_share": round(pooled, 3), "abstain_share": round(abstain, 3), "per_judge": per_judge, "per_writer": per_writer, "verdicts": len(voice_all)},
        "quality": {"v_or_tie_share": round(q_ok_share, 3), "counts": {k: quality.count(k) for k in ("v", "n", "tie", "unparsed")}},
        "tier1": {"sv_gt_sn": tier1_wins, "of": len(items), "attribution": attributed},
        "rules": rules,
        "voice_pass": voice_pass,
        "quality_pass": rules["quality_guard_v_or_tie_ge_0.40"],
        "tier1_pass": rules["tier1_sv_gt_sn_ge_12_of_18"],
        "gate_for_s34_design": voice_pass and rules["quality_guard_v_or_tie_ge_0.40"],
    }


# ---------------------------------------------------------------------------
# Tier (iii): the user as judge


TOPIC = """In at most twelve words, name the topic of this note, as a situation someone could react to. Reply with the topic only.

Note:
{note}"""


def user_pairs(db_path: pathlib.Path, tenant_id: str, out: pathlib.Path, key: pathlib.Path, n: int = 20) -> None:
    """Blinded pairs for tier (iii), from a COPY of a database (it is
    modified). Holds out ``n`` of the user's live notes (soft-deleted in the
    copy, so extraction withdraws them), re-learns from the rest, and writes
    a V draft for each held-out note's topic. ``out`` gets the pairs
    (``pair``, ``A``, ``B``) to show the user; ``key`` says which is theirs.
    Refuses below the pre-registered floor of 40 live notes."""
    _scratch_env()
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    from app.database import SessionLocal
    from app.services import echo_personal_vectors as pv
    from app.services import echo_signal_extraction as ex
    from app.services import note_service

    rng = random.Random(SEED)
    db = SessionLocal()
    try:
        notes = list(note_service.iter_notes(db, tenant_id, include_deleted=False))
        if len(notes) < 40:
            raise SystemExit(f"tier (iii) needs at least 40 live notes; this tenant has {len(notes)}")
        held = rng.sample(notes, n)
        held_text = {x.id: x.body_md for x in held}
        for x in held:
            note_service.delete_note(db, tenant_id, x.id)
        ex.run(db, tenant_id)
        pv.sync_tenant(db, tenant_id)
        remaining = [x.body_md for x in note_service.iter_notes(db, tenant_id, include_deleted=False)]
        exemplars = _exemplars(remaining)
        drafter = _client(DRAFTER, 1200)
        pairs, keys = [], []
        for i, (note_id, own) in enumerate(held_text.items(), start=1):
            topic, _, _ = _ask(drafter, TOPIC.format(note=own))
            language = ex.language_of(own)
            card = _trait_card(db, tenant_id, topic)
            draft, _, _ = _ask(drafter, VOICE.format(
                trait_card="\n".join(f"- {line}" for line in card) or "- (nothing learned yet)",
                exemplars="\n\n".join(f"[{k + 1}] {e}" for k, e in enumerate(exemplars)),
                situation=topic,
                language={"en": "English", "hi-Deva": "Hindi", "hi-Latn": "Hindi in Roman letters", "mixed": "Hinglish"}[language],
            ))
            own_first = rng.random() < 0.5
            pid = f"p{i:02d}"
            pairs.append({"pair": pid, "A": own if own_first else draft, "B": draft if own_first else own})
            keys.append({"pair": pid, "own_is": "A" if own_first else "B", "note_id": note_id, "topic": topic})
    finally:
        db.close()
    out.write_text(json.dumps(pairs, indent=2, ensure_ascii=False), encoding="utf-8")
    key.write_text(json.dumps(keys, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(pairs)} pairs to {out} and the key to {key}. Show the user only the pairs file.")


def user_score(key: pathlib.Path, answers: pathlib.Path) -> dict:
    """``key``: [{pair, own_is}] ; ``answers``: {pair: "A"|"B"}. Pass when the
    user picks their own text in at most 80% of pairs (and >= 20 pairs)."""
    k = json.loads(key.read_text(encoding="utf-8"))
    a = json.loads(answers.read_text(encoding="utf-8"))
    picked_own = sum(1 for row in k if a.get(row["pair"]) == row["own_is"])
    share = picked_own / len(k) if k else 1.0
    result = {"pairs": len(k), "picked_own_share": round(share, 3), "pass": len(k) >= 20 and share <= 0.80}
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    _load_env(sys.argv)
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", type=pathlib.Path)
    r.add_argument("--env-file")
    p = sub.add_parser("user-pairs")
    p.add_argument("--db", type=pathlib.Path, required=True)
    p.add_argument("--tenant", required=True)
    p.add_argument("--out", type=pathlib.Path, required=True)
    p.add_argument("--key", type=pathlib.Path, required=True)
    p.add_argument("--env-file")
    s = sub.add_parser("user-score")
    s.add_argument("--key", type=pathlib.Path, required=True)
    s.add_argument("--answers", type=pathlib.Path, required=True)
    args = ap.parse_args()
    if args.mode == "run":
        run(args.out)
    elif args.mode == "user-pairs":
        user_pairs(args.db, args.tenant, args.out, args.key)
    else:
        user_score(args.key, args.answers)


if __name__ == "__main__":
    main()
