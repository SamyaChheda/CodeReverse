"use strict";
const $a = document.getElementById("app");
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const mmss = s => s == null ? "" : String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(Math.round(s) % 60).padStart(2, "0");
let hideScores = false, timer = null, D = null, built = false;

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  let j = {}; try { j = await r.json(); } catch (e) {}
  return { status: r.status, ...j };
}

function loginView(msg) {
  clearInterval(timer); built = false;
  $a.innerHTML = `<form class="card" id="f" style="max-width:380px;margin:40px auto"><h2>Organiser login</h2>
    <label>Admin password</label><input type="password" id="pw" autofocus><button class="full">Open dashboard</button>
    <div class="err">${esc(msg || "")}</div></form>`;
  document.getElementById("f").onsubmit = async e => {
    e.preventDefault();
    const r = await api("/admin/api/login", { password: document.getElementById("pw").value });
    r.error ? loginView(r.error) : start();
  };
}

function shell() {
  $a.innerHTML = `<div class="toolbar">
    <div class="box"><label>Seats in use</label><b id="s_slots">-</b></div>
    <div class="box"><label>Running now</label><b id="s_run">-</b></div>
    <div class="box"><label>Finished / Total</label><b id="s_fin">-</b></div>
    <div class="box"><label>Max seats</label><input type="number" id="maxa" min="1" max="100"> <button class="sm" id="setmax">Set</button></div>
    <div class="box"><label>Access code</label><input type="text" id="code"> <button class="sm" id="setcode">Set</button></div>
    <div class="box"><label>New logins</label><button class="sm" id="reg"></button></div>
    <div class="box"><label>Display</label><button class="sm ghost" id="hide">Hide scores (projector)</button></div>
    <div class="box"><label>Results</label><a href="/admin/api/export.csv"><button class="sm good">Download CSV</button></a>
      <button class="sm ghost hide" id="grade">Grade explanations (<span id="np">0</span>)</button></div></div>
  <div id="scores" class="scores"><div style="overflow:auto;max-height:calc(100vh - 230px)"><table><thead><tr>
    <th>#</th><th>Name</th><th>Phone</th><th>Status</th><th>Time left</th><th>R1</th><th>R2</th><th>R3</th><th>Total</th><th>Time</th><th>Tabs</th><th>Actions</th></tr></thead>
    <tbody id="rows"></tbody></table></div></div>
  <p style="color:var(--mute);font-size:.85rem">Ranking: highest total marks, then lowest total round time. "TIE" = same marks and same time, needs the tie-break challenge. Seats free up automatically when a participant finishes or their browser disappears for 3 minutes.</p>`;
  document.getElementById("hide").onclick = e => { hideScores = !hideScores; document.getElementById("scores").classList.toggle("hidden", hideScores); e.target.textContent = hideScores ? "Show scores" : "Hide scores (projector)"; };
  document.getElementById("setmax").onclick = () => api("/admin/api/settings", { max_active: +document.getElementById("maxa").value }).then(refresh);
  document.getElementById("setcode").onclick = () => api("/admin/api/settings", { access_code: document.getElementById("code").value }).then(refresh);
  document.getElementById("reg").onclick = () => api("/admin/api/settings", { registration_open: !D.settings.registration_open }).then(refresh);
  document.getElementById("grade").onclick = gradingView;
  document.getElementById("rows").onclick = rowClick;
  built = true;
}

async function refresh() {
  const r = await api("/admin/api/overview");
  if (r.status === 401) return loginView();
  D = r; if (!built) shell();
  const c = r.counts, set = r.settings;
  document.getElementById("s_slots").textContent = `${c.slots_used} / ${set.max_active}`;
  document.getElementById("s_run").textContent = c.running;
  document.getElementById("s_fin").textContent = `${c.finished} / ${c.total}`;
  const maxa = document.getElementById("maxa"), code = document.getElementById("code");
  if (document.activeElement !== maxa) maxa.value = set.max_active;
  if (document.activeElement !== code) code.value = set.access_code;
  const reg = document.getElementById("reg"); reg.textContent = set.registration_open ? "OPEN – click to close" : "CLOSED – click to open"; reg.className = "sm " + (set.registration_open ? "good" : "danger");
  const g = document.getElementById("grade"); g.classList.toggle("hide", !r.explain_enabled); document.getElementById("np").textContent = c.pending_grading;
  document.getElementById("rows").innerHTML = r.board.map(x => {
    const fin = x.status !== "active", live = x.remaining != null;
    const dot = fin ? "fin" : x.online ? "on" : "";
    return `<tr><td>${x.rank || ""}</td><td><span class="dot ${dot}"></span><b>${esc(x.name)}</b> ${x.tie ? '<span class="tag tie">TIE</span>' : ""}</td>
      <td class="num">${esc(x.phone)}</td><td>${esc(x.stage)}${!fin && !x.online ? ' <span class="tag warn">offline</span>' : ""}</td>
      <td class="num">${live ? mmss(x.remaining) : ""}</td>
      ${[1, 2, 3].map(k => `<td class="num sc">${x.per_round[k]}</td>`).join("")}
      <td class="num sc"><b>${x.score}</b>${x.pending ? ` <span class="tag warn" title="ungraded explanations">+${x.pending}?</span>` : ""}</td>
      <td class="num sc">${x.time ? mmss(x.time) : ""}</td><td class="num">${x.tabs ? `<span class="tag warn">${x.tabs}</span>` : "0"}</td>
      <td class="row-actions"><button class="sm ghost" data-a="view" data-id="${x.id}">View</button>
      ${fin ? `<button class="sm ghost" data-a="reopen" data-id="${x.id}">Reopen</button>` : `<button class="sm ghost" data-a="extend" data-id="${x.id}">+2 min</button><button class="sm ghost" data-a="end" data-id="${x.id}">End</button>`}
      <button class="sm ghost" data-a="reset" data-id="${x.id}">Reset</button><button class="sm danger" data-a="delete" data-id="${x.id}">Delete</button></td></tr>`;
  }).join("") || `<tr><td colspan="12" style="color:var(--mute);padding:24px">No participants yet.</td></tr>`;
}

async function rowClick(e) {
  const b = e.target.closest("button[data-a]"); if (!b) return;
  const id = b.dataset.id, a = b.dataset.a, who = D.board.find(x => x.id == id).name;
  if (a === "view") return detailView(id);
  const msg = { end: `End ${who}'s event now?`, reset: `Reset ${who}? All their answers and times are erased and they restart Round 1 with the same paper.`,
    delete: `Delete ${who} completely?`, reopen: `Reopen ${who}?`, extend: null }[a];
  if (msg && !confirm(msg)) return;
  await api("/admin/api/participant/" + id, { action: a, seconds: 120 }); refresh();
}

function modal(html) {
  const m = document.createElement("div"); m.className = "modal"; m.innerHTML = `<div class="box big">${html}<div class="row"><button class="ghost" id="close">Close</button></div></div>`;
  document.body.appendChild(m); m.querySelector("#close").onclick = () => { m.remove(); refresh(); }; return m;
}

async function detailView(id) {
  const r = await api("/admin/api/participant/" + id);
  modal(`<h2>${esc(r.name)}</h2>` + r.questions.map(q => `<div class="qd ${q.ok ? "ok" : "no"}"><small>Round ${q.round} &middot; ${esc(q.id)}</small>
    <pre class="code" style="user-select:text">${esc(q.code)}</pre><b>${esc(q.question)}</b>
    <div>Answered: <b>${q.given == null ? "(none)" : esc(q.given)}</b></div>${q.ok ? "" : `<div>Correct: <b>${esc(q.correct)}</b></div>`}
    ${q.explain ? `<div><small>Explanation typed:</small> ${esc(q.explain)}</div>` : ""}</div>`).join(""));
}

async function gradingView() {
  const r = await api("/admin/api/grading"), max = r.max;
  const m = modal(`<h2>Grade explanations (0–${max})</h2><p style="color:var(--mute)">Ungraded first. Compare with the model explanation.</p>` +
    (r.items.map(i => `<div class="qd" id="g_${i.pid}_${i.qid}"><small>${esc(i.name)} &middot; ${esc(i.qid)} &middot; MCQ ${i.ok ? "correct" : "wrong"}</small>
    <pre class="code" style="user-select:text">${esc(i.code)}</pre><b>${esc(i.question)}</b>
    <div style="margin:8px 0"><small>Participant wrote:</small> ${esc(i.explain)}</div><div><small>Model:</small> ${esc(i.model)}</div>
    <div class="row-actions" style="margin-top:8px">${Array.from({ length: max + 1 }, (_, k) => `<button class="sm ${i.marks === k ? "" : "ghost"}" data-p="${i.pid}" data-q="${i.qid}" data-k="${k}">${k}</button>`).join("")}</div></div>`).join("") || "<p>Nothing to grade.</p>"));
  m.onclick = async e => {
    const b = e.target.closest("button[data-k]"); if (!b) return;
    await api("/admin/api/grade", { pid: b.dataset.p, qid: b.dataset.q, marks: +b.dataset.k });
    b.parentElement.querySelectorAll("button").forEach(x => x.className = "sm ghost"); b.className = "sm";
  };
}

function start() { refresh(); clearInterval(timer); timer = setInterval(refresh, 3000); }
start();
