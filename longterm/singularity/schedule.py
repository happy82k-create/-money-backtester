"""한국시간 매일 06:30에 미국 정규장 종가를 한 번 받는다.

공개 Streamlit은 접속이 없으면 프로세스가 잠든다. 그래서 6시 30분이 지난 뒤
처음 페이지가 열릴 때도 같은 규칙으로 받고, 서버가 켜져 있으면 그 시각에 직접 받는다.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from singularity.market import DATA_DIR, fetch_market, load_cache

SEOUL = ZoneInfo("Asia/Seoul")
REFRESH_HOUR = 6
REFRESH_MINUTE = 30
ATTEMPT_PATH = DATA_DIR / "refresh_attempt.json"
RETRY_MINUTES = 15

_lock = threading.Lock()
_started = False


def window_start(now: datetime | None = None) -> datetime:
    """지금 보여주고 있어야 할 종가의 갱신 시각. 당일 06:30 이전이면 어제 06:30."""
    now = (now or datetime.now(SEOUL)).astimezone(SEOUL)
    start = now.replace(hour=REFRESH_HOUR, minute=REFRESH_MINUTE, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    return start


def current_window_id(now: datetime | None = None) -> str:
    return window_start(now).strftime("%Y-%m-%d")


def _aware(stamp: str) -> datetime:
    parsed = datetime.fromisoformat(stamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def window_satisfied(fetched_at: str, sources_ok: dict | None, now: datetime | None = None) -> bool:
    """이번 06:30 구간에 TQQQ 종가를 이미 받았으면 다시 받지 않는다."""
    if not sources_ok or not sources_ok.get("TQQQ"):
        return False
    return _aware(fetched_at).astimezone(SEOUL) >= window_start(now)


def seconds_until_next_window(now: datetime | None = None) -> float:
    now = (now or datetime.now(SEOUL)).astimezone(SEOUL)
    nxt = window_start(now) + timedelta(days=1)
    return max(1.0, (nxt - now).total_seconds())


def _recent_attempt(now: datetime | None = None) -> bool:
    if not ATTEMPT_PATH.exists():
        return False
    try:
        raw = json.loads(ATTEMPT_PATH.read_text(encoding="utf-8"))
        stamp = _aware(raw["at"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return False
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return now - stamp.astimezone(timezone.utc) < timedelta(minutes=RETRY_MINUTES)


def _mark_attempt() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ATTEMPT_PATH.write_text(
        json.dumps({"at": datetime.now(timezone.utc).isoformat()}),
        encoding="utf-8",
    )


def indices_ready(bundle) -> bool:
    """1페이지 칸에 넣을 S&P 500과 나스닥 종가가 같이 저장돼 있어야 한다."""
    spx = getattr(bundle, "spx", None)
    ixic = getattr(bundle, "ixic", None)
    return bool(spx and spx.points and ixic and ixic.points)


def headlines_ready(bundle) -> bool:
    """그날 시장을 대표하는 한국어 기사 한 줄이 저장돼 있어야 한다."""
    lines = getattr(bundle, "headlines", None) or []
    return len(lines) >= 1


def covers_chart(bundle) -> bool:
    """2023년 1월 차트를 그리려면 그 이전 시세와 CNN 점수가 저장돼 있어야 한다."""
    if bundle is None or not bundle.tqqq.points or not bundle.fear_greed:
        return False
    return bundle.tqqq.points[0][0] <= date(2022, 3, 1) and min(bundle.fear_greed) <= date(2022, 12, 15)


def refresh_if_due() -> bool:
    """이번 06:30 구간에 아직 종가가 없거나 2023년 차트가 안 되면 받아 온다."""
    with _lock:
        cached = load_cache()
        ready = (
            cached is not None
            and window_satisfied(cached.fetched_at, cached.sources_ok)
            and covers_chart(cached)
            and indices_ready(cached)
            and headlines_ready(cached)
        )
        if ready or _recent_attempt():
            return False
        try:
            fetch_market(use_cache_on_error=True)
        except Exception:
            _mark_attempt()
            raise
        latest = load_cache()
        if latest is None or not (
            window_satisfied(latest.fetched_at, latest.sources_ok)
            and covers_chart(latest)
            and indices_ready(latest)
            and headlines_ready(latest)
        ):
            _mark_attempt()
        return True


def _loop() -> None:
    while True:
        try:
            refresh_if_due()
            cached = load_cache()
            ready = (
                cached is not None
                and window_satisfied(cached.fetched_at, cached.sources_ok)
                and covers_chart(cached)
                and indices_ready(cached)
                and headlines_ready(cached)
            )
        except Exception:
            ready = False
        delay = seconds_until_next_window() if ready else RETRY_MINUTES * 60
        time.sleep(max(30.0, delay))


def ensure_scheduler() -> None:
    """프로세스당 스레드 하나. Streamlit이 스크립트를 다시 실행해도 중복으로 켜지지 않는다."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="kst-close-refresh", daemon=True).start()
