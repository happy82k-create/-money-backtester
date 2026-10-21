"""장기 신호와 단기 백테스트를 상단 메뉴로 묶는 진입점."""
import streamlit as st

st.set_page_config(
    page_title="TQQQ 투자",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="auto",
)

st.markdown(
    """
    <style>
    [data-testid="stHeader"] {
      background: #071018;
      border-bottom: 1px solid rgba(140, 196, 180, 0.28);
    }
    [data-testid="stDecoration"] { display: none; }
    [data-testid="stAppDeployButton"],
    [data-testid="stMainMenu"],
    [data-testid="stToolbarActions"] { display: none !important; }
    [data-testid="stToolbar"],
    [data-testid="stToolbar"] > div {
      width: 100%;
    }
    [data-testid="stTopNav"] {
      display: flex !important;
      width: 100% !important;
      gap: 8px;
      padding: 6px 8px 8px;
    }
    [data-testid="stTopNav"] > .rc-overflow-item:not(.rc-overflow-item-rest) {
      flex: 1 1 0 !important;
      position: static !important;
      opacity: 1 !important;
      height: auto !important;
    }
    [data-testid="stTopNavLinkContainer"],
    [data-testid="stTopNavLink"] {
      width: 100%;
      display: flex !important;
      justify-content: center;
      align-items: center;
    }
    [data-testid="stTopNav"] a {
      min-height: 48px;
      margin: 0 !important;
      padding: 10px 8px !important;
      font-size: 16px !important;
      font-weight: 700 !important;
      border-radius: 12px !important;
      background: #122433;
      color: #e7f2ee !important;
    }
    [data-testid="stTopNav"] p {
      white-space: normal !important;
      text-align: center;
      margin: 0;
    }
    [data-testid="stTopNav"] a[aria-current="page"] {
      background: #e2c36b;
      color: #071018 !important;
    }
    @media (max-width: 720px) {
      [data-testid="stTopNav"] a {
        font-size: 13px !important;
        min-height: 52px;
        line-height: 1.25;
        text-align: center;
      }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

long = st.Page("pages/long.py", title="1. TQQQ 장기투자", default=True)
short = st.Page("pages/short.py", title="2. TQQQ 단기투자")
st.navigation([long, short], position="top").run()
