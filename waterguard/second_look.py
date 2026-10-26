"""A second look by a vision-language model: Nemotron reads the same chip an analyst would see.

When the measurements leave a cell undecided, the inspector can show its analyst chip
(BEFORE | AFTER, co-registered | COLOUR CHANGE dE, with the flagged ground outlined) to an NVIDIA
Nemotron vision-language model on Nebius Token Factory. It gets only the picture and what the panels
are, not the agent's own measurements, so its read is independent. It answers in a fixed JSON form:
what most likely caused the change, and why, in a sentence an analyst can check against the image.

The read can do two things, and nothing else (enforced in inspector.py, not trusted to the model):
  - send a cell to the analyst as a *likely false alarm* (a flag; a person still decides), when the
    model is confident the change is seasonal, the river, cloud/shadow or misalignment AND the colour
    evidence line is absent;
  - put its explanation on the review card.
It can never confirm damage and never remove anything.

    NEBIUS_API_KEY        Token Factory key (same as the copilot)
    NEBIUS_VL_MODEL       default nvidia/Nemotron-3.5-Super-VL
"""
import base64
import json
import os
import re
import time
from pathlib import Path

import cv2

VL_MODEL = "nvidia/Nemotron-3.5-Super-VL"
CAUSES = ["flood debris or scour", "landslide", "standing flood water", "seasonal vegetation change",
          "river level or turbidity", "cloud, haze or shadow", "image misalignment", "unclear"]
NOT_FLOOD = {"seasonal vegetation change", "river level or turbidity", "cloud, haze or shadow", "image misalignment"}
SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["cause", "fresh_sediment_or_debris_visible", "vegetation_lost", "confidence", "explanation"],
          "properties": {"cause": {"type": "string", "enum": CAUSES}, "fresh_sediment_or_debris_visible": {"type": "boolean"},
                         "vegetation_lost": {"type": "boolean"}, "confidence": {"type": "number"},
                         "explanation": {"type": "string"}}}
MAX_W = 1536

PROMPT = """You are checking one 600 m cell of a satellite flood-damage map, the way an image analyst would.
The image has three panels side by side, each the same 900 m window of Sentinel-2 imagery at 10 m:
  1. BEFORE: true colour, shortly before the event
  2. AFTER: true colour after the event, co-registered to BEFORE
  3. COLOUR CHANGE dE: CIELAB colour difference, blue = no change, red = strong change
The white square is the cell; the red outline (white in panel 3) is the ground the map flagged as flood impact.
Grey areas had no cloud-free view.

Event: {event}. Debris flows leave grey or brown sediment, boulders and scoured channels where there was
forest, fields or buildings. A monsoon season also greens or browns vegetation, changes river width and
turbidity, and leaves cloud and shadow; slightly misaligned images show change only along existing edges.

Look at the flagged ground and decide what most likely changed it. Reply with ONLY this JSON:
{{"cause": one of {causes},
 "fresh_sediment_or_debris_visible": true or false,
 "vegetation_lost": true or false,
 "confidence": a number from 0 to 1,
 "explanation": "one or two sentences pointing at what you see in the panels"}}"""


def available() -> bool:
    return bool(os.getenv("NEBIUS_API_KEY"))


def _image_url(path: Path) -> str:
    img = cv2.imread(str(path))
    if img.shape[1] > MAX_W:
        img = cv2.resize(img, (MAX_W, round(img.shape[0] * MAX_W / img.shape[1])), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def parse(text: str) -> dict:
    """The model's JSON, normalised; {'error': ...} if there is none."""
    text = re.sub(r"<(thinking|think)>.*?</\1>", "", text or "", flags=re.S)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"error": "no JSON in the reply"}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"error": "unreadable JSON in the reply"}
    cause = str(d.get("cause", "unclear")).strip().lower()
    cause = next((c for c in CAUSES if c == cause), None) or next((c for c in CAUSES if cause and (cause in c or c in cause)), "unclear")
    try:
        conf = min(max(float(d.get("confidence", 0)), 0.0), 1.0)
    except (TypeError, ValueError):
        conf = 0.0
    return {"cause": cause, "debris_visible": bool(d.get("fresh_sediment_or_debris_visible")),
            "vegetation_lost": bool(d.get("vegetation_lost")), "confidence": round(conf, 2),
            "explanation": str(d.get("explanation", ""))[:400]}


def read(chip: Path, event: str = "a glacier-lake outburst flood and debris flow, Nepal, August 2026") -> dict:
    """Ask the vision-language model about one chip. Never raises: errors come back as {'error': ...}."""
    from openai import OpenAI
    from .copilot import NEBIUS_BASE_URL
    model = os.getenv("NEBIUS_VL_MODEL", VL_MODEL)
    t = time.time()
    try:
        cli = OpenAI(base_url=os.getenv("NEBIUS_BASE_URL", NEBIUS_BASE_URL), api_key=os.environ["NEBIUS_API_KEY"],
                     timeout=90)
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": PROMPT.format(event=event, causes=json.dumps(CAUSES))},
            {"type": "image_url", "image_url": {"url": _image_url(Path(chip))}}]}]
        # the model reasons first (often ~700-1000 tokens): leave room, and let the server enforce the JSON form
        try:
            r = cli.chat.completions.create(model=model, temperature=0.0, max_tokens=3000, messages=msgs,
                                            response_format={"type": "json_schema",
                                                             "json_schema": {"name": "second_look", "schema": SCHEMA, "strict": True}})
        except Exception:          # endpoint without structured output: ask for JSON in the prompt only
            r = cli.chat.completions.create(model=model, temperature=0.0, max_tokens=3000, messages=msgs)
        out = parse(r.choices[0].message.content)
        u = getattr(r, "usage", None)
        out["tokens"] = (u.prompt_tokens + u.completion_tokens) if u else None
    except Exception as e:   # network, quota, model not served: the agent carries on without it
        out = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    out["model"], out["seconds"] = model, round(time.time() - t, 1)
    return out


def says_not_flood(sl: dict | None, min_conf: float = 0.7) -> bool:
    return bool(sl) and "error" not in sl and sl["cause"] in NOT_FLOOD and sl["confidence"] >= min_conf
