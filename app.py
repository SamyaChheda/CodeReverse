#!/usr/bin/env python3
"""Code Reverse Engineering - event server (Flask + SQLite, no external services)."""
import csv
import io
import json
import math
import os
import random
import re
import secrets
import sqlite3
import time
from collections import Counter

from flask import Flask, Response, g, jsonify, make_response, request, send_from_directory

import config

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="/static")

QUESTIONS = {q["id"]: q for q in json.load(open(os.path.join(BASE, "questions.json"), encoding="utf-8"))}
BY_ROUND = {r: [q for q in QUESTIONS.values() if q["round"] == r] for r in config.ROUNDS}
NO_SHUFFLE = re.compile(r"\b(above|both|none of|all of|neither)\b", re.I)
ADMIN_TOKENS = set()

SCHEMA = """
CREATE TABLE IF NOT EXISTS participants(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT UNIQUE, email TEXT,
  token TEXT, created REAL, last_seen REAL, status TEXT DEFAULT 'active',
  qids TEXT, orders TEXT, tabs INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS rounds(
  pid INTEGER, round INTEGER, started REAL, deadline REAL, submitted REAL,
  auto INTEGER DEFAULT 0, bonus INTEGER DEFAULT 0, PRIMARY KEY(pid, round));
CREATE TABLE IF NOT EXISTS answers(
  pid INTEGER, qid TEXT, choice TEXT, explain TEXT DEFAULT '', explain_marks INTEGER,
  updated REAL, PRIMARY KEY(pid, qid));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""


# ----------------------------------------------------------------- database
def db():
    if "db" not in g:
        c = sqlite3.connect(config.DB_PATH, timeout=15, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=15000")
        g.db = c
    return g.db


@app.teardown_appcontext
def close_db(_):
    c = g.pop("db", None)
    if c:
        c.close()


def init_db():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    c = sqlite3.connect(config.DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    c.close()


def get_setting(c, key, default=None):
    r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_setting(c, key, value):
    c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (key, json.dumps(value)))


def max_active(c):
    return get_setting(c, "max_active", config.MAX_ACTIVE)


def access_code(c):
    return get_setting(c, "access_code", config.ACCESS_CODE)


@app.after_request
def no_cache(resp):
    if request.path.startswith(("/api", "/admin/api")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# --------------------------------------------------------------- core logic
def marks_split(rnd):
    """(mcq marks, explanation marks) per question in a round."""
    per_q = config.ROUNDS[rnd]["per_q"]
    ex = config.R3_EXPLAIN_MARKS if rnd == 3 else 0
    return per_q - ex, ex


def pick_questions(rng, rnd):
    """Random, balanced selection: spread across topics and question types."""
    n = config.ROUNDS[rnd]["questions"]
    pool = BY_ROUND[rnd][:]
    rng.shuffle(pool)
    chosen, topics, types = [], set(), Counter()
    cap = max(2, math.ceil(n / 2))
    for q in pool:
        topic = q["topic"].split("/")[0].strip().lower()
        if topic in topics or types[q["type"]] >= cap:
            continue
        chosen.append(q)
        topics.add(topic)
        types[q["type"]] += 1
        if len(chosen) == n:
            break
    for q in pool:                      # top up if the constraints were too tight
        if len(chosen) == n:
            break
        if q not in chosen:
            chosen.append(q)
    rng.shuffle(chosen)
    return chosen


def build_paper(rng):
    qids, orders = {}, {}
    for rnd in config.ROUNDS:
        qs = pick_questions(rng, rnd)
        qids[rnd] = [q["id"] for q in qs]
        for q in qs:
            letters = [o["letter"] for o in q["options"]]
            if not any(NO_SHUFFLE.search(o["text"]) for o in q["options"]):
                rng.shuffle(letters)
            orders[q["id"]] = letters
    return qids, orders


def sync(c, pid):
    """Close the running round if its deadline has passed; mark finished participants."""
    now = time.time()
    r = c.execute("SELECT * FROM rounds WHERE pid=? AND submitted IS NULL", (pid,)).fetchone()
    if r and now >= r["deadline"]:
        c.execute("UPDATE rounds SET submitted=?, auto=1 WHERE pid=? AND round=?", (r["deadline"], pid, r["round"]))
    n = c.execute("SELECT COUNT(*) FROM rounds WHERE pid=? AND submitted IS NOT NULL", (pid,)).fetchone()[0]
    if n >= len(config.ROUNDS):
        c.execute("UPDATE participants SET status='finished' WHERE id=? AND status='active'", (pid,))


def round_rows(c, pid):
    return {r["round"]: r for r in c.execute("SELECT * FROM rounds WHERE pid=?", (pid,))}


def active_count(c):
    cutoff = time.time() - config.IDLE_SECONDS
    return c.execute("SELECT COUNT(*) FROM participants WHERE status='active' AND last_seen>?", (cutoff,)).fetchone()[0]


def current_user():
    tok = request.cookies.get("tok")
    if not tok:
        return None
    return db().execute("SELECT * FROM participants WHERE token=?", (tok,)).fetchone()


def scoreboard_row(c, p):
    """Score, per-round marks and times for one participant."""
    qids = json.loads(p["qids"])
    rows = round_rows(c, p["id"])
    ans = {a["qid"]: a for a in c.execute("SELECT * FROM answers WHERE pid=?", (p["id"],))}
    per_round, times, pending = {}, {}, 0
    for rnd in config.ROUNDS:
        mcq_m, ex_m = marks_split(rnd)
        total = 0
        if str(rnd) in qids:
            for qid in qids[str(rnd)]:
                a = ans.get(qid)
                if not a:
                    continue
                if a["choice"] == QUESTIONS[qid]["correct"]:
                    total += mcq_m
                if ex_m and a["explain"] and a["explain"].strip():
                    if a["explain_marks"] is None:
                        pending += 1
                    else:
                        total += min(a["explain_marks"], ex_m)
        per_round[rnd] = total
        r = rows.get(rnd)
        if r and r["submitted"] is not None:
            times[rnd] = max(0, round(r["submitted"] - r["started"] - r["bonus"]))
    return {"per_round": per_round, "score": sum(per_round.values()), "times": times,
            "time": sum(times.values()), "pending": pending}


# -------------------------------------------------------------- participant
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/admin")
def admin_page():
    return send_from_directory(app.static_folder, "admin.html")


@app.get("/api/config")
def api_config():
    return jsonify(event=config.EVENT_NAME, org=config.ORG_NAME, subtitle=config.EVENT_SUBTITLE,
                   rounds=[{"round": r, **{k: v for k, v in d.items() if k != "per_q"},
                            "marks": d["questions"] * d["per_q"]} for r, d in config.ROUNDS.items()],
                   total_minutes=sum(d["minutes"] for d in config.ROUNDS.values()))


@app.post("/api/login")
def api_login():
    d = request.get_json(silent=True) or {}
    name = re.sub(r"\s+", " ", str(d.get("name", "")).strip())
    phone = re.sub(r"\D", "", str(d.get("phone", "")))[-10:]
    email = str(d.get("email", "")).strip().lower()
    code = str(d.get("code", "")).strip()
    if not (2 <= len(name) <= 60):
        return jsonify(error="Please enter your full name."), 400
    if len(phone) != 10:
        return jsonify(error="Enter a valid 10-digit phone number."), 400
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify(error="Enter a valid email address."), 400

    c = db()
    if code.lower() != str(access_code(c)).lower():
        return jsonify(error="Wrong event access code. Ask a volunteer."), 403

    c.execute("BEGIN IMMEDIATE")
    try:
        p = c.execute("SELECT * FROM participants WHERE phone=?", (phone,)).fetchone()
        now = time.time()
        slots = {"active": active_count(c), "max": max_active(c)}
        if p:
            if p["email"] != email:
                c.execute("ROLLBACK")
                return jsonify(error="This phone number is already registered with a different email."), 403
            recently_seen = p["last_seen"] and p["last_seen"] > now - config.IDLE_SECONDS
            if p["status"] == "active" and not recently_seen and slots["active"] >= slots["max"]:
                c.execute("ROLLBACK")
                return jsonify(wait=True, **slots)
            pid = p["id"]
        else:
            if not get_setting(c, "registration_open", True):
                c.execute("ROLLBACK")
                return jsonify(error="Registration is closed."), 403
            if slots["active"] >= slots["max"]:
                c.execute("ROLLBACK")
                return jsonify(wait=True, **slots)
            qids, orders = build_paper(random.Random(secrets.randbits(64)))
            cur = c.execute(
                "INSERT INTO participants(name,phone,email,created,last_seen,qids,orders) VALUES(?,?,?,?,?,?,?)",
                (name, phone, email, now, now, json.dumps(qids), json.dumps(orders)))
            pid = cur.lastrowid
        token = secrets.token_urlsafe(24)       # a new login replaces any older browser session
        c.execute("UPDATE participants SET token=?, last_seen=? WHERE id=?", (token, now, pid))
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    resp = make_response(jsonify(ok=True))
    resp.set_cookie("tok", token, max_age=12 * 3600, httponly=True, samesite="Lax")
    return resp


def paper_for(p, rnd):
    qids = json.loads(p["qids"])[str(rnd)]
    orders = json.loads(p["orders"])
    saved = {a["qid"]: a for a in db().execute("SELECT * FROM answers WHERE pid=?", (p["id"],))}
    out = []
    for i, qid in enumerate(qids, 1):
        q = QUESTIONS[qid]
        letters = orders[qid]
        text = {o["letter"]: o["text"] for o in q["options"]}
        a = saved.get(qid)
        out.append({"id": qid, "n": i, "code": q["code"], "question": q["question"],
                    "options": [text[l] for l in letters],
                    "saved": letters.index(a["choice"]) if a and a["choice"] in letters else None,
                    "explain": a["explain"] if a else ""})
    return out


@app.get("/api/state")
def api_state():
    p = current_user()
    if not p:
        return jsonify(stage="login"), 401
    c = db()
    c.execute("UPDATE participants SET last_seen=? WHERE id=?", (time.time(), p["id"]))
    sync(c, p["id"])
    p = c.execute("SELECT * FROM participants WHERE id=?", (p["id"],)).fetchone()
    rows = round_rows(c, p["id"])
    sb = scoreboard_row(c, p)
    base = {"name": p["name"], "times": sb["times"], "total_time": sb["time"], "now": time.time()}
    if p["status"] in ("finished", "ended"):
        extra = {"score": sb["score"]} if config.SHOW_SCORE_TO_PARTICIPANT else {}
        return jsonify(stage="finished", ended=p["status"] == "ended", **base, **extra)
    done = sum(1 for r in rows.values() if r["submitted"] is not None)
    rnd = done + 1
    cfg = config.ROUNDS[rnd]
    info = {"round": rnd, "rounds": len(config.ROUNDS), "round_name": cfg["name"], "level": cfg["level"],
            "minutes": cfg["minutes"], "count": cfg["questions"], "marks": cfg["questions"] * cfg["per_q"]}
    r = rows.get(rnd)
    if not r:
        return jsonify(stage="ready", **info, **base)
    return jsonify(stage="round", **info, **base, remaining=max(0, r["deadline"] - time.time()),
                   explain=(rnd == 3 and config.R3_EXPLAIN_MARKS > 0), questions=paper_for(p, rnd))


@app.post("/api/round/start")
def api_round_start():
    p = current_user()
    if not p:
        return jsonify(error="login"), 401
    c = db()
    c.execute("BEGIN IMMEDIATE")
    sync(c, p["id"])
    rows = round_rows(c, p["id"])
    done = sum(1 for r in rows.values() if r["submitted"] is not None)
    rnd = done + 1
    st = c.execute("SELECT status FROM participants WHERE id=?", (p["id"],)).fetchone()["status"]
    if st == "active" and rnd in config.ROUNDS and rnd not in rows:
        now = time.time()
        c.execute("INSERT INTO rounds(pid,round,started,deadline) VALUES(?,?,?,?)",
                  (p["id"], rnd, now, now + config.ROUNDS[rnd]["minutes"] * 60))
    c.execute("COMMIT")
    return jsonify(ok=True)


@app.post("/api/answer")
def api_answer():
    p = current_user()
    if not p:
        return jsonify(error="login"), 401
    d = request.get_json(silent=True) or {}
    c = db()
    sync(c, p["id"])
    rows = round_rows(c, p["id"])
    running = [r for r in rows.values() if r["submitted"] is None]
    if not running or time.time() >= running[0]["deadline"]:
        return jsonify(error="Round is over", over=True), 409
    rnd = running[0]["round"]
    qid = str(d.get("qid", ""))
    if qid not in json.loads(p["qids"])[str(rnd)]:
        return jsonify(error="Unknown question"), 400
    letters = json.loads(p["orders"])[qid]
    old = c.execute("SELECT * FROM answers WHERE pid=? AND qid=?", (p["id"], qid)).fetchone()
    choice = old["choice"] if old else None
    explain = old["explain"] if old else ""
    if "choice" in d:
        idx = d["choice"]
        choice = letters[idx] if isinstance(idx, int) and 0 <= idx < len(letters) else None
    if "explain" in d and rnd == 3 and config.R3_EXPLAIN_MARKS > 0:
        explain = str(d["explain"])[:600]
    c.execute("INSERT INTO answers(pid,qid,choice,explain,updated) VALUES(?,?,?,?,?) "
              "ON CONFLICT(pid,qid) DO UPDATE SET choice=excluded.choice, explain=excluded.explain, updated=excluded.updated",
              (p["id"], qid, choice, explain, time.time()))
    c.execute("UPDATE participants SET last_seen=? WHERE id=?", (time.time(), p["id"]))
    return jsonify(ok=True)


@app.post("/api/round/submit")
def api_round_submit():
    p = current_user()
    if not p:
        return jsonify(error="login"), 401
    c = db()
    c.execute("BEGIN IMMEDIATE")
    sync(c, p["id"])
    r = c.execute("SELECT * FROM rounds WHERE pid=? AND submitted IS NULL", (p["id"],)).fetchone()
    if r:
        c.execute("UPDATE rounds SET submitted=? WHERE pid=? AND round=?",
                  (min(time.time(), r["deadline"]), p["id"], r["round"]))
    sync(c, p["id"])
    c.execute("COMMIT")
    return jsonify(ok=True)


@app.post("/api/event")
def api_event():
    p = current_user()
    if p and (request.get_json(silent=True) or {}).get("kind") == "blur":
        db().execute("UPDATE participants SET tabs=tabs+1 WHERE id=?", (p["id"],))
    return jsonify(ok=True)


# -------------------------------------------------------------------- admin
def admin_required():
    return request.cookies.get("adm") in ADMIN_TOKENS


@app.post("/admin/api/login")
def admin_login():
    pw = str((request.get_json(silent=True) or {}).get("password", ""))
    if not secrets.compare_digest(pw.encode(), config.ADMIN_PASSWORD.encode()):
        time.sleep(1)
        return jsonify(error="Wrong password"), 403
    tok = secrets.token_urlsafe(24)
    ADMIN_TOKENS.add(tok)
    resp = make_response(jsonify(ok=True))
    resp.set_cookie("adm", tok, max_age=12 * 3600, httponly=True, samesite="Lax")
    return resp


def leaderboard(c):
    now = time.time()
    out = []
    for p in c.execute("SELECT * FROM participants").fetchall():
        sync(c, p["id"])
    for p in c.execute("SELECT * FROM participants").fetchall():
        sb = scoreboard_row(c, p)
        rows = round_rows(c, p["id"])
        running = next((r for r in rows.values() if r["submitted"] is None), None)
        done = sum(1 for r in rows.values() if r["submitted"] is not None)
        if p["status"] == "finished":
            stage = "Finished"
        elif p["status"] == "ended":
            stage = "Ended by organiser"
        elif running:
            stage = f"Round {running['round']} running"
        else:
            stage = f"Round {done + 1} (not started)"
        out.append({"id": p["id"], "name": p["name"], "phone": p["phone"], "email": p["email"],
                    "status": p["status"], "stage": stage, "score": sb["score"], "per_round": sb["per_round"],
                    "times": sb["times"], "time": sb["time"], "pending": sb["pending"], "tabs": p["tabs"],
                    "remaining": max(0, round(running["deadline"] - now)) if running else None,
                    "online": bool(p["last_seen"] and p["last_seen"] > now - config.IDLE_SECONDS),
                    "seen_ago": round(now - p["last_seen"]) if p["last_seen"] else None})
    fin = [x for x in out if x["status"] in ("finished", "ended")]
    rest = [x for x in out if x not in fin]
    fin.sort(key=lambda x: (-x["score"], x["time"], x["name"].lower()))
    rest.sort(key=lambda x: (-x["score"], x["name"].lower()))
    for i, x in enumerate(fin, 1):
        x["rank"] = i
    keys = Counter((x["score"], x["time"]) for x in fin)
    for x in fin:
        x["tie"] = keys[(x["score"], x["time"])] > 1
    return fin + rest


@app.get("/admin/api/overview")
def admin_overview():
    if not admin_required():
        return jsonify(error="auth"), 401
    c = db()
    board = leaderboard(c)
    return jsonify(board=board, now=time.time(),
                   settings={"max_active": max_active(c), "access_code": access_code(c),
                             "registration_open": get_setting(c, "registration_open", True)},
                   counts={"slots_used": active_count(c), "total": len(board),
                           "finished": sum(1 for x in board if x["status"] == "finished"),
                           "running": sum(1 for x in board if x["remaining"] is not None),
                           "pending_grading": sum(x["pending"] for x in board)},
                   explain_enabled=config.R3_EXPLAIN_MARKS > 0, explain_max=config.R3_EXPLAIN_MARKS)


@app.post("/admin/api/settings")
def admin_settings():
    if not admin_required():
        return jsonify(error="auth"), 401
    d = request.get_json(silent=True) or {}
    c = db()
    if "max_active" in d:
        set_setting(c, "max_active", max(1, min(100, int(d["max_active"]))))
    if "registration_open" in d:
        set_setting(c, "registration_open", bool(d["registration_open"]))
    if d.get("access_code"):
        set_setting(c, "access_code", str(d["access_code"]).strip())
    return jsonify(ok=True)


@app.post("/admin/api/participant/<int:pid>")
def admin_participant(pid):
    if not admin_required():
        return jsonify(error="auth"), 401
    d = request.get_json(silent=True) or {}
    act = d.get("action")
    c = db()
    c.execute("BEGIN IMMEDIATE")
    p = c.execute("SELECT * FROM participants WHERE id=?", (pid,)).fetchone()
    if not p:
        c.execute("ROLLBACK")
        return jsonify(error="not found"), 404
    if act == "end":
        c.execute("UPDATE rounds SET submitted=? WHERE pid=? AND submitted IS NULL", (time.time(), pid))
        c.execute("UPDATE participants SET status='ended' WHERE id=?", (pid,))
    elif act == "reopen":
        c.execute("UPDATE participants SET status='active', last_seen=? WHERE id=?", (time.time(), pid))
        sync(c, pid)
    elif act == "extend":
        secs = max(0, min(1800, int(d.get("seconds", 120))))
        c.execute("UPDATE rounds SET deadline=deadline+?, bonus=bonus+? WHERE pid=? AND submitted IS NULL",
                  (secs, secs, pid))
    elif act == "reset":      # start this participant over with the same paper
        c.execute("DELETE FROM rounds WHERE pid=?", (pid,))
        c.execute("DELETE FROM answers WHERE pid=?", (pid,))
        c.execute("UPDATE participants SET status='active', last_seen=?, tabs=0 WHERE id=?", (time.time(), pid))
    elif act == "delete":
        for t in ("rounds", "answers"):
            c.execute(f"DELETE FROM {t} WHERE pid=?", (pid,))
        c.execute("DELETE FROM participants WHERE id=?", (pid,))
    else:
        c.execute("ROLLBACK")
        return jsonify(error="bad action"), 400
    c.execute("COMMIT")
    return jsonify(ok=True)


@app.get("/admin/api/participant/<int:pid>")
def admin_detail(pid):
    if not admin_required():
        return jsonify(error="auth"), 401
    c = db()
    p = c.execute("SELECT * FROM participants WHERE id=?", (pid,)).fetchone()
    if not p:
        return jsonify(error="not found"), 404
    ans = {a["qid"]: a for a in c.execute("SELECT * FROM answers WHERE pid=?", (pid,))}
    orders = json.loads(p["orders"])
    out = []
    for rnd, qids in json.loads(p["qids"]).items():
        for qid in qids:
            q, a = QUESTIONS[qid], ans.get(qid)
            text = {o["letter"]: o["text"] for o in q["options"]}
            out.append({"round": int(rnd), "id": qid, "code": q["code"], "question": q["question"],
                        "given": text.get(a["choice"]) if a and a["choice"] else None,
                        "correct": text[q["correct"]], "ok": bool(a and a["choice"] == q["correct"]),
                        "explain": a["explain"] if a else "", "explain_marks": a["explain_marks"] if a else None,
                        "model": q["explanation"]})
    return jsonify(name=p["name"], questions=out)


@app.get("/admin/api/grading")
def admin_grading():
    if not admin_required():
        return jsonify(error="auth"), 401
    c = db()
    rows = c.execute("SELECT a.pid, a.qid, a.choice, a.explain, a.explain_marks, p.name FROM answers a "
                     "JOIN participants p ON p.id=a.pid WHERE trim(a.explain)<>'' ORDER BY a.explain_marks IS NOT NULL, a.updated").fetchall()
    return jsonify(items=[{"pid": r["pid"], "qid": r["qid"], "name": r["name"], "explain": r["explain"],
                           "marks": r["explain_marks"], "ok": r["choice"] == QUESTIONS[r["qid"]]["correct"],
                           "code": QUESTIONS[r["qid"]]["code"], "question": QUESTIONS[r["qid"]]["question"],
                           "model": QUESTIONS[r["qid"]]["explanation"]} for r in rows], max=config.R3_EXPLAIN_MARKS)


@app.post("/admin/api/grade")
def admin_grade():
    if not admin_required():
        return jsonify(error="auth"), 401
    d = request.get_json(silent=True) or {}
    m = max(0, min(config.R3_EXPLAIN_MARKS, int(d["marks"])))
    db().execute("UPDATE answers SET explain_marks=? WHERE pid=? AND qid=?", (m, int(d["pid"]), d["qid"]))
    return jsonify(ok=True)


@app.get("/admin/api/export.csv")
def admin_export():
    if not admin_required():
        return Response("auth", 401)
    board = leaderboard(db())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Rank", "Name", "Phone", "Email", "Status", "R1 marks", "R2 marks", "R3 marks", "Total marks",
                "R1 sec", "R2 sec", "R3 sec", "Total sec", "Tab switches", "Tie", "Explanations ungraded"])
    for x in board:
        w.writerow([x.get("rank", ""), x["name"], x["phone"], x["email"], x["stage"],
                    *[x["per_round"][r] for r in (1, 2, 3)], x["score"],
                    *[x["times"].get(r, "") for r in (1, 2, 3)], x["time"], x["tabs"],
                    "TIE" if x.get("tie") else "", x["pending"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=cre_results.csv"})


init_db()

if __name__ == "__main__":
    print(f"\n  Code Reverse Engineering server\n  Participants: http://<this-pc-ip>:{config.PORT}/"
          f"\n  Organiser   : http://localhost:{config.PORT}/admin\n")
    app.run(host="0.0.0.0", port=config.PORT, threaded=True)
