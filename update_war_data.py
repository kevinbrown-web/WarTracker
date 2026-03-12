import os
import json
import datetime
import urllib.request
import urllib.parse

# ── CONFIG ──────────────────────────────────────────────
NEWS_API_KEY    = os.environ["NEWS_API_KEY"]
ANTHROPIC_KEY   = os.environ["ANTHROPIC_API_KEY"]
OUTPUT_PATH     = "data/war_data.json"
TODAY           = datetime.datetime.utcnow().strftime("%Y-%m-%d")
NOW             = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

# ── STEP 1: FETCH HEADLINES ──────────────────────────────
def fetch_headlines():
    queries = [
        "Ukraine Russia war military",
        "Israel Iran war strikes",
        "Gaza Lebanon Hezbollah",
        "NATO military conflict 2026",
        "North Korea Russia troops",
        "Houthi Red Sea attack"
    ]
    articles = []
    for q in queries:
        # No 'from' date filter — works on NewsAPI free tier
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
                for a in data.get("articles", []):
                    title = a.get("title", "")
                    desc  = a.get("description", "")
                    source = a.get("source", {}).get("name", "Unknown")
                    if title:
                        articles.append(f"[{source}] {title}: {desc}")
        except Exception as e:
            print(f"News fetch error for '{q}': {e}")
    # deduplicate and cap at 40 headlines
    seen, unique = set(), []
    for a in articles:
        if a not in seen:
            seen.add(a)
            unique.append(a)
    return unique[:40]

# ── STEP 2: ASK CLAUDE TO STRUCTURE THE DATA ─────────────
def ask_claude(headlines):
    headlines_text = "\n".join(f"- {h}" for h in headlines)
    prompt = f"""You are a neutral, factual conflict-data analyst for a war tracking website.
Today is {TODAY}.

Below are today's news headlines about ongoing global military conflicts.
Extract structured data and return ONLY a valid JSON object — no explanation, no markdown, no code fences.

Headlines:
{headlines_text}

Return this exact JSON structure, filling in what you can from the headlines.
For anything not mentioned in the headlines, use empty arrays [] or empty strings "".
Casualty numbers should be strings like "~500" or "est. 1,200" — never raw integers.
Strike methods: use one of: Air/Drone, Missile/Surface, Ground/Armored, Naval/USV, Naval/Cruise Missile, Ballistic Missile, Anti-Ship Missile, Air/Precision Strike, Rocket/Surface

{{
  "ticker_items": ["3 to 5 short breaking news bullets from today, each under 15 words"],
  "new_entrant": {{
    "active": true or false,
    "text": "One sentence if a new country entered or exited the conflict today, else empty string"
  }},
  "strikes_today": {{
    "eastern_europe": [
      {{
        "time_utc": "HH:MM or Unknown",
        "attacker": "Country or group",
        "target_country": "Country",
        "target_location": "City or region",
        "description": "One sentence factual description",
        "method": "Strike method from list above"
      }}
    ],
    "middle_east": [
      {{
        "time_utc": "HH:MM or Unknown",
        "attacker": "Country or group",
        "target_country": "Country",
        "target_location": "City or region",
        "description": "One sentence factual description",
        "method": "Strike method from list above"
      }}
    ]
  }},
  "casualties": {{
    "today": [
      {{
        "incident": "Short incident name",
        "kia": "Number or estimate",
        "wia": "Number or estimate",
        "civilian": true or false
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
    {{"time": "HH:MM UTC", "text": "What happened — one sentence per major event, most recent first"}}
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

    # Strip markdown fences if Claude adds them despite instructions
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]

    return json.loads(raw)

# ── STEP 3: MERGE WITH EXISTING DATA & SAVE ──────────────
def save_data(new_data):
    # Load existing file to preserve cumulative figures
    try:
        with open(OUTPUT_PATH, "r") as f:
            existing = json.load(f)
        cumulative = existing.get("casualties", {}).get("cumulative", {})
    except Exception:
        cumulative = {}

    new_data["last_updated"] = NOW
    new_data.setdefault("casualties", {})
    new_data["casualties"]["cumulative"] = cumulative  # preserve running totals

    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(new_data, f, indent=2)
    print(f"✓ war_data.json updated at {NOW}")
    print(f"  Strikes (EU): {len(new_data.get('strikes_today',{}).get('eastern_europe',[]))}")
    print(f"  Strikes (ME): {len(new_data.get('strikes_today',{}).get('middle_east',[]))}")
    print(f"  Ticker items: {len(new_data.get('ticker_items',[]))}")

# ── MAIN ─────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"── War Tracker Daily Update ── {TODAY} ──")
    print("Fetching headlines...")
    headlines = fetch_headlines()
    print(f"Got {len(headlines)} headlines")

    print("Asking Claude to structure data...")
    structured = ask_claude(headlines)

    print("Saving data...")
    save_data(structured)
    print("Done.")
