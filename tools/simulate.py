#!/usr/bin/env python3
"""Simulate N participants against a running server (default http://127.0.0.1:5055)."""
import json, sys, threading, time, urllib.request, http.cookiejar, random

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5055"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 20
KEY = {q["id"]: q for q in json.load(open("questions.json"))}

class C:
    def __init__(s):
        s.o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(s, path, body=None):
        req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with s.o.open(req) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            try: return {"status": e.code, **json.load(e)}
            except Exception: return {"status": e.code}

results, lock = {}, threading.Lock()
def player(i):
    c = C(); acc = (i % 5) / 4          # accuracy varies 0..1
    f = {"name": f"Player {i}", "phone": f"98000000{i:02d}", "email": f"p{i}@x.com", "code": "renaissance"}
    while True:
        r = c.call("/api/login", f)
        if not r.get("wait"): break
        time.sleep(0.5)
    if r.get("error"): results[i] = r; return
    while True:
        s = c.call("/api/state")
        if s["stage"] == "finished": break
        if s["stage"] == "ready": c.call("/api/round/start", {}); continue
        for q in s["questions"]:
            # recover the original letter by text -> option index of the key text
            k = KEY[q["id"]]; correct_text = next(o["text"] for o in k["options"] if o["letter"] == k["correct"])
            ci = q["options"].index(correct_text)
            pick = ci if random.random() < acc else (ci + 1) % len(q["options"])
            c.call("/api/answer", {"qid": q["id"], "choice": pick})
            time.sleep(0.01)
        c.call("/api/round/submit", {})
    results[i] = c.call("/api/state")

ts = [threading.Thread(target=player, args=(i,)) for i in range(N)]
t0 = time.time(); [t.start() for t in ts]; [t.join() for t in ts]
print(f"{len(results)} players finished in {time.time()-t0:.1f}s; errors:", [r for r in results.values() if r.get("error")])
