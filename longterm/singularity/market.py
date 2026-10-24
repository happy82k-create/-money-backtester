from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from dataclasses import dataclass, field
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
# 날짜를 붙이면 2022년부터 온다. 2023년 1월 차트의 앞부분 계산에 필요하다.
CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2022-01-01"
CNBC_MARKET_URL = "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069"
MARKET_WORDS = (
    "nasdaq", "s&p", "dow", "wall street", "stock", "fed", "federal reserve",
    "treasury", "yield", "inflation", "cpi", "jobs", "payroll", "recession",
    "rally", "selloff", "sell-off", "plunge", "surge", "nvidia", "apple",
    "microsoft", "amazon", "meta", "tesla", "google", "alphabet", "chip",
    "semiconductor", "tariff", "oil", "crude", "earnings", "market cap", "market-cap",
)
QUIET_WORDS = (
    "mortgage", "refinance", "borrower", "renting", "retire", "401(k)",
    "credit card", "social security", "what it means for", "how to",
)


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
    spx: Series
    ixic: Series
    fear_greed: dict[date, float]
    fetched_at: str
    sources_ok: dict[str, bool]
    headlines: list = field(default_factory=list)


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
    del rng  # 차트는 2023년부터라, 이동평균이 가능하도록 2021년부터 고정해서 받는다.
    encoded = urllib.parse.quote(symbol)
    start = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp())
    end = int(datetime.now(timezone.utc).timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{encoded}?interval=1d&period1={start}&period2={end}&includeAdjustedClose=true"
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


def _series_from_cache(payload: dict, key: str, symbol: str) -> Series:
    raw = payload.get(key)
    if not raw:
        return Series(symbol, [])
    return _deserialize_series(raw)


def _headline_score(title: str) -> int:
    text = title.lower()
    score = sum(2 for word in MARKET_WORDS if word in text)
    score -= sum(3 for word in QUIET_WORDS if word in text)
    if re.match(r"i['’ ]|why i ", text) or " i " in f" {text}":
        score -= 10
    return score


def _one_korean_line(text: str) -> str:
    cleaned = html.unescape(text)
    replacements = {
        "마켓캡": "시가총액",
        "마켓 캡": "시가총액",
        "Apple": "애플",
        "Nvidia": "엔비디아",
        "Microsoft": "마이크로소프트",
        "Amazon": "아마존",
        "Google": "구글",
        "Tesla": "테슬라",
        "베어리쉬": "하락",
        "스톡": "주식",
    }
    for src, dst in replacements.items():
        cleaned = cleaned.replace(src, dst)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    parts = re.split(r"(?<=[.!?。])\s+", cleaned)
    line = parts[0].strip() if parts else cleaned
    return line[:120].rstrip()


def _translate_ko(title: str) -> str:
    query = urllib.parse.quote(html.unescape(title)[:280])
    url = f"https://api.mymemory.translated.net/get?q={query}&langpair=en|ko"
    raw = json.loads(_request(url, {"User-Agent": YAHOO_UA, "Accept": "application/json"}, timeout=20).decode())
    if raw.get("quotaFinished"):
        raise RuntimeError("번역 한도")
    text = raw.get("responseData", {}).get("translatedText") or ""
    line = _one_korean_line(text)
    if "treasur" in title.lower():
        line = line.replace("재무부", "미국 국채").replace("이주", "이동")
    if not line or line.lower() == html.unescape(title).lower():
        raise RuntimeError("번역 없음")
    return line


def fetch_headlines() -> list[dict]:
    """그날 CNBC 시장 제목 가운데 대표적인 3개를 한국어 한 줄로 만든다. 링크는 담지 않는다."""
    raw = _request(CNBC_MARKET_URL, {"User-Agent": YAHOO_UA, "Accept": "application/xml"}, timeout=20)
    root = ET.fromstring(raw)
    rows = []
    for order, item in enumerate(root.iter("item")):
        title = (item.findtext("title") or "").strip()
        stamp = item.findtext("pubDate")
        if not title or not stamp:
            continue
        published = parsedate_to_datetime(stamp).astimezone(NY)
        rows.append({
            "title": html.unescape(title),
            "day": published.date().isoformat(),
            "score": _headline_score(title),
            "order": order,
        })
    if not rows:
        return []
    latest = max(row["day"] for row in rows)
    day_rows = [row for row in rows if row["day"] == latest]
    day_rows.sort(key=lambda row: (-row["score"], row["order"]))
    picked = [row for row in day_rows if row["score"] >= 0][:3]
    for row in day_rows:
        if len(picked) >= 3:
            break
        if row not in picked:
            picked.append(row)
    lines = []
    for row in picked:
        try:
            text = _translate_ko(row["title"])
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError, RuntimeError):
            continue
        lines.append({"text": text, "source": "CNBC", "date": row["day"]})
    return lines[:3]


def save_cache(bundle: MarketBundle) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": bundle.fetched_at,
        "sources_ok": bundle.sources_ok,
        "tqqq": _serialize_series(bundle.tqqq),
        "qqq": _serialize_series(bundle.qqq),
        "vix": _serialize_series(bundle.vix),
        "tnx": _serialize_series(bundle.tnx),
        "spx": _serialize_series(bundle.spx),
        "ixic": _serialize_series(bundle.ixic),
        "fear_greed": {d.isoformat(): v for d, v in bundle.fear_greed.items()},
        "headlines": [
            {"text": item.get("text", ""), "source": "CNBC", "date": item.get("date", "")}
            for item in bundle.headlines
            if item.get("text")
        ],
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
        spx=_series_from_cache(payload, "spx", "^GSPC"),
        ixic=_series_from_cache(payload, "ixic", "^IXIC"),
        fear_greed={
            date.fromisoformat(k): float(v) for k, v in payload["fear_greed"].items()
        },
        fetched_at=payload["fetched_at"],
        sources_ok=payload.get("sources_ok", {}),
        headlines=[
            {"text": item.get("text", ""), "source": "CNBC", "date": item.get("date", "")}
            for item in payload.get("headlines", [])
            if isinstance(item, dict) and item.get("text")
        ],
    )


def official_closes(bundle: MarketBundle, now: datetime | None = None) -> MarketBundle:
    """저장된 시세에서도 아직 마감 전인 봉은 빼고 보여 준다."""
    return MarketBundle(
        tqqq=Series(bundle.tqqq.symbol, drop_unclosed(bundle.tqqq.points, now)),
        qqq=Series(bundle.qqq.symbol, drop_unclosed(bundle.qqq.points, now)),
        vix=Series(bundle.vix.symbol, drop_unclosed(bundle.vix.points, now)),
        tnx=Series(bundle.tnx.symbol, drop_unclosed(bundle.tnx.points, now)),
        spx=Series(bundle.spx.symbol, drop_unclosed(bundle.spx.points, now)),
        ixic=Series(bundle.ixic.symbol, drop_unclosed(bundle.ixic.points, now)),
        fear_greed={d: v for d, v in bundle.fear_greed.items() if session_is_closed(d, now)},
        fetched_at=bundle.fetched_at,
        sources_ok=bundle.sources_ok,
        headlines=list(bundle.headlines),
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
                "^GSPC": cached.spx,
                "^IXIC": cached.ixic,
            }
            return mapping[symbol]

    tqqq = grab("TQQQ")
    qqq = grab("QQQ")
    vix = grab("^VIX")
    tnx = grab("^TNX")
    spx = grab("^GSPC")
    ixic = grab("^IXIC")

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

    try:
        headlines = fetch_headlines()
        headlines_ok = len(headlines) >= 3
    except (urllib.error.URLError, TimeoutError, ET.ParseError, json.JSONDecodeError) as exc:
        errors["CNBC"] = str(exc)
        headlines_ok = False
        headlines = list(cached.headlines) if cached is not None else []
    if not headlines and cached is not None:
        headlines = list(cached.headlines)

    bundle = MarketBundle(
        tqqq=tqqq,
        qqq=qqq,
        vix=vix,
        tnx=tnx,
        spx=spx,
        ixic=ixic,
        fear_greed=fear_greed,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        sources_ok={
            "TQQQ": "TQQQ" not in errors,
            "QQQ": "QQQ" not in errors,
            "VIX": "^VIX" not in errors,
            "TNX": "^TNX" not in errors,
            "SPX": "^GSPC" not in errors,
            "IXIC": "^IXIC" not in errors,
            "CNN": fg_ok,
            "CNBC": headlines_ok,
        },
        headlines=headlines,
    )
    save_cache(bundle)
    return bundle
