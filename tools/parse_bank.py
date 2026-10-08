#!/usr/bin/env python3
"""Convert the question-bank .docx into questions.json.

Usage: python3 tools/parse_bank.py bank.docx questions.json
"""
import json
import re
import sys

import docx


# Corrections to the source document (found by running the code in verify_bank.py)
FIXES = {
    "R2-14": {"correct": "A",
              "explanation": "No two neighbouring letters in banana are equal (b-a, a-n, n-a, a-n, n-a), so count stays 0."},
}


def parse(path):
    d = docx.Document(path)
    paras = [(p.style.name, p.text.rstrip()) for p in d.paragraphs if p.text.strip()]
    questions, cur, rnd, mode = [], None, 0, None

    def flush():
        nonlocal cur
        if cur:
            cur["code"] = "\n".join(cur["code"]).rstrip("\n")
            questions.append(cur)
        cur = None

    for style, text in paras:
        if style == "Heading 1":
            m = re.match(r"Round (\d)", text)
            if text.startswith("Quick Answer Key"):
                flush()
                break
            if m:
                flush()
                rnd = int(m.group(1))
            continue
        if style == "Heading 2" and rnd:
            m = re.match(r"(R\d-\d+)\s+[—-]\s+(.*)", text)
            if m:
                flush()
                cur = {"id": m.group(1), "round": rnd, "title": m.group(2).strip(),
                       "difficulty": "", "topic": "", "type": "", "code": [],
                       "question": "", "options": [], "answer": "", "explanation": ""}
                mode = None
            continue
        if not cur:
            continue
        if text.startswith("Difficulty:"):
            for part in text.split("|"):
                k, _, v = part.partition(":")
                k = k.strip().lower()
                v = v.strip()
                if k == "difficulty":
                    cur["difficulty"] = v
                elif k.startswith("concept"):
                    cur["topic"] = v
                elif k == "type":
                    cur["type"] = v
        elif text.strip() == "Code:":
            mode = "code"
        elif text.startswith("Question:"):
            cur["question"] = text[len("Question:"):].strip()
            mode = "question"
        elif text.startswith("Correct answer:"):
            cur["answer"] = text[len("Correct answer:"):].strip()
            mode = None
        elif text.startswith("Explanation/solution:"):
            cur["explanation"] = text[len("Explanation/solution:"):].strip()
            mode = None
        elif style == "List Bullet" and re.match(r"^[A-F]\.\s", text):
            cur["options"].append({"letter": text[0], "text": text[3:].strip()})
        elif mode == "code":
            cur["code"].append(text)
    flush()

    for q in questions:
        m = re.match(r"^([A-F])\.", q["answer"])
        q["correct"] = m.group(1) if m else None
        del q["answer"]
    for q in questions:
        q.update(FIXES.get(q["id"], {}))
    return questions


if __name__ == "__main__":
    qs = parse(sys.argv[1])
    json.dump(qs, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
    from collections import Counter
    print(Counter(q["round"] for q in qs), "questions written to", sys.argv[2])
    for q in qs:
        letters = [o["letter"] for o in q["options"]]
        if q["correct"] not in letters or len(letters) < 2 or not q["code"]:
            print("PROBLEM:", q["id"], letters, q["correct"])
