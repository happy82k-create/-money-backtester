"""QQQ 실제 일봉과 헤이킨 아시. 매수·매도 도장은 그리지 않는다."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

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


def _fmt(value: float) -> str:
    return f"{float(value):,.2f}"


def build_chart(bars: list[tuple[date, float, float, float, float]], years: int = 1) -> go.Figure | None:
    frame = heikin_ashi(bars_frame(bars))
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
    figure.add_trace(
        go.Candlestick(
            x=x_value,
            open=view["open"],
            high=view["high"],
            low=view["low"],
            close=view["close"],
            name="실제",
            increasing_line_color=RISE,
            decreasing_line_color=FALL,
            increasing_fillcolor=RISE,
            decreasing_fillcolor=FALL,
            hoverinfo="text",
            hovertext=[
                f"{pd.Timestamp(day).strftime('%Y-%m-%d')} 실제<br>"
                f"시가 {_fmt(row.open)} 고가 {_fmt(row.high)}<br>"
                f"저가 {_fmt(row.low)} 종가 {_fmt(row.close)}"
                for day, row in zip(view["date"], view.itertuples(index=False))
            ],
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
                hoverinfo="text",
                hovertext=[
                    f"{pd.Timestamp(day).strftime('%Y-%m-%d')} {name} {_fmt(value)}"
                    for day, value in zip(view["date"], view[column])
                ],
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
            increasing_line_color=RISE,
            decreasing_line_color=FALL,
            increasing_fillcolor=RISE,
            decreasing_fillcolor=FALL,
            hoverinfo="text",
            hovertext=[
                f"{pd.Timestamp(day).strftime('%Y-%m-%d')} 헤이킨 아시<br>"
                f"시가 {_fmt(row.ha_open)} 고가 {_fmt(row.ha_high)}<br>"
                f"저가 {_fmt(row.ha_low)} 종가 {_fmt(row.ha_close)}"
                for day, row in zip(view["date"], view.itertuples(index=False))
            ],
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
        height=760,
        uirevision="qqq-ha-dark",
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
