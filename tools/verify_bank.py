#!/usr/bin/env python3
"""Run every code snippet and compare stdout with the keyed answer (sanity check)."""
import json, subprocess, sys, re
qs = json.load(open(sys.argv[1]))
norm = lambda s: re.sub(r"\s+", " ", s).strip()
bad = skipped = ok = 0
for q in qs:
    r = subprocess.run([sys.executable, "-I", "-c", q["code"]], capture_output=True, text=True, timeout=5)
    out = norm(r.stdout if r.returncode == 0 else "Error")
    key = next(o["text"] for o in q["options"] if o["letter"] == q["correct"])
    matches = [o["letter"] for o in q["options"] if norm(o["text"]) == out]
    if matches:
        if q["correct"] in matches: ok += 1
        else:
            bad += 1; print("MISMATCH", q["id"], "output=", repr(out), "key=", q["correct"], key)
    else:
        skipped += 1
        print("manual   ", q["id"], "|", q["question"][:50], "| out=", repr(out)[:50], "| key=", key[:60])
print(f"auto-verified OK={ok} MISMATCH={bad} needs-manual-check={skipped}")
