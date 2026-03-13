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
                        # Tag tier based on source
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
                # Only include conflict-relevant items
                keywords = ["war","conflict","ukraine","russia","israel","iran","gaza","houthi","military","strike","missile","attack","killed","troops","ceasefire","nato","hezbollah"]
                combined = (title + desc).lower()
                if any(k in combined for k in keywords):
                    articles.append(f"[{tier}][{source_name} {pub}] {title}: {desc[:200]}")
            print(f"  RSS {source_name}: {len(items)} items fetched")
        except Exception as e:
            print(f"  RSS error for {source_name}: {e}")
    print(f"Total RSS articles: {len(articles)}")
    return articles

# ── STEP 3: FETCH AL JAZEERA LIVE TRACKER ───────────────
def fetch_aljazeera_tracker():
    url = "https://www.aljazeera.com/news/2026/3/1/us-israel-attacks-on-iran-death-toll-and-injuries-live-tracker"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", errors="ignore")
        # Extract text between common HTML tags, strip tags
        import re
        text = re.sub(r'<[^>]+>', ' ', raw)
        text = re.sub(r'\s+', ' ', text).strip()
        # Grab first 3000 chars of meaningful content
        snippet = text[:3000]
        print(f"  AJ tracker fetched: {len(snippet)} chars")
        return f"[VERIFIED][Al Jazeera Live Tracker] Casualty tracker data: {snippet}"
    except Exception as e:
        print(f"  AJ tracker error: {e}")
        return None

# ── HELPER: SOURCE TIER ──────────────────────────────────
def get_source_tier(source_name):
    verified = ["reuters","associated press","ap news","bbc","un ","united nations","al jazeera","radio free europe","rferl","the guardian","new york times","washington post","financial times"]
    analyst  = ["bellingcat","isw","institute for the study","war on the rocks","foreign policy","foreign affairs","defense one","breaking defense","jane's"]
    s = source_name.lower()
    if any(v in s for v in verified):  return "VERIFIED"
    if any(a in s for a in analyst):   return "ANALYST"
    return "REPORTED"

# ── STEP 4: LOAD PREVIOUS DATA ───────────────────────────
def load_previous_data():
    try:
        with open(OUTPUT_PATH, "r") as f:
            existing = json.load(f)
        return {
            "escalation_score": existing.get("escalation", {}).get("score", None),
            "cumulative": existing.get("casualties", {}).get("cumulative", {})
        }
    except Exception:
        return {"escalation_score": None, "cumulative": {}}

# ── STEP 5: ASK CLAUDE ───────────────────────────────────
def ask_claude(all_headlines, prev_data):
    if not all_headlines:
        print("No headlines — skipping Claude call.")
        return None

    headlines_text = "\n".join(f"- {h}" for h in all_headlines[:60])
    prev_score = prev_data.get("escalation_score")
    prev_score_text = f"Yesterday's escalation score was {prev_score}/10." if prev_score else "No previous escalation score available."

    prompt = f"""You are a neutral, factual conflict-data analyst for a war tracking website.
Today is {TODAY}.
{prev_score_text}

Headlines are tagged with their source tier:
[VERIFIED] = Reuters, AP, BBC, UN, Al Jazeera, RFE/RL
[ANALYST] = Bellingcat, ISW, War on the Rocks, established analysts
[REPORTED] = Other news outlets
Items without a tag should be treated as [REPORTED].

Below are recent headlines about ongoing global military conflicts.
Extract structured data and return ONLY a valid JSON object — no explanation, no markdown, no code fences.

Headlines:
{headlines_text}

Return this exact JSON structure. For anything not in headlines use empty arrays [] or empty strings "".
Casualty numbers: strings like "~500" or "est. 1,200" — never raw integers.
Strike methods: Air/Drone, Missile/Surface, Ground/Armored, Naval/USV, Naval/Cruise Missile, Ballistic Missile, Anti-Ship Missile, Air/Precision Strike, Rocket/Surface
For lat/lng: decimal coordinates of target_location. Kyiv=50.45,30.52. Beirut=33.89,35.50.
For source_tier on strikes/updates: use "verified", "analyst", or "unverified" based on where the info came from.

Escalation score rules:
1-3=Low: Diplomatic tensions only
4-5=Guarded: Sporadic strikes, proxy activity
6-7=Elevated: Active multi-front conflict, direct state strikes
8-9=High: Superpower involvement, nuclear rhetoric, mass mobilization
10=Critical: Imminent/active WMD or full superpower war

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
        "claim": "Description of claimed figure e.g. Russian military KIA",
        "figure": "~680,000",
        "claimed_by": "Ukraine MoD",
        "as_of": "Date or approximate"
      }}
    ]
  }},
  "quotes": {{
    "russia": [
      {{"text": "Quote if found", "speaker": "Name", "title": "Title", "date": "Date"}}
    ],
    "ukraine": [
      {{"text": "Quote if found", "speaker": "Name", "title": "Title", "date": "Date"}}
    ],
    "middle_east": [
      {{"text": "Quote if found", "speaker": "Name", "title": "Title", "date": "Date"}}
    ]
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
    "notes": "One sentence on any significant financial development today"
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

# ── STEP 6: SAVE ─────────────────────────────────────────
def save_data(new_data, prev_cumulative):
    new_data["last_updated"] = NOW
    new_data.setdefault("casualties", {})

    # Preserve cumulative totals from previous runs
    if prev_cumulative:
        new_data["casualties"]["cumulative"] = prev_cumulative

    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(new_data, f, indent=2)
    print(f"✓ war_data.json updated at {NOW}")

    archive_dir = "data/archive"
    os.makedirs(archive_dir, exist_ok=True)
    archive_path = f"{archive_dir}/{TODAY}.json"
    with open(archive_path, "w") as f:
        json.dump(new_data, f, indent=2)
    print(f"✓ Archive saved: {archive_path}")

    esc = new_data.get("escalation", {})
    print(f"  Escalation:   {esc.get('score','—')}/10 ({esc.get('level','—')})")
    print(f"  Ticker items: {len(new_data.get('ticker_items',[]))}")
    print(f"  Strikes EU:   {len(new_data.get('strikes_today',{}).get('eastern_europe',[]))}")
    print(f"  Strikes ME:   {len(new_data.get('strikes_today',{}).get('middle_east',[]))}")
    print(f"  Claimed totals: {len(new_data.get('casualties',{}).get('claimed_totals',[]))}")

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

    print("Loading previous data...")
    prev_data = load_previous_data()
    print(f"  Previous escalation: {prev_data.get('escalation_score')}")

    print("Asking Claude to structure data...")
    structured = ask_claude(all_headlines, prev_data)

    if structured is None:
        print("No data to save.")
        exit(1)

    print("Saving data...")
    save_data(structured, prev_data.get("cumulative", {}))
    print("Done ✓")
