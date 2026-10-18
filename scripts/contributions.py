"""Fetch, validate and merge the public contribution calendars.

The data layer behind render_sequencer.py, kept separate so the drawing code
never touches the network or unvalidated input.

Security posture:
  * Standard library only. Nothing is installed at run time, so there is no
    dependency to compromise.
  * The token is read from the environment, sent only to api.github.com over
    HTTPS, and never printed.
  * Every field of the response is validated before use. Anything unexpected
    raises, and no file is written. A failed run leaves yesterday's image in
    place instead of publishing a broken or empty one.
"""

import datetime as dt
import json
import os
import re
import tempfile
import urllib.request
from pathlib import Path

ACCOUNTS = ("jacob7choi-xyz", "jacobjax7choi")

API = "https://api.github.com/graphql"
MAX_BYTES = 2_000_000
MAX_DAILY = 50_000  # far above any real day; guards against garbage, not a quota
LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

QUERY = """query($login:String!){user(login:$login){contributionsCollection{
contributionCalendar{weeks{contributionDays{date contributionCount}}}}}}"""



class DataError(ValueError):
    pass


def fetch(login: str, token: str) -> dict:
    if not LOGIN_RE.fullmatch(login):
        raise DataError(f"invalid login: {login!r}")
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        method="POST",
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "jacob7choi-xyz-profile",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise DataError(f"HTTP {resp.status} for {login}")
        raw = resp.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise DataError("response too large")
    return json.loads(raw)


def parse_calendar(payload: dict, login: str) -> dict[dt.date, int]:
    """Validate one GraphQL response and return {date: count}."""
    if not isinstance(payload, dict) or payload.get("errors"):
        raise DataError(f"GraphQL errors for {login}")
    try:
        weeks = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    except (KeyError, TypeError):
        raise DataError(f"unexpected response shape for {login}") from None
    if not isinstance(weeks, list) or not 50 <= len(weeks) <= 54:
        raise DataError(f"unexpected week count for {login}")
    days: dict[dt.date, int] = {}
    for week in weeks:
        cdays = week.get("contributionDays") if isinstance(week, dict) else None
        if not isinstance(cdays, list):
            raise DataError(f"bad week for {login}")
        for day in cdays:
            date, count = (day.get("date"), day.get("contributionCount")) if isinstance(day, dict) else (None, None)
            if not isinstance(date, str) or not DATE_RE.fullmatch(date):
                raise DataError(f"bad date for {login}")
            # bool is a subclass of int; reject it explicitly.
            if type(count) is not int or not 0 <= count <= MAX_DAILY:
                raise DataError(f"bad count for {login}")
            d = dt.date.fromisoformat(date)
            if d in days:
                raise DataError(f"duplicate date for {login}")
            days[d] = count
    if not 350 <= len(days) <= 378:
        raise DataError(f"unexpected day count for {login}")
    return days


def merge(calendars: list[dict[dt.date, int]]) -> list[tuple[dt.date, int]]:
    """Sum per day across accounts over one contiguous date range."""
    start = min(min(c) for c in calendars)
    end = max(max(c) for c in calendars)
    out = []
    d = start
    while d <= end:
        out.append((d, sum(c.get(d, 0) for c in calendars)))
        d += dt.timedelta(days=1)
    return out


def write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".svg")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
