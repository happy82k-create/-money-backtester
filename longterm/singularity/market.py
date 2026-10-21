from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_PATH = DATA_DIR / "market_cache.json"
NY = ZoneInfo("America/New_York")
# 미국 정규장 마감. 조기 폐장일도 이 시각 이후에는 그날 종가가 확정돼 있다.
REGULAR_CLOSE = time(16, 0)

YAHOO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"


@dataclass
class Series:
    symbol: str
    points: list[tuple[date, float]]

    def as_map(self) -> dict[date, float]:
        return {d: v for d, v in self.points}


@dataclass
class MarketBundle:
    tqqq: Series
    qqq: Series
    vix: Series
    tnx: Series
    fear_greed: dict[date, float]
    fetched_at: str
    sources_ok: dict[str, bool]


def _request(url: str, headers: dict[str, str], timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def session_is_closed(day: date, now: datetime | None = None) -> bool:
    """그날 미국 정규장 16:00(뉴욕)이 지났으면 종가가 확정된 것이다."""
    now_ny = (now or datetime.now(NY)).astimezone(NY)
    close_at = datetime.combine(day, REGULAR_CLOSE, tzinfo=NY)
    return now_ny >= close_at


def drop_unclosed(points: list[tuple[date, float]], now: datetime | None = None) -> list[tuple[date, float]]:
    """아직 마감 전인 마지막 봉은 뺀다. 화면 숫자는 항상 확정 종가 기준이다."""
    if points and not session_is_closed(points[-1][0], now):
        return points[:-1]
    return points


def fetch_yahoo(symbol: str, rng: str = "5y") -> Series:
    encoded = urllib.parse.quote(symbol)
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{encoded}?interval=1d&range={rng}&includeAdjustedClose=true"
    )
    raw = json.loads(
        _request(
            url,
            {
                "User-Agent": YAHOO_UA,
                "Accept": "application/json",
            },
        ).decode()
    )
    result = raw["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    adj = result["indicators"].get("adjclose", [{}])[0].get("adjclose") or quote["close"]
    points: list[tuple[date, float]] = []
    seen: set[date] = set()
    for i, ts in enumerate(timestamps):
        close = adj[i]
        if close is None:
            continue
        day = datetime.fromtimestamp(ts, timezone.utc).date()
        if day in seen:
            points[-1] = (day, float(close))
            continue
        seen.add(day)
        points.append((day, float(close)))
    return Series(symbol=symbol, points=drop_unclosed(points))


def fetch_fear_greed() -> dict[date, float]:
    raw = json.loads(
        _request(
            CNN_URL,
            {
                "User-Agent": YAHOO_UA,
                "Accept": "application/json",
                "Referer": "https://edition.cnn.com/markets/fear-and-greed",
            },
        ).decode()
    )
    out: dict[date, float] = {}
    for item in raw.get("fear_and_greed_historical", {}).get("data", []):
        ts = item["x"] / 1000
        day = datetime.fromtimestamp(ts, timezone.utc).date()
        out[day] = float(item["y"])
    current = raw.get("fear_and_greed", {})
    stamp = current.get("timestamp")
    score = current.get("score")
    if stamp and score is not None:
        day = datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).date()
        out[day] = float(score)
    for day in [d for d in out if not session_is_closed(d)]:
        out.pop(day, None)
    return out


def _serialize_series(series: Series) -> dict:
    return {
        "symbol": series.symbol,
        "points": [[d.isoformat(), v] for d, v in series.points],
    }


def _deserialize_series(payload: dict) -> Series:
    return Series(
        symbol=payload["symbol"],
        points=[(date.fromisoformat(d), float(v)) for d, v in payload["points"]],
    )


def save_cache(bundle: MarketBundle) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": bundle.fetched_at,
        "sources_ok": bundle.sources_ok,
        "tqqq": _serialize_series(bundle.tqqq),
        "qqq": _serialize_series(bundle.qqq),
        "vix": _serialize_series(bundle.vix),
        "tnx": _serialize_series(bundle.tnx),
        "fear_greed": {d.isoformat(): v for d, v in bundle.fear_greed.items()},
    }
    CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")


def load_cache() -> MarketBundle | None:
    if not CACHE_PATH.exists():
        return None
    payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return MarketBundle(
        tqqq=_deserialize_series(payload["tqqq"]),
        qqq=_deserialize_series(payload["qqq"]),
        vix=_deserialize_series(payload["vix"]),
        tnx=_deserialize_series(payload["tnx"]),
        fear_greed={
            date.fromisoformat(k): float(v) for k, v in payload["fear_greed"].items()
        },
        fetched_at=payload["fetched_at"],
        sources_ok=payload.get("sources_ok", {}),
    )


def official_closes(bundle: MarketBundle, now: datetime | None = None) -> MarketBundle:
    """저장된 시세에서도 아직 마감 전인 봉은 빼고 보여 준다."""
    return MarketBundle(
        tqqq=Series(bundle.tqqq.symbol, drop_unclosed(bundle.tqqq.points, now)),
        qqq=Series(bundle.qqq.symbol, drop_unclosed(bundle.qqq.points, now)),
        vix=Series(bundle.vix.symbol, drop_unclosed(bundle.vix.points, now)),
        tnx=Series(bundle.tnx.symbol, drop_unclosed(bundle.tnx.points, now)),
        fear_greed={d: v for d, v in bundle.fear_greed.items() if session_is_closed(d, now)},
        fetched_at=bundle.fetched_at,
        sources_ok=bundle.sources_ok,
    )


def fetch_market(use_cache_on_error: bool = True) -> MarketBundle:
    errors: dict[str, str] = {}
    cached = load_cache() if use_cache_on_error else None

    def grab(symbol: str) -> Series:
        try:
            return fetch_yahoo(symbol)
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            errors[symbol] = str(exc)
            if cached is None:
                raise
            mapping = {
                "TQQQ": cached.tqqq,
                "QQQ": cached.qqq,
                "^VIX": cached.vix,
                "^TNX": cached.tnx,
            }
            return mapping[symbol]

    tqqq = grab("TQQQ")
    qqq = grab("QQQ")
    vix = grab("^VIX")
    tnx = grab("^TNX")

    try:
        fear_greed = fetch_fear_greed()
        fg_ok = True
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        errors["CNN"] = str(exc)
        fg_ok = False
        if cached is None:
            fear_greed = {}
        else:
            fear_greed = cached.fear_greed

    bundle = MarketBundle(
        tqqq=tqqq,
        qqq=qqq,
        vix=vix,
        tnx=tnx,
        fear_greed=fear_greed,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        sources_ok={
            "TQQQ": "TQQQ" not in errors,
            "QQQ": "QQQ" not in errors,
            "VIX": "^VIX" not in errors,
            "TNX": "^TNX" not in errors,
            "CNN": fg_ok,
        },
    )
    save_cache(bundle)
    return bundle
