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


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def _qqq_chart_bars(window_id: str) -> list[tuple]:
    """점수판 갱신과 분리. 같은 06:30 구간에서는 다시 받지 않는다."""
    del window_id
    from singularity.qqq_charts import load_qqq_chart_bars

    return load_qqq_chart_bars()


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
  <style>
    {css}
    html, body {{ background: #071018; font-family: "IBM Plex Sans KR", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif; }}
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
      padding: 16px 16px 12px;
      background: #0d1822;
      border: 1px solid rgba(140, 196, 180, 0.16);
      border-radius: 14px;
    }
    .qqq-ha-head.open {
      border-bottom: 0;
      border-radius: 14px 14px 0 0;
      margin-bottom: 0;
      padding-bottom: 10px;
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
    .qqq-ha-illust {
      min-width: 0;
      border: 1px solid rgba(140, 196, 180, 0.16);
      border-radius: 10px;
      background: #071018;
      padding: 6px 6px 4px;
    }
    .qqq-ha-illust svg {
      display: block;
      width: 100%;
      height: auto;
      max-height: 88px;
    }
    .qqq-ha-illust-label {
      margin: 4px 2px 0;
      color: #8aa39a;
      font-size: 0.72rem;
      font-family: "IBM Plex Sans KR", sans-serif;
    }
    div[data-testid="stHorizontalBlock"]:has(.qqq-ha-illust) {
      background: #0d1822;
      border: 1px solid rgba(140, 196, 180, 0.16);
      border-top: 0;
      border-radius: 0 0 14px 14px;
      padding: 0 12px 14px;
      margin-top: 0;
      gap: 0.65rem;
      align-items: center;
    }
    .stButton > button {
      background: #e2c36b !important;
      color: #1a1406 !important;
      border: 0 !important;
      border-radius: 10px !important;
      font-weight: 600 !important;
      font-family: "IBM Plex Sans KR", sans-serif !important;
      width: 100%;
      min-height: 42px;
      white-space: normal !important;
      line-height: 1.25 !important;
      padding: 10px 12px !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.qqq-ha-illust) .stButton > button {
      min-height: 72px;
    }
    .stButton > button:hover {
      background: #f0d48a !important;
      color: #1a1406 !important;
      border: 0 !important;
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

# 고정 일러스트용 14봉. 실세 수신 없이 헤이킨 아시 모양만 보여 준다.
_HA_PREVIEW = (
    (62, 58, 62, 58),
    (58, 54, 59, 54),
    (54, 51, 55, 51),
    (51, 49, 52, 49),
    (49, 52, 49, 52),
    (52, 56, 52, 56),
    (56, 60, 55, 60),
    (60, 63, 59, 63),
    (63, 61, 64, 61),
    (61, 57, 62, 57),
    (57, 55, 58, 55),
    (55, 58, 54, 58),
    (58, 62, 57, 62),
    (62, 66, 61, 66),
)


def _ha_preview_svg() -> str:
    width, height, pad = 280, 78, 6
    lows = [bar[2] for bar in _HA_PREVIEW]
    highs = [bar[1] for bar in _HA_PREVIEW]
    lo, hi = min(lows), max(highs)
    span = max(hi - lo, 1)
    gap = (width - 2 * pad) / len(_HA_PREVIEW)
    body_w = max(4.5, gap * 0.55)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="헤이킨 아시 14봉 예시 일러스트">'
        f'<rect width="{width}" height="{height}" fill="#071018" rx="8"/>'
    ]
    for index, (open_, high, low, close) in enumerate(_HA_PREVIEW):
        cx = pad + gap * index + gap / 2
        y_high = pad + (hi - high) / span * (height - 2 * pad)
        y_low = pad + (hi - low) / span * (height - 2 * pad)
        y_open = pad + (hi - open_) / span * (height - 2 * pad)
        y_close = pad + (hi - close) / span * (height - 2 * pad)
        top = min(y_open, y_close)
        body_h = max(2.2, abs(y_close - y_open))
        color = "#e23b3b" if close >= open_ else "#3d8bfd"
        parts.append(
            f'<line x1="{cx:.1f}" y1="{y_high:.1f}" x2="{cx:.1f}" y2="{y_low:.1f}" '
            f'stroke="{color}" stroke-width="1.6" stroke-linecap="round"/>'
            f'<rect x="{cx - body_w / 2:.1f}" y="{top:.1f}" width="{body_w:.1f}" '
            f'height="{body_h:.1f}" fill="{color}" rx="1"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


show_chart = bool(st.session_state.get("show_qqq_ha"))
if not show_chart:
    st.markdown(
        """
        <div class="qqq-ha-head" style="border-radius:14px 14px 0 0;border-bottom:0;margin-bottom:0;">
          <h2>QQQ 일봉 · 헤이킨 아시</h2>
          <p>버튼을 누를 때만 실전 차트를 받습니다. 옆 그림은 14봉 예시 일러스트입니다.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    illust_col, button_col = st.columns([1.25, 0.85], gap="small")
    with illust_col:
        st.markdown(
            f"""
            <div class="qqq-ha-illust">
              {_ha_preview_svg()}
              <div class="qqq-ha-illust-label">헤이킨 아시 14봉 예시 · 고정 일러스트</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with button_col:
        if st.button("QQQ 헤이킨 아시\n차트 보기", key="open_qqq_ha"):
            st.session_state["show_qqq_ha"] = True
            st.rerun()
else:
    with st.spinner("QQQ 차트를 받는 중"):
        from singularity.qqq_charts import build_chart, last_bar_label

        try:
            qqq_bars = _qqq_chart_bars(payload.get("window_id") or current_window_id())
        except Exception:
            qqq_bars = []
        chart = build_chart(qqq_bars) if qqq_bars else None
    detail = (
        f"마지막 봉 {last_bar_label(qqq_bars)} · 최근 1년 · 실제 일봉과 헤이킨 아시 · 한국시간 06:30 갱신"
        if qqq_bars
        else "차트를 받지 못했습니다. 다시 시도해 주세요."
    )
    st.markdown(
        f"""
        <div class="qqq-ha-head{" open" if chart is not None else ""}">
          <h2>QQQ 일봉 · 헤이킨 아시</h2>
          <p>{detail}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if chart is not None:
        st.plotly_chart(
            chart,
            width="stretch",
            theme=None,
            key="qqq_ha_bottom",
            config={
                "scrollZoom": False,
                "displaylogo": False,
                "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d", "zoom2d"],
            },
        )
        if st.button("차트 닫기", key="close_qqq_ha"):
            st.session_state["show_qqq_ha"] = False
            st.rerun()
    else:
        if st.button("다시 시도", key="retry_qqq_ha"):
            _qqq_chart_bars.clear()
            st.rerun()
        if st.button("차트 닫기", key="close_qqq_ha_fail"):
            st.session_state["show_qqq_ha"] = False
            st.rerun()
