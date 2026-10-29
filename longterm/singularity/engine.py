from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from singularity.formula import (
    ComponentScore,
    MA200_PERIOD,
    RATE_DROP,
    RATE_LOOKBACK,
    RATE_SMA_PERIOD,
    VIX_SMA_PERIOD,
    WEIGHTS,
    cutler_rsi,
    drawdown_cell,
    fear_greed_cell,
    ma200_cell,
    rsi_cell,
    total_score,
    vix_cell,
)
from singularity.market import MarketBundle, session_is_closed, week_friday

SEOUL = ZoneInfo("Asia/Seoul")
NY = ZoneInfo("America/New_York")

COMPONENT_META = [
    ("drawdown", "고점 대비 하락"),
    ("weekly_rsi", "주간 RSI"),
    ("vix", "VIX"),
    ("ma200", "200일선"),
    ("daily_rsi", "일간 RSI"),
    ("fear_greed", "공포탐욕"),
]


@dataclass
class RateState:
    yield_10y: float
    high_3m: float
    sma50: float
    drop_from_high: float
    broken: bool


@dataclass
class DaySnapshot:
    date: str
    score: float
    tqqq: float
    ytd_high: float
    drawdown_pct: float
    sma200: float
    ma_gap_pct: float
    daily_rsi: float
    weekly_rsi: float
    vix: float
    vix_sma50: float
    vix_ratio: float
    fear_greed: float
    qqq: float | None
    qqq_drawdown_pct: float | None
    cells: dict[str, float]
    rate: RateState
    components: list[ComponentScore]


def _lookup(series_map: dict[date, float], day: date) -> float | None:
    if day in series_map:
        return series_map[day]
    prev = [series_map[d] for d in sorted(series_map) if d <= day]
    return prev[-1] if prev else None


def _ytd_high(points: list[tuple[date, float]], index: int) -> float:
    year = points[index][0].year
    high = None
    for j in range(index + 1):
        if points[j][0].year == year:
            high = points[j][1] if high is None else max(high, points[j][1])
    return high or points[index][1]


def _weekly_closes(points: list[tuple[date, float]]) -> list[float]:
    by_week: dict[int, float] = {}
    order: list[int] = []
    for day, close in points:
        key = day.toordinal() - day.weekday()
        if key not in by_week:
            order.append(key)
        by_week[key] = close
    return [by_week[key] for key in order]


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _rate_state(tnx_map: dict[date, float], day: date, dates: list[date]) -> RateState | None:
    available = [d for d in dates if d <= day and d in tnx_map]
    if len(available) < RATE_LOOKBACK:
        return None
    values = [tnx_map[d] for d in available]
    current = values[-1]
    high_3m = max(values[-RATE_LOOKBACK:])
    sma50 = _sma(values, RATE_SMA_PERIOD)
    if sma50 is None:
        return None
    return RateState(
        yield_10y=current,
        high_3m=high_3m,
        sma50=sma50,
        drop_from_high=high_3m - current,
        broken=current <= high_3m - RATE_DROP and current < sma50,
    )


def _zone(score: float) -> dict:
    if score >= 90:
        return {
            "key": "buy",
            "label": "90점대 · 대형 웅덩이",
            "hint": "큰 위기의 바닥 근처로 보는 구간입니다. 영상 원칙은 첫날 바로 사지 않고 3~5거래일을 기다립니다.",
        }
    if score >= 80:
        return {
            "key": "event",
            "label": "80점대 · 중형 웅덩이",
            "hint": "실제 사건이 터진 조정에 가깝습니다. 90점과 금리 꺾임을 함께 보는 편이 보수적입니다.",
        }
    if score >= 70:
        return {
            "key": "worry",
            "label": "70점대 · 소형 웅덩이",
            "hint": "며칠 급락으로 빠른 칸만 찬 상태일 수 있습니다. 느린 칸(주간 RSI, 200일선)을 확인하세요.",
        }
    return {
        "key": "wait",
        "label": "관망",
        "hint": "아직 매수신호 구간이 아닙니다.",
    }


def _components(snap: DaySnapshot) -> list[ComponentScore]:
    raw = {
        "drawdown": (
            snap.drawdown_pct,
            f"올해 고점 ${snap.ytd_high:.2f} 대비 {snap.drawdown_pct:.1f}%",
        ),
        "weekly_rsi": (snap.weekly_rsi, f"주봉 14주 RSI {snap.weekly_rsi:.1f}"),
        "vix": (
            snap.vix_ratio,
            f"VIX {snap.vix:.2f} / 50일평균 {snap.vix_sma50:.2f} = {snap.vix_ratio:.2f}배",
        ),
        "ma200": (
            snap.ma_gap_pct,
            f"200일선 ${snap.sma200:.2f} 대비 {snap.ma_gap_pct:+.1f}%",
        ),
        "daily_rsi": (snap.daily_rsi, f"일봉 14일 RSI {snap.daily_rsi:.1f}"),
        "fear_greed": (snap.fear_greed, f"CNN {snap.fear_greed:.1f} → 칸 {100 - snap.fear_greed:.1f}"),
    }
    items: list[ComponentScore] = []
    for key, label in COMPONENT_META:
        value, detail = raw[key]
        items.append(
            ComponentScore(
                key=key,
                label=label,
                weight=WEIGHTS[key],
                cell=snap.cells[key],
                raw_label=detail,
                raw_value=value,
                detail=detail,
            )
        )
    return items


def compute_history(bundle: MarketBundle) -> list[DaySnapshot]:
    tqqq = bundle.tqqq.points
    qqq_map = bundle.qqq.as_map()
    vix_map = bundle.vix.as_map()
    tnx_map = bundle.tnx.as_map()
    fg_map = bundle.fear_greed
    dates = [d for d, _ in tqqq]
    closes = [c for _, c in tqqq]
    qqq_points = bundle.qqq.points

    history: list[DaySnapshot] = []
    for i, (day, price) in enumerate(tqqq):
        if i < MA200_PERIOD:
            continue
        vix = _lookup(vix_map, day)
        fg = _lookup(fg_map, day)
        if vix is None or fg is None:
            continue
        vix_dates = [d for d in dates if d <= day and d in vix_map]
        if len(vix_dates) < VIX_SMA_PERIOD:
            continue
        vix_closes = [vix_map[d] for d in vix_dates]
        vix_sma = _sma(vix_closes, VIX_SMA_PERIOD)
        sma200 = _sma(closes[: i + 1], MA200_PERIOD)
        daily_rsi = cutler_rsi(closes[: i + 1])
        weekly_rsi = cutler_rsi(_weekly_closes(tqqq[: i + 1]))
        if vix_sma is None or sma200 is None or daily_rsi is None or weekly_rsi is None:
            continue
        rate = _rate_state(tnx_map, day, dates)
        if rate is None:
            continue

        high = _ytd_high(tqqq, i)
        qqq = _lookup(qqq_map, day)
        qqq_dd = None
        if qqq is not None:
            q_high = None
            for d0, c0 in qqq_points:
                if d0.year == day.year and d0 <= day:
                    q_high = c0 if q_high is None else max(q_high, c0)
            if q_high:
                qqq_dd = (q_high - qqq) / q_high * 100.0

        cells = {
            "drawdown": drawdown_cell(price, high),
            "weekly_rsi": rsi_cell(weekly_rsi) or 0.0,
            "vix": vix_cell(vix, vix_sma),
            "ma200": ma200_cell(price, sma200),
            "daily_rsi": rsi_cell(daily_rsi) or 0.0,
            "fear_greed": fear_greed_cell(fg),
        }
        snap = DaySnapshot(
            date=day.isoformat(),
            score=total_score(cells),
            tqqq=price,
            ytd_high=high,
            drawdown_pct=(high - price) / high * 100.0,
            sma200=sma200,
            ma_gap_pct=(price / sma200 - 1.0) * 100.0,
            daily_rsi=daily_rsi,
            weekly_rsi=weekly_rsi,
            vix=vix,
            vix_sma50=vix_sma,
            vix_ratio=vix / vix_sma,
            fear_greed=fg,
            qqq=qqq,
            qqq_drawdown_pct=qqq_dd,
            cells=cells,
            rate=rate,
            components=[],
        )
        snap.components = _components(snap)
        history.append(snap)
    return history


def _first_cross_events(history: list[DaySnapshot], threshold: float) -> list[dict]:
    events = []
    prev = 0.0
    for snap in history:
        if snap.score >= threshold and prev < threshold:
            events.append(
                {
                    "date": snap.date,
                    "score": round(snap.score, 1),
                    "tqqq": round(snap.tqqq, 2),
                    "threshold": threshold,
                }
            )
        prev = snap.score
    return events[-12:]


def _wait_status(history: list[DaySnapshot]) -> dict | None:
    if not history:
        return None
    latest = history[-1]
    if latest.score < 90:
        recent = [s for s in history[-10:] if s.score >= 90]
        if not recent:
            return None
        return {
            "active": False,
            "label": "최근 10거래일 안에 90점을 찍은 적 있음",
            "days": 0,
        }
    start = None
    for snap in reversed(history):
        if snap.score >= 90:
            start = snap.date
        else:
            break
    if start is None:
        return None
    start_day = date.fromisoformat(start)
    days = sum(1 for s in history if date.fromisoformat(s.date) >= start_day)
    return {
        "active": True,
        "since": start,
        "days": days,
        "label": f"90점 구간 {days}거래일째. 영상 원칙은 3~5거래일 후 분할 매수.",
        "ready": days >= 3,
    }


def _pct_change(series) -> dict | None:
    if len(series.points) < 2:
        return None
    prev_day, prev = series.points[-2]
    day, curr = series.points[-1]
    if prev == 0:
        return None
    return {"date": day.isoformat(), "prev": prev, "curr": curr, "pct": (curr / prev - 1) * 100}


def _index_clause(name: str, pct: float, final: bool, with_prev: bool = True) -> str:
    ending = "다" if final else "고"
    if abs(pct) < 0.05:
        return f"{name}은 전날과 거의 같았{ending}"
    verb = "올랐" if pct > 0 else "내렸"
    base = "전날보다 " if with_prev else ""
    return f"{name}은 {base}{abs(pct):.1f}% {verb}{ending}"


def _level_clause(name: str, prev: float, curr: float, digits: int, suffix: str, final: bool, flat: float) -> str:
    ending = "다" if final else "고"
    if abs(curr - prev) < flat:
        return f"{name} {curr:.{digits}f}{suffix}로 거의 그대로였{ending}"
    verb = "올랐" if curr > prev else "내렸"
    return f"{name} {prev:.{digits}f}{suffix}에서 {curr:.{digits}f}{suffix}로 {verb}{ending}"


def _market_brief(bundle: MarketBundle) -> dict:
    """지수 결과, 대표 기사 한 줄, 금리·공포 배경을 이어서 보여 준다."""
    lines: list[dict] = []
    spx = _pct_change(bundle.spx)
    nasdaq = _pct_change(bundle.ixic)
    when = ""
    if nasdaq and spx:
        when = nasdaq["date"]
        lines.append({
            "text": f"{_index_clause('나스닥', nasdaq['pct'], False)}, {_index_clause('S&P 500', spx['pct'], True, False)}.",
            "source": "",
        })
    story = next((item.get("text", "") for item in bundle.headlines if item.get("text")), "")
    if story:
        lines.append({
            "text": f"이날 가장 크게 다뤄진 이야기는, {story}",
            "source": "CNBC",
        })
    backdrop = []
    vix = _pct_change(bundle.vix)
    rate = _pct_change(bundle.tnx)
    if vix:
        backdrop.append(_level_clause("공포지수 VIX는", vix["prev"], vix["curr"], 1, "", False, 0.05))
    if rate:
        backdrop.append(_level_clause("미국 10년물 금리는", rate["prev"], rate["curr"], 2, "%", True, 0.01))
    if len(backdrop) == 1:
        backdrop[0] = backdrop[0][:-1] + "다"
    if backdrop:
        lines.append({"text": ", ".join(backdrop) + ".", "source": ""})
    return {"date": when, "lines": lines}


def _weekly_cci(bars: list[tuple]) -> list[float | None]:
    """주봉 CCI 30. 대표값의 30주 평균에서 얼마나 떨어졌는지다."""
    period = 30
    typical = [(bar[2] + bar[3] + bar[4]) / 3 for bar in bars]
    values: list[float | None] = []
    for index in range(len(bars)):
        if index + 1 < period:
            values.append(None)
            continue
        window = typical[index + 1 - period : index + 1]
        average = sum(window) / period
        deviation = sum(abs(price - average) for price in window) / period
        values.append(None if deviation == 0 else (typical[index] - average) / (0.015 * deviation))
    return values


def _weekly_trend(bundle: MarketBundle) -> list[dict]:
    """QQQ와 SOXX의 최근 30주. 방향은 마지막 확정 주봉 CCI가 0 이상이면 상승이다."""
    cards = []
    for symbol in ("QQQ", "SOXX"):
        bars = list(bundle.weekly.get(symbol, []))
        paired = [
            (bar, value)
            for bar, value in zip(bars, _weekly_cci(bars))
            if value is not None
        ]
        if len(paired) < 30:
            continue
        shown = paired[-30:]
        last_bar, last_value = shown[-1]
        last_cci = int(round(last_value))
        friday = week_friday(last_bar[0])
        weeks = []
        for bar, value in shown:
            ended = week_friday(bar[0])
            weeks.append({
                "label": f"{ended.month}/{ended.day}",
                "open": round(bar[1], 2),
                "high": round(bar[2], 2),
                "low": round(bar[3], 2),
                "close": round(bar[4], 2),
                "cci": int(round(value)),
            })
        cards.append({
            "symbol": symbol,
            "direction": "up" if last_cci >= 0 else "down",
            "close": round(last_bar[4], 2),
            "cci": last_cci,
            "as_of_label": f"{friday.month}월 {friday.day}일 주봉",
            "weeks": weeks,
        })
    return cards


def _index_quote(series) -> dict | None:
    """그 지수의 마지막 확정 종가. 날짜는 칸에 그대로 적는다."""
    if not series.points:
        return None
    d, value = series.points[-1]
    return {"value": round(value, 2), "date": d.isoformat()}


def build_payload(bundle: MarketBundle) -> dict:
    history = compute_history(bundle)
    if not history:
        raise RuntimeError("점수를 계산할 시계열이 부족합니다.")
    latest = history[-1]
    today_ny = datetime.now(NY).date()
    last_day = date.fromisoformat(latest.date)
    # 뉴욕 날짜가 같아도 정규장 16:00이 지났으면 종가다.
    # 한국시간 아침 6시 30분은 뉴욕이 전날 저녁이라, 날짜만 보면 장중으로 잘못 나온다.
    is_intraday = last_day == today_ny and not session_is_closed(last_day)
    prev = history[-2] if len(history) >= 2 else None
    payload = {
        "as_of": latest.date,
        "as_of_label": f"{latest.date} {'장중' if is_intraday else '종가'}",
        "is_intraday": is_intraday,
        "fetched_at": bundle.fetched_at,
        "fetched_at_kst": datetime.fromisoformat(bundle.fetched_at).astimezone(SEOUL).strftime(
            "%Y-%m-%d %H:%M KST"
        ),
        "sources_ok": bundle.sources_ok,
        "score": round(latest.score, 1),
        "score_int": int(round(latest.score)),
        "prev_score": round(prev.score, 1) if prev else None,
        "score_delta": round(latest.score - prev.score, 1) if prev else None,
        "zone": _zone(latest.score),
        "tqqq": round(latest.tqqq, 2),
        "spx": _index_quote(bundle.spx),
        "nasdaq": _index_quote(bundle.ixic),
        "market_brief": _market_brief(bundle),
        "weekly_trend": _weekly_trend(bundle),
        "qqq": round(latest.qqq, 2) if latest.qqq is not None else None,
        "qqq_drawdown_pct": round(latest.qqq_drawdown_pct, 1)
        if latest.qqq_drawdown_pct is not None
        else None,
        "cells": {k: round(v, 1) for k, v in latest.cells.items()},
        "components": [asdict(c) | {"contribution": round(c.contribution, 1)} for c in latest.components],
        "raw": {
            "ytd_high": round(latest.ytd_high, 2),
            "drawdown_pct": round(latest.drawdown_pct, 1),
            "sma200": round(latest.sma200, 2),
            "ma_gap_pct": round(latest.ma_gap_pct, 1),
            "daily_rsi": round(latest.daily_rsi, 1),
            "weekly_rsi": round(latest.weekly_rsi, 1),
            "vix": round(latest.vix, 2),
            "vix_sma50": round(latest.vix_sma50, 2),
            "vix_ratio": round(latest.vix_ratio, 2),
            "fear_greed": round(latest.fear_greed, 1),
        },
        "rate": asdict(latest.rate),
        "wait": _wait_status(history),
        "events_90": _first_cross_events(history, 90),
        "events_80": _first_cross_events(history, 80),
        "history": [
            {
                "date": s.date,
                "score": round(s.score, 1),
                "tqqq": round(s.tqqq, 2),
                "cells": {k: round(v, 1) for k, v in s.cells.items()},
            }
            for s in history
        ],
        "disclaimer": (
            "테스프레소 영상 설명을 재구성한 학습용 점수입니다. "
            "RSI 0점(70)은 영상에 명시되지 않아 추정했습니다. 투자 조언이 아닙니다."
        ),
        "formula_note": (
            "가중치: 하락률 30%, 주간 RSI 20%, VIX 15%, 200일선 15%, "
            "일간 RSI 10%, CNN 공포탐욕 10%."
        ),
    }
    payload["rate"]["yield_10y"] = round(payload["rate"]["yield_10y"], 3)
    payload["rate"]["high_3m"] = round(payload["rate"]["high_3m"], 3)
    payload["rate"]["sma50"] = round(payload["rate"]["sma50"], 3)
    payload["rate"]["drop_from_high"] = round(payload["rate"]["drop_from_high"], 3)
    return payload
