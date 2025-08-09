from flask import Flask, request, jsonify
from flask_cors import CORS
import os, re, time, json, sqlite3, hashlib
import requests
from bs4 import BeautifulSoup
from collections import defaultdict

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": os.environ.get("ALLOW_ORIGIN", "*")}})

DATA_DIR = os.environ.get("DATA_DIR", ".")
CACHE_DB = os.path.join(DATA_DIR, "cratebuddy_cache.sqlite3")
HEADERS = {"User-Agent": "Mozilla/5.0 (Cratebuddy/1.0; +https://cratebuddy.example)"}
WEIGHTS = {"copurchase": 0.6, "label_artist": 0.3, "tags": 0.1}
MAX_FANS = 25
MAX_FAN_PURCHASES = 40
MAX_SEED_ITEMS = 25
REQUEST_GAP = 0.8
TTL_TRALBUM = 60 * 60 * 24 * 7
TTL_COLLECTION = 60 * 60 * 24

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
    r = requests.get(url, headers=HEADERS, timeout=20)
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
        r = requests.get(url, headers=HEADERS, timeout=20)
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
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/healthz")
def healthz():
    return {"ok": True}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
