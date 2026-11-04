"""TQQQ 웅덩이 매수 신호. 8080 화면을 이 앱 1페이지로 넣는다."""
import json
import sys
from pathlib import Path

import streamlit as st

from ui_menu import top_menu

ROOT = Path(__file__).resolve().parents[1]
LONG = ROOT / "longterm"
sys.path.insert(0, str(LONG))

from singularity.engine import build_payload  # noqa: E402
from singularity.market import load_cache, official_closes  # noqa: E402
from singularity.qqq_charts import build_chart, last_bar_label  # noqa: E402
from singularity.schedule import current_window_id, refresh_if_due, window_satisfied  # noqa: E402

STATIC = LONG / "static"


@st.cache_data(show_spinner="미국 종가를 확인하고 있습니다")
def _fresh_snapshot(window_id: str) -> dict:
    """이번 06:30 구간에 종가를 받은 뒤에만 캐시한다. 실패는 캐시하지 않는다."""
    refresh_if_due()
    bundle = load_cache()
    if bundle is None or not window_satisfied(bundle.fetched_at, bundle.sources_ok):
        raise RuntimeError("이번 아침 종가가 아직 없습니다.")
    payload = build_payload(official_closes(bundle))
    payload["stale"] = False
    payload["window_id"] = window_id
    return payload


def load_snapshot() -> dict:
    """한국시간 06:30 기준 미국 종가. 화면의 버튼으로는 다시 받지 않는다."""
    try:
        return _fresh_snapshot(current_window_id())
    except Exception:
        bundle = load_cache()
        if bundle is None:
            raise
        payload = build_payload(official_closes(bundle))
        payload["stale"] = True
        return payload


def dashboard_html(payload: dict) -> str:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    body = index.split("<body>", 1)[1].rsplit("</body>", 1)[0]
    body = body.replace('<script src="/static/app.js?v=50"></script>', "")
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    {css}
    html, body {{ background: #071018; }}
  </style>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
</head>
<body>
  {body}
  <script>window.__SNAPSHOT = {data};</script>
  <script>{js}</script>
</body>
</html>"""


st.markdown(
    """
    <style>
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
      background: #071018;
    }
    .block-container {
      padding-top: 64px !important;
      padding-bottom: 1.5rem;
      max-width: 1180px;
    }
    [data-testid="stMainBlockContainer"] {
      padding-left: 0.35rem;
      padding-right: 0.35rem;
    }
    [data-testid="stHeader"] { display: none; }
    iframe { background: #071018 !important; border: 0; }
    footer { visibility: hidden; height: 0; }
    .qqq-ha-head {
      margin: 18px 0 0;
      padding: 16px 16px 10px;
      background: #0d1822;
      border: 1px solid rgba(140, 196, 180, 0.16);
      border-bottom: 0;
      border-radius: 14px 14px 0 0;
    }
    .qqq-ha-head h2 {
      margin: 0 0 4px;
      color: #e2c36b;
      font-size: 1.15rem;
      font-weight: 600;
      letter-spacing: -0.01em;
      font-family: "IBM Plex Sans KR", sans-serif;
    }
    .qqq-ha-head p {
      margin: 0;
      color: #8aa39a;
      font-size: 0.88rem;
      line-height: 1.45;
      font-family: "IBM Plex Sans KR", sans-serif;
    }
    div[data-testid="stPlotlyChart"]:has(#qqq_ha_bottom),
    div[data-testid="stElementContainer"]:has(.js-plotly-plot) {
      margin-top: 0 !important;
    }
    [data-testid="stPlotlyChart"] {
      background: #0d1822;
      border: 1px solid rgba(140, 196, 180, 0.16);
      border-top: 0;
      border-radius: 0 0 14px 14px;
      padding: 0 6px 8px;
      margin-top: 0 !important;
    }
    [data-testid="stPlotlyChart"] .modebar-btn path {
      fill: #8aa39a !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

top_menu("long")

try:
    payload = load_snapshot()
except Exception as exc:
    st.error("시세를 아직 가져오지 못했습니다. 페이지를 다시 열면 이어서 받아 옵니다.")
    st.caption(str(exc))
    st.stop()

if payload.get("stale"):
    st.warning("오늘 아침 종가를 아직 받지 못해, 마지막에 저장해 둔 종가로 보여주고 있습니다.")

st.iframe(
    dashboard_html(payload),
    height="content",
    alt="TQQQ 웅덩이 매수 신호지수",
)

cached = load_cache()
qqq_bars = list(official_closes(cached).daily_ohlc.get("QQQ", [])) if cached is not None else []
chart = build_chart(qqq_bars) if qqq_bars else None
if chart is not None:
    st.markdown(
        f"""
        <div class="qqq-ha-head">
          <h2>QQQ 일봉 · 헤이킨 아시</h2>
          <p>마지막 봉 {last_bar_label(qqq_bars)} · 최근 1년 · 실제 일봉과 헤이킨 아시 · 한국시간 06:30 갱신</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.plotly_chart(
        chart,
        width="stretch",
        theme=None,
        key="qqq_ha_bottom",
        config={
            "scrollZoom": False,
            "displaylogo": False,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
    )
elif payload.get("stale"):
    st.caption("QQQ 일봉 차트를 아직 받지 못했습니다. 페이지를 다시 열면 이어서 받아 옵니다.")
