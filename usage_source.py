"""Read Claude plan usage (same numbers as /usage) for the cube display.

Source order:
  1. GET https://api.anthropic.com/api/oauth/usage with Claude Code's OAuth token
     (read from the macOS Keychain item "Claude Code-credentials"; never stored or printed).
  2. Fallback: usage.json in this folder (a saved Claude Code statusline JSON, which carries
     rate_limits), if you have something that writes it.
"""
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"


def _token():
    out = subprocess.run(
        ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
        capture_output=True, text=True, timeout=10,
    )
    if out.returncode != 0:
        raise RuntimeError("keychain item 'Claude Code-credentials' not readable")
    return json.loads(out.stdout)["claudeAiOauth"]["accessToken"]


def _to_epoch(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()


def _norm(block):
    """-> {'pct': float, 'resets_at': epoch|None} from either API or statusline shape."""
    if not block:
        return None
    pct = block.get("utilization", block.get("used_percentage"))
    if pct is None:
        return None
    return {"pct": float(pct), "resets_at": _to_epoch(block.get("resets_at"))}


def from_api():
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": "Bearer " + _token(),
        "anthropic-beta": "oauth-2025-04-20",
        "Content-Type": "application/json",
        "User-Agent": "claudecube/1.0",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.load(r)
    return {"five_hour": _norm(d.get("five_hour")), "seven_day": _norm(d.get("seven_day")),
            "source": "api", "fetched_at": time.time()}


def from_statusline():
    p = os.path.join(HERE, "usage.json")
    d = json.load(open(p))["rate_limits"]
    return {"five_hour": _norm(d.get("five_hour")), "seven_day": _norm(d.get("seven_day")),
            "source": "statusline", "fetched_at": os.path.getmtime(p)}


def get_usage():
    try:
        return from_api()
    except Exception as e:
        if not os.path.exists(os.path.join(HERE, "usage.json")):
            raise RuntimeError(f"could not read Claude usage ({e}); is Claude Code logged in?") from None
        u = from_statusline()
        u["api_error"] = repr(e)
        return u


def _fmt_left(resets_at, now):
    if not resets_at:
        return ""
    s = max(0, int(resets_at - now))
    h, m = divmod(s // 60, 60)
    if h >= 24:
        return f"{h // 24}d{h % 24}h"
    return f"{h}h{m:02d}m" if h else f"{m}m"


def format_text(u, now=None):
    """Short line for the cube, e.g. 'Claude 5h 42% (1h20m) | 7d 18%'."""
    now = now or time.time()
    parts = []
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        b = u.get(key)
        if not b:
            continue
        pct = b["pct"]
        if b["resets_at"] and b["resets_at"] <= now:
            pct = 0.0  # window already reset since we last looked
        left = _fmt_left(b["resets_at"], now)
        parts.append(f"{label} {pct:.0f}%" + (f" ({left})" if left and key == "five_hour" else ""))
    return "Claude " + " | ".join(parts) if parts else "Claude usage n/a"


if __name__ == "__main__":
    u = get_usage()
    print(json.dumps({k: v for k, v in u.items()}, indent=1, default=str))
    print(format_text(u))
