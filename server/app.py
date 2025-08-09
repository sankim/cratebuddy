from flask import Flask, request, jsonify
from flask_cors import CORS
import os, re, time, json, sqlite3, hashlib
import requests
from bs4 import BeautifulSoup
from collections import defaultdict
import random

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": os.environ.get("ALLOW_ORIGIN", "*")}})

# Configuration from environment variables
DATA_DIR = os.environ.get("DATA_DIR", ".")
CACHE_DB = os.path.join(DATA_DIR, "cratebuddy_cache.sqlite3")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
BASE_DELAY = float(os.environ.get("BASE_DELAY", "2.0"))
REQUEST_GAP = float(os.environ.get("REQUEST_GAP", "0.8"))
TTL_TRALBUM = 60 * 60 * 24 * 7
TTL_COLLECTION = 60 * 60 * 24

# More realistic browser headers to avoid 403 errors
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
    "Referer": "https://bandcamp.com/"
}

# Multiple User-Agent strings to rotate through
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15"
]

def get_random_user_agent():
    """Get a random User-Agent string to avoid pattern detection"""
    return random.choice(USER_AGENTS)

# Create a session for persistent cookies and connection pooling
session = requests.Session()
session.headers.update(HEADERS)

WEIGHTS = {"copurchase": 0.6, "label_artist": 0.3, "tags": 0.1}
MAX_FANS = 25
MAX_FAN_PURCHASES = 40
MAX_SEED_ITEMS = 25

# Cache (SQLite KV)
def _db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB)
    conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, ts INTEGER NOT NULL)")
    return conn

def cache_get(key: str, ttl: int):
    conn = _db()
    cur = conn.execute("SELECT v, ts FROM kv WHERE k=?", (key,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    v, ts = row
    if int(time.time()) - int(ts) > ttl:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None

def cache_set(key: str, value):
    conn = _db()
    conn.execute("INSERT OR REPLACE INTO kv (k, v, ts) VALUES (?, ?, ?)", (key, json.dumps(value), int(time.time())))
    conn.commit()
    conn.close()

BC_FAN_RE = re.compile(r"https?://bandcamp\.com/([A-Za-z0-9_-]+)$")

def make_request_with_retry(url: str, max_retries: int = None, delay: float = None):
    """Make HTTP request with retry logic and better error handling"""
    if max_retries is None:
        max_retries = MAX_RETRIES
    if delay is None:
        delay = BASE_DELAY
        
    for attempt in range(max_retries):
        try:
            # Add some randomization to the delay to avoid pattern detection
            if attempt > 0:
                time.sleep(delay + (attempt * 0.5) + (random.random() * 1.0))
            
            # Use a random User-Agent for each request
            session.headers.update({"User-Agent": get_random_user_agent()})
            r = session.get(url, timeout=20)
            
            if r.status_code == 200:
                return r
            elif r.status_code == 403:
                # If we get blocked, wait longer and try again
                if attempt < max_retries - 1:
                    time.sleep(delay * (attempt + 1) * 2)
                    continue
                else:
                    raise RuntimeError(f"Access blocked by Bandcamp (403) after {max_retries} attempts")
            elif r.status_code == 429:
                # Rate limited, wait longer
                if attempt < max_retries - 1:
                    time.sleep(delay * (attempt + 1) * 3)
                    continue
                else:
                    raise RuntimeError(f"Rate limited by Bandcamp (429) after {max_retries} attempts")
            else:
                return r
                
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                continue
            else:
                raise RuntimeError(f"Request failed after {max_retries} attempts: {str(e)}")
    
    raise RuntimeError(f"Failed to fetch {url} after {max_retries} attempts")

def normalize_input(inp: str) -> str:
    inp = inp.strip()
    m = BC_FAN_RE.match(inp)
    if m: return m.group(1)
    return inp

def get_user_collection(username: str):
    cache_key = f"collection:{username}"
    cached = cache_get(cache_key, TTL_COLLECTION)
    if cached is not None:
        return cached

    url = f"https://bandcamp.com/{username}"
    r = make_request_with_retry(url)
    if r.status_code != 200:
        raise RuntimeError(f"User page not reachable: {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")

    out = []
    for a in soup.select("a.item, a.collection-item, .collection-item-container a"):
        href = a.get("href")
        if not href: continue
        if not href.startswith("http"):
            href = f"https://{username}.bandcamp.com{href}" if href.startswith("/") else f"https://bandcamp.com{href}"
        parsed = parse_tralbum(href)
        if parsed:
            out.append(parsed)
        if len(out) >= MAX_SEED_ITEMS: break
        time.sleep(REQUEST_GAP)

    dedup = {}
    for it in out:
        if not it or not it.get("url"): continue
        dedup[it["url"]] = it
    result = list(dedup.values())
    cache_set(cache_key, result)
    return result

def parse_tralbum(url: str):
    key = "tralbum:" + hashlib.sha1(url.encode()).hexdigest()
    cached = cache_get(key, TTL_TRALBUM)
    if cached is not None:
        return cached
    try:
        r = make_request_with_retry(url)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")

        title = soup.select_one("meta[property='og:title']")
        title = title.get("content") if title else (soup.select_one("#name-section .trackTitle") or {}).get("text", "").strip()
        artist = soup.select_one("#name-section .albumTitle span a, #name-section .artist, span[itemprop='byArtist'] a")
        artist = artist.get_text(strip=True) if artist else None
        label = None
        lab_el = soup.find("a", href=re.compile(r"/label/"))
        if lab_el: label = lab_el.get_text(strip=True)
        tags = [t.get_text(strip=True) for t in soup.select(".tralbum-tags a, .tag")][:12]

        fans = []
        for a in soup.select(".supported-by a[href^='https://bandcamp.com/']"):
            m = BC_FAN_RE.match(a.get("href"))
            if m: fans.append(m.group(1))
        fans = list(dict.fromkeys(fans))

        result = {"title": title or "", "artist": artist or "", "label": label, "tags": tags, "url": url, "fans": fans}
        cache_set(key, result)
        return result
    except Exception:
        return None

def crawl_supported_fans(seed_items):
    fan_usernames = []
    for it in seed_items:
        if not it or not it.get("url"): continue
        fans = it.get("fans")
        if fans is None:
            parsed = parse_tralbum(it["url"]) or {}
            fans = parsed.get("fans", [])
        fan_usernames.extend(fans[:MAX_FANS])
        time.sleep(REQUEST_GAP)
    seen = []
    for u in fan_usernames:
        if u not in seen:
            seen.append(u)
    return seen[:MAX_FANS]

def get_fan_purchases(usernames):
    purchases_by_fan = {}
    for u in usernames:
        try:
            purchases_by_fan[u] = get_user_collection(u)[:MAX_FAN_PURCHASES]
        except Exception:
            purchases_by_fan[u] = []
        time.sleep(REQUEST_GAP)
    return purchases_by_fan

def jaccard(a, b):
    sa, sb = set(a or []), set(b or [])
    if not sa or not sb: return 0.0
    return len(sa & sb) / len(sa | sb)

def recommend(input_username_or_url: str):
    username = normalize_input(input_username_or_url)
    seed_items = get_user_collection(username)
    if not seed_items:
        return []

    seed_urls = {it["url"] for it in seed_items if it.get("url")}
    seed_artists = {it.get("artist") for it in seed_items if it.get("artist")}
    seed_labels = {it.get("label") for it in seed_items if it.get("label")}
    seed_tags_flat = set(t for it in seed_items for t in (it.get("tags") or []))

    fans = crawl_supported_fans(seed_items)
    fan_purchases = get_fan_purchases(fans)

    candidates = {}
    copurchase_counts = defaultdict(int)

    for fan, items in fan_purchases.items():
        for it in items:
            if not it or not it.get("url"): continue
            url = it["url"]
            if url in seed_urls: continue
            cand = candidates.setdefault(url, {**it, "why": {"fans": set(), "seed_artists": set(), "seed_labels": set(), "tag_overlap": 0.0}})
            cand["why"]["fans"].add(fan)
            copurchase_counts[url] += 1

    for url, cand in candidates.items():
        if cand.get("artist") in seed_artists:
            cand["why"]["seed_artists"].add(cand.get("artist"))
        if cand.get("label") and cand.get("label") in seed_labels:
            cand["why"]["seed_labels"].add(cand.get("label"))
        cand["why"]["tag_overlap"] = jaccard(seed_tags_flat, cand.get("tags") or [])

    max_co = max(copurchase_counts.values()) if copurchase_counts else 1

    scored = []
    for url, cand in candidates.items():
        co_norm = (copurchase_counts[url] / max_co) if max_co else 0.0
        la = 1.0 if (cand["why"]["seed_artists"] or cand["why"]["seed_labels"]) else 0.0
        tg = cand["why"]["tag_overlap"]
        score = WEIGHTS["copurchase"] * co_norm + WEIGHTS["label_artist"] * la + WEIGHTS["tags"] * tg
        scored.append({
            "url": url,
            "title": cand.get("title"),
            "artist": cand.get("artist"),
            "label": cand.get("label"),
            "tags": cand.get("tags"),
            "breakdown": {"copurchase": WEIGHTS["copurchase"] * co_norm, "label_artist": WEIGHTS["label_artist"] * la, "tags": WEIGHTS["tags"] * tg},
            "raw": {"copurchase_count": copurchase_counts[url], "fans": sorted(list(cand["why"]["fans"]))[:8]},
            "total_score": score,
        })

    scored.sort(key=lambda x: x["total_score"], reverse=True)
    return scored[:40]

@app.route("/recommend", methods=["POST"])
def api_recommend():
    data = request.get_json(force=True)
    inp = (data.get("input") or "").strip()
    if not inp:
        return jsonify({"error": "Provide a Bandcamp username or fan page URL"}), 400
    try:
        recs = recommend(inp)
        return jsonify({"recommendations": recs})
    except RuntimeError as e:
        error_msg = str(e)
        if "403" in error_msg or "blocked" in error_msg.lower():
            return jsonify({"error": "Bandcamp is temporarily blocking our requests. Please try again in a few minutes."}), 429
        elif "429" in error_msg or "rate limited" in error_msg.lower():
            return jsonify({"error": "Too many requests. Please wait a moment and try again."}), 429
        else:
            return jsonify({"error": error_msg}), 500
    except Exception as e:
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "timestamp": int(time.time())})

@app.route("/test-scraping")
def test_scraping():
    """Test endpoint to debug scraping issues"""
    try:
        # Test with a simple, public Bandcamp page
        test_url = "https://bandcamp.com/"
        r = make_request_with_retry(test_url, max_retries=1)
        return jsonify({
            "status": "success",
            "status_code": r.status_code,
            "content_length": len(r.text),
            "headers": dict(r.headers)
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__
        }), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
