"""Reports from the web: what news and agencies say after the event (Tavily search).

The satellite maps say where the ground changed and which roads are gone. They cannot say whether a
road has since been reopened, where relief is being staged, or what casualties the authorities have
reported. The copilot can look that up here, as a clearly separate source:

  - web reports are NEVER an input to the map, the damage figures, the access analysis or the
    ledger: they live only in copilot answers;
  - every fact taken from them is attributed to its site, and numbers that appear only in web
    reports are listed as "from web reports, not checked against the maps" (copilot.verify);
  - results are cached by query and date window, so an answer can be traced to what was read.

    TAVILY_API_KEY   https://app.tavily.com (free tier)
"""
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests

from .config import CACHE_DIR

URL = "https://api.tavily.com/search"
CACHE = CACHE_DIR / "web"
DAYS_AFTER = 60
# a headline about the event, not a story that only mentions the area in passing
DISASTER = re.compile(r"\b(floods?|flooding|glacier|glof|landslides?|mudslides?|debris|disaster|rescue|relief|missing|dead|"
                      r"deaths?|killed|evacuat\w*|highway|roads?|bridges?|aid|monsoon)\b")
# social media and video: unattributable posts, not reports
EXCLUDE = ["facebook.com", "instagram.com", "tiktok.com", "x.com", "twitter.com", "youtube.com", "pinterest.com", "reddit.com",
           "linkedin.com"]


MAX_PER_HOUR = int(os.getenv("WATERGUARD_WEB_PER_HOUR", "60"))   # uncached searches (a public demo spends credits)
_recent: list = []


def available() -> bool:
    return bool(os.getenv("TAVILY_API_KEY"))


def reports(query: str, event_utc: str, place_hint: str = "", max_results: int = 6, days_after: int = DAYS_AFTER) -> dict:
    """News and agency reports published from the day before the event to `days_after` days after it.
    place_hint: the area's place names and country. They are added to the query, and a result must name
    one of them (search relevance alone lets unrelated stories from the same days through)."""
    if not available():
        return {"error": "web reports are not configured (TAVILY_API_KEY)"}
    ev = datetime.fromisoformat(event_utc.replace("Z", "+00:00"))
    start = (ev - timedelta(days=1)).date()
    end = min(ev + timedelta(days=days_after), datetime.now(timezone.utc)).date()
    q = " ".join(x for x in (query.strip(), place_hint.strip()) if x)[:380]
    body = {"query": q, "topic": "news", "search_depth": "basic", "max_results": 10,
            "start_date": start.isoformat(), "end_date": end.isoformat(), "include_answer": False,
            "exclude_domains": EXCLUDE}
    key = hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
    cached = CACHE / f"{key}.json"
    if cached.exists():
        raw = json.loads(cached.read_text(encoding="utf-8"))
    else:
        now = datetime.now(timezone.utc).timestamp()
        _recent[:] = [x for x in _recent if now - x < 3600]
        if len(_recent) >= MAX_PER_HOUR:
            return {"error": "web search limit for this hour reached; try again later"}
        _recent.append(now)
        try:
            r = requests.post(URL, json=body, headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"}, timeout=25)
            r.raise_for_status()
            raw = r.json()
        except Exception as e:
            return {"error": f"web search failed: {type(e).__name__}: {str(e)[:120]}"}
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps({**raw, "request": body, "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                                     ensure_ascii=False), encoding="utf-8")
    anchors = [w.lower() for w in place_hint.split() if len(w) > 3]

    def about(x):   # names the area, and the headline is about the area or a disaster (not a sidebar mention)
        title, text = x.get("title", "").lower(), f"{x.get('title', '')} {x.get('content', '')}".lower()
        return not anchors or (any(a in text for a in anchors)
                               and (any(a in title for a in anchors) or bool(DISASTER.search(title))))
    items = [{"title": x.get("title", ""), "url": x.get("url", ""), "site": urlparse(x.get("url", "")).netloc.removeprefix("www."),
              "published": (x.get("published_date") or "")[:16], "snippet": (x.get("content") or "")[:600]}
             for x in raw.get("results", []) if x.get("url", "").startswith(("http://", "https://")) and about(x)][:max_results]
    return {"source": "web search (Tavily, news): reports from other organisations, NOT checked against the satellite maps",
            "searched": q, "window": f"{start} to {end}", "results": items}
