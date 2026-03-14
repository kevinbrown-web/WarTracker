import os
import json
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

# ── CONFIG ──────────────────────────────────────────────
NEWS_API_KEY    = os.environ["NEWS_API_KEY"]
ANTHROPIC_KEY   = os.environ["ANTHROPIC_API_KEY"]
OUTPUT_PATH     = "data/war_data.json"
TODAY           = datetime.datetime.utcnow().strftime("%Y-%m-%d")
NOW             = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
ARCHIVE_PATH    = f"data/archive/{TODAY}.json"

# ── STEP 1: FETCH NEWSAPI HEADLINES ─────────────────────
def fetch_headlines():
    queries = [
        "Ukraine Russia war military",
        "Israel Iran war strikes",
        "Gaza Lebanon Hezbollah",
        "NATO military conflict",
        "North Korea Russia troops",
        "Houthi Red Sea attack",
        "Bellingcat conflict verification",
        "Michael Kofman Russia military analysis",
        "ISW Ukraine assessment",
        "OSINT Ukraine Russia",
        "Rob Lee military analysis"
    ]
    articles = []
    for q in queries:
        params = urllib.parse.urlencode({
            "q": q,
            "sortBy": "publishedAt",
            "pageSize": 8,
            "apiKey": NEWS_API_KEY,
            "language": "en"
        })
        url = f"https://newsapi.org/v2/everything?{params}"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())
                status = data.get("status")
                total  = data.get("totalResults", 0)
                print(f"  NewsAPI '{q}': status={status}, results={total}")
                for a in data.get("articles", []):
                    title  = a.get("title", "") or ""
                    desc   = a.get("description", "") or ""
                    source = a.get("source", {}).get("name", "Unknown")
                    pub    = a.get("publishedAt", "")[:10]
                    if title and "[Removed]" not in title:
                        tier = get_source_tier(source)
                        articles.append(f"[{tier}][{source} {pub}] {title}: {desc}")
        except Exception as e:
            print(f"  NewsAPI error for '{q}': {e}")

    seen, unique = set(), []
    for a in articles:
        if a not in seen:
            seen.add(a)
            unique.append(a)
    print(f"Total NewsAPI headlines: {len(unique)}")
    return unique[:48]

# ── STEP 2: FETCH RSS FEEDS ──────────────────────────────
def fetch_rss():
    feeds = [
        ("https://www.bellingcat.com/feed/", "Bellingcat", "ANALYST"),
        ("https://understandingwar.org/rss.xml", "ISW", "ANALYST"),
        ("https://warontherocks.com/feed/", "War on the Rocks", "ANALYST"),
        ("https://www.rferl.org/api/zpiqeoep_qos", "Radio Free Europe", "VERIFIED"),
        ("https://www.aljazeera.com/xml/rss/all.xml", "Al Jazeera", "REPORTED"),
    ]
    articles = []
    for url, source_name, tier in feeds:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "WarTracker/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                content = r.read()
            root = ET.fromstring(content)
            items = root.findall(".//item")[:5]
            for item in items:
                title = item.findtext("title", "") or ""
                desc  = item.findtext("description", "") or ""
                pub   = item.findtext("pubDate", "")[:16] if item.findtext("pubDate") else ""
                keywords = ["war","conflict","ukraine","russia","israel","iran","gaza","houthi","military","strike","missile","attack","killed","troops","ceasefire","nato","hezbollah"]
                combined = (title + desc).lower()
                if any(k in combined for k in keywords):
                    articles.append(f"[{tier}][{source_name} {pub}] {title}: {desc[:200]}")
            print(f"  RSS {source_name}: {len(items)} items fetched")
        except Exception as e:
            print(f"  RSS error for {source_name}: {e}")
    print(f"Total RSS articles: {len(articles)}")
    return articles

# ── STEP 3: FETCH AL JAZEERA TRACKER ────────────────────
def fetch_aljazeera_tracker():
    url = "https://www.aljazeera.com/news/2026/3/1/us-israel-attacks-on-iran-death-toll-and-injuries-live-tracker"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", errors="ignore")
        import re
        text = re.sub(r'<[^>]+>', ' ', raw)
        text = re.sub(r'\s+', ' ', text).strip()
        snippet = text[:3000]
        print(f"  AJ tracker fetched: {len(snippet)} chars")
        return f"[VERIFIED][Al Jazeera Live Tracker] Casualty tracker data: {snippet}"
    except Exception as e:
        print(f"  AJ tracker error: {e}")
        return None

# ── HELPER: SOURCE TIER ──────────────────────────────────
def get_source_tier(source_name):
    verified = ["reuters","associated press","ap news","bbc","un ","united nations","al jazeera","radio free europe","rferl","the guardian","new york times","washington post","financial times"]
    analyst  = ["bellingcat","isw","institute for the study","war on the rocks","foreign policy","foreign affairs","defense one","breaking defense"]
    s = source_name.lower()
    if any(v in s for v in verified):  return "VERIFIED"
    if any(a in s for a in analyst):   return "ANALYST"
    return "REPORTED"

# ── STEP 4: LOAD TODAY'S EXISTING DATA ──────────────────
def load_today_data():
    """Load today's archive if it exists — for within-day accumulation."""
    try:
        with open(ARCHIVE_PATH, "r") as f:
            data = json.load(f)
        print(f"  Found existing data for {TODAY} — will accumulate")
        return data
    except Exception:
        print(f"  No existing data for {TODAY} — starting fresh")
        return None

def load_previous_escalation():
    """Load previous escalation score for delta calculation."""
    try:
        with open(OUTPUT_PATH, "r") as f:
            existing = json.load(f)
        # Only use previous score if it's from a different day
        last_updated = existing.get("last_updated", "")[:10]
        if last_updated != TODAY:
            score = existing.get("escalation", {}).get("score", None)
            print(f"  Previous escalation score: {score} (from {last_updated})")
            return score
        return None
    except Exception:
        return None

def load_cumulative():
    """Always preserve cumulative casualty totals."""
    try:
        with open(OUTPUT_PATH, "r") as f:
            existing = json.load(f)
        return existing.get("casualties", {}).get("cumulative", {})
    except Exception:
        return {}

# ── STEP 5: MERGE NEW DATA INTO EXISTING ────────────────
def merge_data(existing, new_data):
    """
    Merge new run's data into existing today's data.
    Accumulate: strikes, casualties today, quotes, update_log, observers, claimed_totals
    Replace: escalation, ticker_items, financial, new_entrant
    """
    merged = existing.copy()

    # Always replace with latest assessment
    merged["escalation"]   = new_data.get("escalation", merged.get("escalation", {}))
    merged["ticker_items"] = new_data.get("ticker_items", merged.get("ticker_items", []))
    merged["financial"]    = new_data.get("financial", merged.get("financial", {}))
    merged["new_entrant"]  = new_data.get("new_entrant", merged.get("new_entrant", {}))

    # Accumulate strikes — deduplicate by description
    def merge_strikes(existing_list, new_list):
        existing_descs = {s.get("description","") for s in existing_list}
        for s in new_list:
            if s.get("description","") not in existing_descs:
                existing_list.append(s)
                existing_descs.add(s.get("description",""))
        return existing_list

    merged.setdefault("strikes_today", {"eastern_europe": [], "middle_east": []})
    merged["strikes_today"]["eastern_europe"] = merge_strikes(
        merged["strikes_today"].get("eastern_europe", []),
        new_data.get("strikes_today", {}).get("eastern_europe", [])
    )
    merged["strikes_today"]["middle_east"] = merge_strikes(
        merged["strikes_today"].get("middle_east", []),
        new_data.get("strikes_today", {}).get("middle_east", [])
    )

    # Accumulate casualties today — deduplicate by incident name
    merged.setdefault("casualties", {})
    existing_incidents = {c.get("incident","") for c in merged["casualties"].get("today", [])}
    new_incidents = [c for c in new_data.get("casualties", {}).get("today", [])
                     if c.get("incident","") not in existing_incidents]
    merged["casualties"]["today"] = merged["casualties"].get("today", []) + new_incidents

    # Accumulate claimed totals — deduplicate by claim+claimed_by
    existing_claims = {(c.get("claim",""), c.get("claimed_by",""))
                       for c in merged["casualties"].get("claimed_totals", [])}
    new_claims = [c for c in new_data.get("casualties", {}).get("claimed_totals", [])
                  if (c.get("claim",""), c.get("claimed_by","")) not in existing_claims]
    merged["casualties"]["claimed_totals"] = merged["casualties"].get("claimed_totals", []) + new_claims

    # Accumulate quotes — deduplicate by speaker+text
    merged.setdefault("quotes", {"russia": [], "ukraine": [], "middle_east": []})
    for theater in ["russia", "ukraine", "middle_east"]:
        existing_quotes = {(q.get("speaker",""), q.get("text","")[:50])
                           for q in merged["quotes"].get(theater, [])}
        new_quotes = [q for q in new_data.get("quotes", {}).get(theater, [])
                      if (q.get("speaker",""), q.get("text","")[:50]) not in existing_quotes]
        merged["quotes"][theater] = merged["quotes"].get(theater, []) + new_quotes

    # Accumulate update log — prepend new items, deduplicate by text
    existing_texts = {u.get("text","") for u in merged.get("update_log", [])}
    new_updates = [u for u in new_data.get("update_log", [])
                   if u.get("text","") not in existing_texts]
    merged["update_log"] = new_updates + merged.get("update_log", [])

    # Accumulate observers — deduplicate by country
    existing_countries = {o.get("country","") for o in merged.get("observers", [])}
    new_observers = [o for o in new_data.get("observers", [])
                     if o.get("country","") not in existing_countries]
    merged["observers"] = merged.get("observers", []) + new_observers

    return merged

# ── STEP 6: ASK CLAUDE ───────────────────────────────────
def ask_claude(all_headlines, prev_score):
    if not all_headlines:
        print("No headlines — skipping Claude call.")
        return None

    headlines_text = "\n".join(f"- {h}" for h in all_headlines[:60])
    prev_score_text = f"Yesterday's escalation score was {prev_score}/10." if prev_score else "No previous escalation score available."

    prompt = f"""You are a neutral, factual conflict-data analyst for a war tracking website.
Today is {TODAY}. This is update run {NOW}.
{prev_score_text}

Headlines are tagged with source tier:
[VERIFIED] = Reuters, AP, BBC, UN, Al Jazeera, RFE/RL
[ANALYST] = Bellingcat, ISW, War on the Rocks, established analysts
[REPORTED] = Other outlets

Extract structured data and return ONLY a valid JSON object — no explanation, no markdown, no code fences.

Headlines:
{headlines_text}

For anything not in headlines use empty arrays [] or empty strings "".
Casualty numbers: strings like "~500" or "est. 1,200" — never raw integers.
Strike methods: Air/Drone, Missile/Surface, Ground/Armored, Naval/USV, Naval/Cruise Missile, Ballistic Missile, Anti-Ship Missile, Air/Precision Strike, Rocket/Surface
For lat/lng: decimal coordinates of target_location. Kyiv=50.45,30.52. Beirut=33.89,35.50.
source_tier on strikes/updates/casualties: "verified", "analyst", or "unverified"

Escalation score:
1-3=Low, 4-5=Guarded, 6-7=Elevated, 8-9=High, 10=Critical

{{
  "escalation": {{
    "score": 6.5,
    "delta": "+0.3 from yesterday",
    "level": "Elevated",
    "rationale": "One sentence explaining today's score citing specific events."
  }},
  "ticker_items": ["3 to 5 short breaking news bullets, each under 15 words"],
  "new_entrant": {{
    "active": true or false,
    "text": "One sentence if a new country entered or exited conflict, else empty string"
  }},
  "strikes_today": {{
    "eastern_europe": [
      {{
        "time_utc": "HH:MM or Unknown",
        "attacker": "Country or group",
        "target_country": "Country",
        "target_location": "City or region",
        "description": "One sentence factual description",
        "method": "Strike method from list above",
        "lat": 0.0,
        "lng": 0.0,
        "source_tier": "verified or analyst or unverified"
      }}
    ],
    "middle_east": [
      {{
        "time_utc": "HH:MM or Unknown",
        "attacker": "Country or group",
        "target_country": "Country",
        "target_location": "City or region",
        "description": "One sentence factual description",
        "method": "Strike method from list above",
        "lat": 0.0,
        "lng": 0.0,
        "source_tier": "verified or analyst or unverified"
      }}
    ]
  }},
  "casualties": {{
    "today": [
      {{
        "incident": "Short incident name",
        "kia": "Number or estimate",
        "wia": "Number or estimate",
        "civilian": true or false,
        "source_tier": "verified or analyst or unverified"
      }}
    ],
    "claimed_totals": [
      {{
        "claim": "e.g. Russian military KIA",
        "figure": "~680,000",
        "claimed_by": "Ukraine MoD",
        "as_of": "Date or approximate"
      }}
    ]
  }},
  "quotes": {{
    "russia": [{{"text": "Quote", "speaker": "Name", "title": "Title", "date": "Date"}}],
    "ukraine": [{{"text": "Quote", "speaker": "Name", "title": "Title", "date": "Date"}}],
    "middle_east": [{{"text": "Quote", "speaker": "Name", "title": "Title", "date": "Date"}}]
  }},
  "observers": [
    {{
      "country": "Country name",
      "flag": "Emoji flag",
      "status": "One of: Supplying dual-use goods / Active materiel + troops / Basing + logistics / Strategic balancer / Mediator + arms supplier / Abstaining / purchasing / Monitoring",
      "description": "2-3 sentences on their involvement today"
    }}
  ],
  "financial": {{
    "usd_rub": "Rate or Unchanged",
    "brent_crude": "Price or Unchanged",
    "wheat_futures": "Price or Unchanged",
    "notes": "One sentence on any significant financial development"
  }},
  "update_log": [
    {{
      "time": "HH:MM UTC",
      "text": "One sentence per major event, most recent first",
      "source_tier": "verified or analyst or unverified"
    }}
  ]
}}"""

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01"
        }
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        response = json.loads(r.read())

    raw = response["content"][0]["text"].strip()
    print(f"Claude response: {len(raw)} chars")

    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]

    return json.loads(raw)

# ── STEP 7: SAVE ─────────────────────────────────────────
def save_data(final_data, cumulative):
    final_data["last_updated"] = NOW
    final_data.setdefault("casualties", {})
    if cumulative:
        final_data["casualties"]["cumulative"] = cumulative

    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(final_data, f, indent=2)
    print(f"✓ war_data.json saved")

    os.makedirs("data/archive", exist_ok=True)
    with open(ARCHIVE_PATH, "w") as f:
        json.dump(final_data, f, indent=2)
    print(f"✓ Archive saved: {ARCHIVE_PATH}")

    esc = final_data.get("escalation", {})
    eu  = final_data.get("strikes_today", {}).get("eastern_europe", [])
    me  = final_data.get("strikes_today", {}).get("middle_east", [])
    print(f"  Escalation:     {esc.get('score','—')}/10 ({esc.get('level','—')})")
    print(f"  Strikes EU:     {len(eu)}")
    print(f"  Strikes ME:     {len(me)}")
    print(f"  Ticker items:   {len(final_data.get('ticker_items',[]))}")
    print(f"  Update log:     {len(final_data.get('update_log',[]))}")
    print(f"  Claimed totals: {len(final_data.get('casualties',{}).get('claimed_totals',[]))}")

# ── MAIN ─────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"── War Tracker Update ── {NOW} ──")

    print("Fetching NewsAPI headlines...")
    news_headlines = fetch_headlines()

    print("Fetching RSS feeds...")
    rss_articles = fetch_rss()

    print("Fetching Al Jazeera tracker...")
    aj_tracker = fetch_aljazeera_tracker()

    all_headlines = news_headlines + rss_articles
    if aj_tracker:
        all_headlines.append(aj_tracker)

    if not all_headlines:
        print("ERROR: No headlines returned.")
        exit(1)

    print(f"Total sources: {len(all_headlines)}")

    # Load previous escalation for delta
    prev_score = load_previous_escalation()

    # Load cumulative totals (always preserved)
    cumulative = load_cumulative()

    print("Asking Claude to structure data...")
    new_data = ask_claude(all_headlines, prev_score)

    if new_data is None:
        print("No data returned from Claude.")
        exit(1)

    # Check if today's data already exists — accumulate if so
    existing_today = load_today_data()
    if existing_today:
        print("Merging with existing today's data...")
        final_data = merge_data(existing_today, new_data)
    else:
        print("Fresh day — using new data as-is...")
        final_data = new_data

    print("Saving data...")
    save_data(final_data, cumulative)
    print("Done ✓")
