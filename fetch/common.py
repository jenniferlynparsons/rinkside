"""Shared helpers: polite HTTP, time conversion, name matching."""
import gzip
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Say who we are, with a link back, the way well-behaved crawlers do.
_REPO = os.environ.get("GITHUB_REPOSITORY", "")
UA = "Mozilla/5.0 (compatible; Rinkside/1.0; personal hockey schedule site" + \
     (f"; +https://github.com/{_REPO})" if _REPO else ")")
ET = ZoneInfo("America/New_York")

STANDINGS_COLUMNS = [{"key": k, "label": k.upper()} for k in ("gp", "pts", "w", "otw", "otl", "l", "gf", "ga")]
SKATER_COLUMNS = [{"key": k, "label": l} for k, l in
                  [("gp", "GP"), ("g", "G"), ("a", "A"), ("pts", "PTS"), ("pm", "+/-"), ("pim", "PIM"), ("sog", "SOG")]]


def http_get(url, *, params=None, tries=3, timeout=30, as_json=False):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/json" if as_json else "text/html,*/*",
                "Accept-Encoding": "gzip",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                text = body.decode(r.headers.get_content_charset() or "utf-8", "replace")
            if as_json:
                text = text.strip()
                if text.startswith("(") and text.endswith(")"):  # JSONP-ish
                    text = text[1:-1]
                return json.loads(text)
            return text
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last = e
            if isinstance(e, urllib.error.HTTPError) and e.code in (403, 404):
                break  # retrying will not help
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET failed: {url.split('?')[0]} ({last})")


def iso_utc(dt):
    """Aware datetime -> 'YYYY-MM-DDTHH:MM:SSZ'."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc():
    return datetime.now(timezone.utc)


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def norm_name(s):
    """Lowercase, accent-free, letters only — for matching player names
    that are written differently on different pages."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z ]", "", s.lower().replace("-", " ").replace("'", ""))
    return " ".join(s.split())


def last_first_to_first_last(s):
    """'Collins, Catie' -> 'Catie Collins'."""
    if "," in s:
        last, first = [p.strip() for p in s.split(",", 1)]
        return f"{first} {last}".strip()
    return s.strip()


def caps_name(s):
    """IIHF style 'McNAUGHTON Ava' / 'DE SOUZA Lia' -> 'Ava McNaughton' / 'Lia De Souza'."""
    toks = s.split()
    lasts, firsts = [], []
    for t in toks:
        core = re.sub(r"^Mc", "MC", t)
        if not firsts and core.upper() == core and any(ch.isalpha() for ch in core):
            lasts.append(t)
        else:
            firsts.append(t)
    if not lasts or not firsts:
        return s

    def fix(t):
        if t.startswith("Mc") and len(t) > 2:
            return "Mc" + t[2:].capitalize()
        return "-".join(p.capitalize() for p in t.split("-"))
    return " ".join(firsts + [fix(t) for t in lasts])


def to_int(s, default=None):
    try:
        return int(str(s).strip().lstrip("+"))
    except (ValueError, TypeError):
        try:
            return int(float(str(s).strip()))
        except (ValueError, TypeError):
            return default


def num(s):
    """Keep stats as numbers where they are numbers, text otherwise."""
    s = (s or "").strip()
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return s  # decimals (".974", "2.47") stay as written
