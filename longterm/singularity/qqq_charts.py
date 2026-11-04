"""QQQ 실제 일봉과 헤이킨 아시. 매수·매도 도장은 그리지 않는다. 차트만 가볍게 따로 받는다."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from singularity.market import DATA_DIR, drop_open_days, fetch_daily_ohlc

BG = "#071018"
PANEL = "#0d1822"
CARD = "rgba(14, 28, 40, 0.96)"
LINE = "rgba(140, 196, 180, 0.16)"
TEXT = "#e7f2ee"
MUTED = "#8aa39a"
GOLD = "#e2c36b"
GREEN = "#5ec49a"
RISE = "#e23b3b"
FALL = "#3d8bfd"
SEOUL = ZoneInfo("Asia/Seoul")
QQQ_DAILY_PATH = DATA_DIR / "qqq_daily.json"
# 1년 화면 + 50일선 여유
KEEP_BARS = 320


def bars_frame(bars: list[tuple[date, float, float, float, float]]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close"])
    frame = pd.DataFrame(bars, columns=["date", "open", "high", "low", "close"])
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.sort_values("date").reset_index(drop=True)


def heikin_ashi(bars: pd.DataFrame) -> pd.DataFrame:
    frame = bars.sort_values("date").reset_index(drop=True).copy()
    if frame.empty:
        return frame
    open_ = frame["open"].to_numpy(dtype=float)
    high = frame["high"].to_numpy(dtype=float)
    low = frame["low"].to_numpy(dtype=float)
    close = frame["close"].to_numpy(dtype=float)
    count = len(frame)
    ha_close = (open_ + high + low + close) / 4.0
    ha_open = np.empty(count)
    ha_open[0] = (open_[0] + close[0]) / 2.0
    for index in range(1, count):
        ha_open[index] = (ha_open[index - 1] + ha_close[index - 1]) / 2.0
    frame["ha_open"] = ha_open
    frame["ha_high"] = np.maximum(np.maximum(high, ha_open), ha_close)
    frame["ha_low"] = np.minimum(np.minimum(low, ha_open), ha_close)
    frame["ha_close"] = ha_close
    return frame


def _window_start(now: datetime | None = None) -> datetime:
    now = (now or datetime.now(SEOUL)).astimezone(SEOUL)
    start = now.replace(hour=6, minute=30, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    return start


def _read_side_cache() -> tuple[list[tuple[date, float, float, float, float]], str | None]:
    if not QQQ_DAILY_PATH.exists():
        return [], None
    try:
        payload = json.loads(QQQ_DAILY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return [], None
    bars = [
        (date.fromisoformat(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]))
        for row in payload.get("bars", [])
    ]
    return drop_open_days(bars), payload.get("updated_at")


def _write_side_cache(bars: list[tuple[date, float, float, float, float]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    slim = bars[-KEEP_BARS:]
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_bar": slim[-1][0].isoformat() if slim else None,
        "bars": [[day.isoformat(), open_, high, low, close] for day, open_, high, low, close in slim],
    }
    QQQ_DAILY_PATH.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def _fresh(updated_at: str | None) -> bool:
    if not updated_at:
        return False
    try:
        stamped = datetime.fromisoformat(updated_at)
    except ValueError:
        return False
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    return stamped.astimezone(SEOUL) >= _window_start()


def load_qqq_chart_bars(force: bool = False) -> list[tuple[date, float, float, float, float]]:
    """차트용 QQQ 일봉. 아침 필수 갱신과 분리하고, 최근 봉만 짧게 저장한다."""
    cached, updated_at = _read_side_cache()
    if not force and cached and _fresh(updated_at):
        return cached[-KEEP_BARS:]
    try:
        bars = fetch_daily_ohlc("QQQ", months=18)
    except Exception:
        return cached[-KEEP_BARS:] if cached else []
    if not bars:
        return cached[-KEEP_BARS:] if cached else []
    slim = bars[-KEEP_BARS:]
    try:
        _write_side_cache(slim)
    except OSError:
        pass
    return slim


def build_chart(bars: list[tuple[date, float, float, float, float]], years: int = 1) -> go.Figure | None:
    frame = heikin_ashi(bars_frame(bars[-KEEP_BARS:]))
    if frame.empty:
        return None
    frame["ma20"] = frame["close"].rolling(20).mean()
    frame["ma50"] = frame["close"].rolling(50).mean()
    last = frame["date"].max()
    view = frame[frame["date"] >= last - pd.DateOffset(years=years)].reset_index(drop=True)
    if view.empty:
        return None
    x_value = pd.to_datetime(view["date"])
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.1,
        row_heights=[0.52, 0.48],
        subplot_titles=("QQQ 실제 일봉", "QQQ 헤이킨 아시"),
    )
    candle = dict(
        increasing_line_color=RISE,
        decreasing_line_color=FALL,
        increasing_fillcolor=RISE,
        decreasing_fillcolor=FALL,
        hovertemplate="%{x|%Y-%m-%d}<br>시가 %{open:.2f}<br>고가 %{high:.2f}<br>저가 %{low:.2f}<br>종가 %{close:.2f}<extra>%{fullData.name}</extra>",
    )
    figure.add_trace(
        go.Candlestick(
            x=x_value,
            open=view["open"],
            high=view["high"],
            low=view["low"],
            close=view["close"],
            name="실제",
            **candle,
        ),
        row=1,
        col=1,
    )
    for name, column, color, width in (
        ("20일", "ma20", GOLD, 2.0),
        ("50일", "ma50", GREEN, 1.8),
    ):
        figure.add_trace(
            go.Scatter(
                x=x_value,
                y=view[column],
                mode="lines",
                name=name,
                line={"color": color, "width": width},
                hovertemplate=f"%{{x|%Y-%m-%d}}<br>{name} %{{y:.2f}}<extra></extra>",
            ),
            row=1,
            col=1,
        )
    figure.add_trace(
        go.Candlestick(
            x=x_value,
            open=view["ha_open"],
            high=view["ha_high"],
            low=view["ha_low"],
            close=view["ha_close"],
            name="헤이킨 아시",
            **candle,
        ),
        row=2,
        col=1,
    )
    real_pad = max((float(view["high"].max()) - float(view["low"].min())) * 0.08, 1.0)
    ha_pad = max((float(view["ha_high"].max()) - float(view["ha_low"].min())) * 0.08, 1.0)
    axis = {
        "showspikes": False,
        "gridcolor": LINE,
        "zeroline": False,
        "color": MUTED,
        "tickfont": {"color": MUTED, "size": 12},
        "title": {"font": {"color": MUTED, "size": 12}},
        "showline": True,
        "linecolor": LINE,
        "mirror": False,
    }
    figure.update_yaxes(
        range=[float(view["low"].min()) - real_pad, float(view["high"].max()) + real_pad],
        autorange=False,
        fixedrange=True,
        title_text="실제 가격",
        row=1,
        col=1,
        **axis,
    )
    figure.update_yaxes(
        range=[float(view["ha_low"].min()) - ha_pad, float(view["ha_high"].max()) + ha_pad],
        autorange=False,
        fixedrange=True,
        title_text="헤이킨 아시",
        row=2,
        col=1,
        **axis,
    )
    for row in (1, 2):
        figure.update_xaxes(
            rangeslider_visible=False,
            rangebreaks=[{"bounds": ["sat", "mon"]}],
            title_text="날짜" if row == 2 else None,
            row=row,
            col=1,
            **axis,
        )
    figure.update_layout(
        margin={"l": 58, "r": 16, "t": 56, "b": 40},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.04,
            "x": 0,
            "font": {"color": TEXT, "size": 13},
            "bgcolor": "rgba(0,0,0,0)",
            "borderwidth": 0,
        },
        hovermode="closest",
        dragmode="pan",
        font={"family": "IBM Plex Sans KR, Malgun Gothic, sans-serif", "color": TEXT},
        paper_bgcolor=PANEL,
        plot_bgcolor=BG,
        height=640,
        uirevision="qqq-ha-light",
        hoverlabel={
            "font": {"family": "IBM Plex Sans KR, Malgun Gothic, sans-serif", "size": 13, "color": TEXT},
            "bgcolor": CARD,
            "bordercolor": GOLD,
        },
    )
    figure.update_annotations(font={"color": GOLD, "size": 14})
    return figure


def last_bar_label(bars: list[tuple[date, float, float, float, float]]) -> str:
    if not bars:
        return ""
    return bars[-1][0].isoformat()
