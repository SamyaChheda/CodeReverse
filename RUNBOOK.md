# Code Reverse Engineering – build & run guide

## 1. What this is
One Flask + SQLite server on the organiser PC. Participant PCs only need a browser pointed at
`http://<server-ip>:5000`. No internet, no database install.

```
Organiser PC (server + /admin dashboard + projector)
        |  lab LAN / switch
15–20 Ubuntu PCs  ->  browser in kiosk mode  ->  http://SERVER_IP:5000
```

Server-side guarantees:
* Timers live on the server. Refresh / re-login / changing the PC clock can't reset or extend a round.
* Answers autosave on every click; a crashed PC loses nothing. Re-login with same phone+email resumes.
* Correct answers never reach the browser. Each participant gets a random, topic-balanced paper
  (5 / 4 / 3 questions from the 25 / 20 / 15 banks) with shuffled option order, so neighbours see different screens.
* Max 15 seats (changeable live). The 16th person sees "lab is full" and is admitted automatically when a seat frees = rolling entry.
* Score: R1 2/q, R2 5/q, R3 10/q = 60. Rank = marks, then lower total in-round time; identical marks+time are flagged "TIE" for the tie-break challenge.

## 2. One-time setup (organiser PC)
```bash
sudo apt install -y python3-flask      # while you still have internet
cd cre
nano config.py                         # change ADMIN_PASSWORD and ACCESS_CODE
./run.sh                               # prints the participant URL
sudo ufw allow 5000/tcp                # only if ufw is enabled
```
Give the server PC a fixed IP. Test from another PC: `curl http://SERVER_IP:5000/api/config`.

Participant PCs: nothing to install. `./kiosk.sh SERVER_IP` (or `chromium --kiosk --incognito http://SERVER_IP:5000`).
Use a locked participant account (no terminal, no USB). The code snippets are short enough to run by hand, so
**invigilation and a locked account are the real anti-cheat**; the site only disables copy/right-click and counts tab switches (column "Tabs").

## 3. Before the day
1. `python3 tools/simulate.py http://SERVER_IP:5000 20`, then stop the server and delete `data/event.db`.
2. Play a full round on 2–3 real lab PCs; check screen fit.
3. Round 3 partial marks (optional): `CRE_R3_EXPLAIN_MARKS=4 ./run.sh` adds an "explain your reasoning" box to Round 3
   (6 marks for the option + up to 4 you grade in /admin → "Grade explanations"). Default 0 = fully automatic.
4. Copy the `cre` folder to a pen drive as backup.

## 4. Event flow
| When | Who does what |
|---|---|
| Doors | Participant signs in, gets a PC; a volunteer tells them the access code (don't print it on screens). |
| Entry | Name / phone / email / code → Login. Up to 15 inside; others wait and are admitted automatically as seats free up. |
| During | /admin shows status, time left, scores, tab switches. Press **Hide scores** before projecting. |
| Problems | PC froze → re-login (same phone+email). Lost time → **+2 min** (not counted in their total time). Wrong/duplicate entry → **Reset** / **Delete**. Suspicious → check Tabs, **End**. |
| End | Set new logins to CLOSED, wait for the last finisher, **Download CSV**, grade R3 explanations if enabled. |
| Result | Top rows of the dashboard; "TIE" rows play the tie-break challenge. |

One participant takes ≈ 45 min + a few minutes of transitions, so with 15 seats expect roughly 18–20 people per hour.

## 5. Question bank
`questions.json` is generated from the docx: `python3 tools/parse_bank.py tools/bank.docx questions.json`.
`python3 tools/verify_bank.py questions.json` runs every snippet and compares it with the key.
Fixed: **R2-14** — key said 1, code prints 0 (answer A). 28 purpose/behaviour questions can't be machine-checked; read them once.
The bank is Python only (the old site also showed Java).

## 6. Files
`app.py` server · `config.py` settings · `questions.json` bank · `static/` pages · `data/event.db` created on first run (all results) · `tools/` parse, verify and load-test scripts.
