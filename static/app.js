"use strict";
const $app = document.getElementById("app");
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const fmt = s => { s = Math.max(0, Math.round(s)); return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0"); };
const fmtWords = s => { s = Math.round(s); return s >= 60 ? Math.floor(s / 60) + " min " + (s % 60) + " s" : s + " s"; };
let CFG = null, S = null, tick = null, syncT = null, deadline = 0, inflight = new Set(), saveState = "ok", leaving = false;

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  let j = {}; try { j = await r.json(); } catch (e) {}
  return { status: r.status, ...j };
}

/* ---------- syntax colouring (Python) ---------- */
const TOK = /(#.*$)|("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')|\b(def|return|if|elif|else|for|while|in|not|and|or|break|continue|import|from|as|True|False|None|pass|is|lambda)\b|\b(range|len|print|append|pop|int|str|sum|max|min|list|set|dict|sorted|reversed|abs|insert|remove|index)\b|(\b\d+(?:\.\d+)?\b)/g;
function highlight(code) {
  return code.split("\n").map((line, i) => {
    let out = "", last = 0, m; TOK.lastIndex = 0;
    while ((m = TOK.exec(line))) {
      out += esc(line.slice(last, m.index));
      const cls = m[1] ? "c" : m[2] ? "s" : m[3] ? "k" : m[4] ? "b" : "n";
      out += `<span class="${cls}">${esc(m[0])}</span>`; last = m.index + m[0].length;
    }
    out += esc(line.slice(last));
    return `<span class="l" data-n="${i + 1}">${out || " "}</span>`;
  }).join("");
}

/* ---------- screens ---------- */
function rulesHTML() {
  const r = CFG.rounds;
  return `<div class="card rules"><h2>${esc(CFG.event)} &ndash; Event Rules</h2>
  <h3>Participation</h3><ul><li>Solo event. Log in once with your own details &ndash; use the access code given by the volunteers.</li>
  <li>If your PC hangs, log in again with the <b>same phone and email</b> to continue. The timer keeps running.</li></ul>
  <h3>Rounds</h3><ul>${r.map(x => `<li><b>Round ${x.round} &ndash; ${esc(x.name)}</b> (${esc(x.level)}): ${x.questions} questions, <b>${x.minutes} min</b>, ${x.marks} marks</li>`).join("")}
  <li>Total: ${r.reduce((a, x) => a + x.questions, 0)} questions, ${CFG.total_minutes} minutes, ${r.reduce((a, x) => a + x.marks, 0)} marks.</li></ul>
  <h3>Answering</h3><ul><li>Read the code, work out what it does, and pick the best option. Answers save automatically.</li>
  <li>Everyone completes all three rounds &ndash; there is no elimination. Unanswered questions score zero.</li>
  <li>A round ends when you submit it or when its timer hits zero. You cannot go back to a finished round.</li>
  <li>Do not run the code, switch tabs or use any other program. Tab switching is recorded.</li></ul>
  <h3>Winner</h3><ul><li>Highest total marks wins. A tie is broken by the lower total time, then by a short tie-break challenge.</li>
  <li>There is no speed bonus. Organiser decisions are final.</li></ul></div>`;
}

function showLogin(msg, prefill) {
  clearTimers();
  const v = prefill || {};
  $app.innerHTML = `<div class="grid2">
    <form class="card" id="lf" autocomplete="off"><h2>Sign in to start the competition</h2>
      <label>Full Name</label><input type="text" name="name" required maxlength="60" value="${esc(v.name || "")}">
      <label>Phone Number</label><input type="tel" name="phone" required inputmode="numeric" value="${esc(v.phone || "")}">
      <label>Email</label><input type="email" name="email" required value="${esc(v.email || "")}">
      <label>Event access code</label><input type="password" name="code" required value="${esc(v.code || "")}">
      <button class="full" id="lb">Login and Start</button><div class="err" id="le">${esc(msg || "")}</div></form>
    ${rulesHTML()}</div>`;
  document.getElementById("lf").onsubmit = async e => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    const btn = document.getElementById("lb"); btn.disabled = true;
    const r = await api("/api/login", f);
    if (r.wait) return showQueue(f, r);
    btn.disabled = false;
    if (r.error) { document.getElementById("le").textContent = r.error; return; }
    load();
  };
}

function showQueue(f, r) {
  clearTimers();
  $app.innerHTML = `<div class="card center"><h2>The lab is full right now</h2>
    <p class="pill">${r.active} of ${r.max} seats in use</p>
    <p>Please wait &ndash; you will be let in automatically as soon as a seat frees up. Keep this page open.</p></div>`;
  syncT = setTimeout(async () => {
    const x = await api("/api/login", f);
    if (x.wait) return showQueue(f, x);
    if (x.error) return showLogin(x.error, f);
    load();
  }, 5000);
}

function showReady() {
  clearTimers();
  const s = S, prev = Object.entries(s.times).map(([r, t]) => `<div class="stat"><b>${fmtWords(t)}</b><span>Round ${r} time</span></div>`).join("");
  $app.innerHTML = `<div class="card center"><span class="pill">Hello, ${esc(s.name)}</span>
    <div class="big">Round ${s.round} of ${s.rounds} &ndash; ${esc(s.round_name)}</div>
    <div class="stats"><div class="stat"><b>${s.count}</b><span>Questions</span></div>
      <div class="stat"><b>${s.minutes} min</b><span>Time limit</span></div>
      <div class="stat"><b>${s.marks}</b><span>Marks</span></div><div class="stat"><b>${esc(s.level)}</b><span>Difficulty</span></div></div>
    ${prev ? `<div class="stats">${prev}</div>` : ""}
    <p style="color:var(--mute)">The timer starts the moment you press the button. Once you begin, you cannot pause.</p>
    <button class="full" id="go">Start Round ${s.round}</button></div>`;
  document.getElementById("go").onclick = async e => { e.target.disabled = true; await api("/api/round/start", {}); load(); };
}

function showFinished() {
  clearTimers();
  const s = S, rows = Object.entries(s.times).map(([r, t]) => `<div class="stat"><b>${fmtWords(t)}</b><span>Round ${r}</span></div>`).join("");
  $app.innerHTML = `<div class="card center"><span class="pill">${esc(s.name)}</span>
    <div class="big">${s.ended ? "Your event has ended" : "All rounds complete – well done!"}</div>
    <div class="stats">${rows}<div class="stat"><b>${fmtWords(s.total_time)}</b><span>Total time</span></div>
    ${s.score !== undefined ? `<div class="stat"><b>${s.score}</b><span>Marks</span></div>` : ""}</div>
    <p style="color:var(--mute)">Your answers are saved. Results and winners will be announced by the organisers at the end of the event.<br>Please stay quiet and do not discuss the questions until the event is over.</p></div>`;
}

function showRound() {
  clearTimers();
  const s = S;
  $app.innerHTML = `<div class="bar"><span class="title">Round ${s.round} &ndash; ${esc(s.round_name)}</span>
      <div class="chips">${s.questions.map(q => `<a class="chip ${q.saved !== null ? "done" : ""}" id="chip${q.n}" href="#q${q.n}">${q.n}</a>`).join("")}</div>
      <span class="sp"></span><span class="save" id="save">Saved</span><span class="clock" id="clock">--:--</span></div>
    ${s.questions.map(q => `<section class="card q" id="q${q.n}"><div class="qn">Question ${q.n} of ${s.count}</div>
      <pre class="code" oncopy="return false" oncut="return false">${highlight(q.code)}</pre>
      <div class="qt">${esc(q.question)}</div>
      <div class="opts">${q.options.map((o, i) => `<button class="opt ${q.saved === i ? "sel" : ""}" data-q="${q.id}" data-n="${q.n}" data-i="${i}">
        <span class="L">${"ABCDEF"[i]}</span><span class="t">${esc(o)}</span></button>`).join("")}</div>
      ${s.explain ? `<div class="explain"><label>Explain your reasoning in one or two lines (earns partial marks)</label>
        <textarea rows="2" maxlength="600" data-q="${q.id}">${esc(q.explain)}</textarea></div>` : ""}</section>`).join("")}
    <div class="actions"><span style="color:var(--mute)" id="left"></span><button id="sub">Submit Round ${s.round}${s.round < s.rounds ? " and continue" : " and finish"}</button></div>`;

  document.querySelectorAll(".opt").forEach(b => b.onclick = () => {
    const card = b.closest(".q"); card.querySelectorAll(".opt").forEach(x => x.classList.remove("sel")); b.classList.add("sel");
    document.getElementById("chip" + b.dataset.n).classList.add("done"); updateLeft();
    save({ qid: b.dataset.q, choice: +b.dataset.i });
  });
  document.querySelectorAll("textarea").forEach(t => { let h; t.oninput = () => { clearTimeout(h); h = setTimeout(() => save({ qid: t.dataset.q, explain: t.value }), 500); }; });
  document.getElementById("sub").onclick = confirmSubmit;
  updateLeft();
  deadline = performance.now() + s.remaining * 1000;
  runClock();
  tick = setInterval(runClock, 250);
  syncT = setInterval(resync, 20000);
}

function updateLeft() {
  const un = document.querySelectorAll(".q").length - document.querySelectorAll(".q .opt.sel").length;
  document.getElementById("left").textContent = un ? `${un} question${un > 1 ? "s" : ""} unanswered` : "All questions answered";
}

function setSave(st) {
  saveState = st; const el = document.getElementById("save"); if (!el) return;
  el.className = "save" + (st === "bad" ? " bad" : "");
  el.textContent = st === "ok" ? "All answers saved" : st === "saving" ? "Saving…" : "Offline – retrying…";
}

async function save(payload, attempt = 0) {
  const p = (async () => {
    setSave("saving");
    try {
      const r = await api("/api/answer", payload);
      if (r.status === 409) { load(); return; }
      if (r.status === 401) return showLogin("Session expired – please log in again.");
      if (r.error) throw new Error(r.error);
      if (inflight.size <= 1) setSave("ok");
    } catch (e) {
      setSave("bad"); await new Promise(res => setTimeout(res, Math.min(5000, 800 * (attempt + 1))));
      return save(payload, attempt + 1);
    }
  })();
  inflight.add(p); p.finally(() => inflight.delete(p)); return p;
}

function runClock() {
  const left = (deadline - performance.now()) / 1000, el = document.getElementById("clock"); if (!el) return;
  el.textContent = fmt(left);
  el.className = "clock" + (left <= 60 ? " crit" : left <= 180 ? " low" : "");
  if (left <= 0 && !leaving) { leaving = true; clearInterval(tick); finishRound(true); }
}

async function resync() {
  const r = await api("/api/state");
  if (r.stage === "round" && S && r.round === S.round) deadline = performance.now() + r.remaining * 1000;
  else if (r.stage && r.stage !== "login") { S = r; render(); }
}

async function finishRound(timeUp) {
  leaving = true; clearInterval(tick);
  if (timeUp) { const el = document.getElementById("clock"); if (el) el.textContent = "00:00"; }
  await Promise.allSettled([...inflight]);
  await api("/api/round/submit", {});
  leaving = false; load();
}

function confirmSubmit() {
  const un = document.querySelectorAll(".q").length - document.querySelectorAll(".q .opt.sel").length;
  const m = document.createElement("div"); m.className = "modal";
  m.innerHTML = `<div class="box"><h3>Submit Round ${S.round}?</h3><p>${un ? `<b>${un}</b> question${un > 1 ? "s are" : " is"} still unanswered. ` : ""}You cannot return to this round after submitting.</p>
    <div class="row"><button class="ghost" id="no">Keep working</button><button id="yes">Submit</button></div></div>`;
  document.body.appendChild(m);
  m.querySelector("#no").onclick = () => m.remove();
  m.querySelector("#yes").onclick = () => { m.remove(); finishRound(false); };
}

function clearTimers() { clearInterval(tick); clearInterval(syncT); clearTimeout(syncT); }

function render() {
  if (!S) return;
  if (S.stage === "ready") showReady();
  else if (S.stage === "round") showRound();
  else if (S.stage === "finished") showFinished();
}

async function load() {
  const r = await api("/api/state");
  if (r.stage === "login" || r.status === 401) return showLogin();
  S = r; render();
}

/* ---------- light integrity logging + copy protection ---------- */
let lastBlur = 0;
function logBlur() {
  if (!S || S.stage !== "round" || Date.now() - lastBlur < 1500) return;
  lastBlur = Date.now(); api("/api/event", { kind: "blur" });
}
window.addEventListener("blur", logBlur);
document.addEventListener("visibilitychange", () => { if (document.hidden) logBlur(); });
document.addEventListener("contextmenu", e => { if (S && S.stage === "round") e.preventDefault(); });
window.addEventListener("beforeunload", e => { if (S && S.stage === "round") { e.preventDefault(); e.returnValue = ""; } });

(async () => {
  CFG = (await api("/api/config"));
  document.getElementById("org").textContent = CFG.org;
  document.getElementById("ev").textContent = CFG.event;
  document.getElementById("foot").textContent = `${CFG.org} · ${CFG.subtitle}`;
  document.title = `${CFG.event} - ${CFG.org}`;
  load();
})();
