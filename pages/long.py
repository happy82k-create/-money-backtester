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
    """이번 08:00 구간에 종가를 받은 뒤에만 캐시한다. 실패는 캐시하지 않는다."""
    refresh_if_due()
    bundle = load_cache()
    if bundle is None or not window_satisfied(bundle.fetched_at, bundle.sources_ok):
        raise RuntimeError("이번 아침 종가가 아직 없습니다.")
    payload = build_payload(official_closes(bundle))
    payload["stale"] = False
    payload["window_id"] = window_id
    return payload


def load_snapshot() -> dict:
    """한국시간 08:00 기준 미국 종가. 화면의 버튼으로는 다시 받지 않는다."""
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
      padding-bottom: 0;
      max-width: 1180px;
    }
    [data-testid="stMainBlockContainer"] {
      padding-left: 0.35rem;
      padding-right: 0.35rem;
    }
    [data-testid="stHeader"] { display: none; }
    iframe { background: #071018 !important; border: 0; }
    footer { visibility: hidden; height: 0; }
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
