"""Load .env into os.environ. Same pattern as JUDGMENT/TOCSIN."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())
