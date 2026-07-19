"""Shared pipeline helpers: HTTP with caching + throttling, YAML emit, slugs.

Family conventions: stdlib + PyYAML only. Every fetch caches to sources/ and is
idempotent (existing file = cache hit; force=True refetches). All requests carry a
project User-Agent and are throttled per host — SUCCURRO crawls many small nonprofit
sites and must be polite by default.
"""
import re
import time
import unicodedata
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"
DATA = ROOT / "data"

UA = "SUCCURRO-pipeline/0.1 (help-services directory; kara@soulstone.org)"

# minimum seconds between requests to the same host
THROTTLE = 1.0
_last_request: dict[str, float] = {}


def _host(url: str) -> str:
    return url.split("/", 3)[2]


# for the few sites whose WAF blocks non-browser clients outright; still throttled
BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
              "Firefox/128.0 (SUCCURRO-pipeline; kara@soulstone.org)")


def get(url: str, timeout: int = 120, ua: str = UA) -> bytes:
    """Throttled GET. Fails loud: a broken source should stop the run."""
    host = _host(url)
    wait = _last_request.get(host, 0) + THROTTLE - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request[host] = time.monotonic()
    try:
        with urlopen(Request(url, headers={"User-Agent": ua}), timeout=timeout) as resp:
            return resp.read()
    except (HTTPError, URLError, TimeoutError) as e:
        raise SystemExit(f"fetch failed: {url} ({e})")


def fetch(url: str, cache: Path, force: bool = False, ua: str = UA) -> Path:
    """Idempotent download: the file on disk is the cache."""
    if cache.exists() and not force:
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(get(url, ua=ua))
    print(f"fetched {url} -> {cache.relative_to(ROOT)}")
    return cache


def slugify(text: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:max_len].rstrip("-")


class Flow(dict):
    """Dict emitted in YAML flow style: geo: {lat: 1.0, lng: 2.0}."""


def _flow_representer(dumper, data):
    return dumper.represent_mapping("tag:yaml.org,2002:map", data, flow_style=True)


# use libyaml when available — the dataset is large enough for it to matter
_Dumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
yaml.SafeDumper.add_representer(Flow, _flow_representer)
if _Dumper is not yaml.SafeDumper:
    _Dumper.add_representer(Flow, _flow_representer)


def dump_yaml(records, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.dump(records, f, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)


def load_yaml(path: Path):
    with path.open() as f:
        return yaml.load(f, Loader=_Loader)
