"""Time signal extraction's non-LLM work on a synthetic 130k-turn chat import (T-3.3.2.10).

Scratch SQLite in a temp dir, never the dev database. From backend/:

    ./venv/Scripts/python scripts/measure_import_scale.py .
"""
import os
import random
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/bench.db".replace("\\", "/")
os.environ["ECHO_SIGNAL_EXTRACTION"] = "off"
os.environ["ECHO_PERSONAL_INDEX_ENABLED"] = "false"
sys.path.insert(0, sys.argv[1])

import logging  # noqa: E402

logging.disable(logging.INFO)
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.share import Share  # noqa: E402
from app.models.voice_signal_input import VoiceSignalInput  # noqa: E402
from app.services import auth_service  # noqa: E402
from app.services import echo_signal_extraction as ex  # noqa: E402

Base.metadata.create_all(engine)
db = SessionLocal()
user = auth_service.create_user(db, email="bench@example.com", password="pw" * 8)
user.tier = "studio"
db.commit()
rng = random.Random(1)
vocab = "yaar ok haha the rates incentive story bhai kal milte data policy why what sure done nahi theek".split()
N = 130_000
imp = str(uuid.uuid4())
rows = []
t0 = datetime(2016, 1, 1)
for k in range(N):
    rows.append({
        "id": str(uuid.uuid4()), "tenant_id": user.id, "user_id": user.id, "surface": "file_import",
        "content_type": "chat_turn", "raw_payload_json": "{}",
        "extracted_text": " ".join(rng.choice(vocab) for _ in range(rng.randint(1, 18))),
        "author_is_tenant": k % 2 == 0, "processing_state": "pending", "import_id": imp,
        "occurred_at": t0 + timedelta(minutes=40 * k),
    })
    if len(rows) == 5000:
        db.bulk_insert_mappings(Share, rows)
        db.commit()
        rows = []
db.commit()

t = time.perf_counter()
n = ex.quick_new_count(db, user.id)
print(f"quick_new_count = {n} in {1000 * (time.perf_counter() - t):.1f} ms")
t = time.perf_counter()
inputs = ex.gather_inputs(db, user.id)
print(f"gather_inputs: {len(inputs)} input(s), {sum(len(i.passages) for i in inputs)} passages, {time.perf_counter() - t:.1f} s")
t = time.perf_counter()
report = ex.run(db, user.id, use_llm=False)
print(f"run (no LLM): {time.perf_counter() - t:.1f} s; ledger rows "
      f"{db.query(VoiceSignalInput).count()}, features {sum(len(r.features_json) for r in db.query(VoiceSignalInput)):,} bytes")
t = time.perf_counter()
print(f"second run reads {ex.run(db, user.id, use_llm=False).inputs_read} input(s) in {time.perf_counter() - t:.1f} s")
