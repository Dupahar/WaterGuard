"""Evaluate the copilot on a fixed question set (English + Nepali) for one run.

    python scripts/eval_copilot.py --run e34c30aded            # uses the configured LLM backend
    WATERGUARD_LLM=nebius python scripts/eval_copilot.py --run e34c30aded --out docs/copilot_eval_nemotron.json
Reports, per question: tools called, numbers in the answer, numbers the verifier rejected, whether
a retry was needed, numbers taken from web reports, and seconds. Writes --out (default docs/copilot_eval.json).
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from waterguard import copilot  # noqa: E402

QUESTIONS = [
    "Which villages are cut off?",
    "How many people are cut off and how did you estimate it?",
    "Which bridges are likely damaged? Give coordinates.",
    "What is the status of Syabru Bensi?",
    "Is any health facility affected?",
    "How much road is inside the impact zone?",
    "Write a 5-line situation report for the district emergency operations centre.",
    "Which satellite images was this based on?",
    "How many people died?",                      # not in the maps: must refuse to give a number
    "कुन कुन गाउँ सम्पर्कविहीन छन्?",
    "कति वटा पुल भत्किए?",
    "स्याब्रुबेसीको अवस्था के छ?",
    "जिल्ला आपतकालीन कार्य सञ्चालन केन्द्रका लागि छोटो स्थिति प्रतिवेदन लेख्नुहोस्।",
]
# asked only when web reports are configured (TAVILY_API_KEY): answers must keep web facts apart from map facts
QUESTIONS_WEB = [
    "What do news reports say about rescue and relief operations here?",
    "Has the main road through Syabru Bensi been reopened, according to reports?",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", default="docs/copilot_eval.json")
    a = ap.parse_args()
    out = []
    from waterguard import web
    for q in QUESTIONS + (QUESTIONS_WEB if web.available() else []):
        t = time.time()
        r = copilot.ask(a.run, q)
        out.append({"q": q, "answer": r["answer"], "backend": r["backend"], "tools": r["tool_calls"],
                    "numbers": r["numbers_checked"], "unverified_final": r["unverified"],
                    "web_numbers": r.get("web_numbers", []), "sources": [x["url"] for x in r.get("sources", [])],
                    "retried": r.get("retried", False), "seconds": round(time.time() - t, 1)})
        print(json.dumps(out[-1], ensure_ascii=False))
    s = {"questions": len(out), "answers_fully_verified": sum(not o["unverified_final"] for o in out),
         "needed_retry": sum(o["retried"] for o in out), "numbers_total": sum(o["numbers"] for o in out),
         "backend": out[0]["backend"] if out else None, "median_seconds": sorted(o["seconds"] for o in out)[len(out) // 2]}
    print(s)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"summary": s, "items": out}, ensure_ascii=False, indent=1),
                                              encoding="utf-8")


if __name__ == "__main__":
    main()
