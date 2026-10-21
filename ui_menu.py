"""두 페이지가 같은 높이의 상단 메뉴를 쓴다."""
import streamlit as st


def top_menu(active: str) -> None:
    long_on = " on" if active == "long" else ""
    short_on = " on" if active == "short" else ""
    st.markdown(
        f"""
        <style>
        [data-testid="stHeader"] {{
          display: none !important;
          height: 0 !important;
          min-height: 0 !important;
          max-height: 0 !important;
          overflow: hidden !important;
          background: transparent !important;
          border: none !important;
        }}
        .app-menu {{
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          height: 64px;
          min-height: 64px;
          max-height: 64px;
          box-sizing: border-box;
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
          align-items: center;
          z-index: 100002;
          background: #071018;
          padding: 8px 10px;
          margin: 0;
        }}
        .app-menu a {{
          display: flex;
          align-items: center;
          justify-content: center;
          height: 48px;
          min-height: 48px;
          max-height: 48px;
          box-sizing: border-box;
          padding: 0 8px;
          border-radius: 12px;
          background: #122433;
          color: #e7f2ee;
          text-decoration: none;
          font-weight: 700;
          font-size: 15px;
          line-height: 1;
          text-align: center;
          white-space: nowrap;
          overflow: hidden;
        }}
        .app-menu a.on {{
          background: #e2c36b;
          color: #071018;
        }}
        .block-container {{
          padding-top: 64px !important;
        }}
        @media (max-width: 720px) {{
          .app-menu a {{ font-size: 14px; }}
        }}
        </style>
        <div class="app-menu">
          <a class="{long_on}" href="/" target="_self">1. TQQQ 장기투자</a>
          <a class="{short_on}" href="/short" target="_self">2. TQQQ 단기투자</a>
        </div>
        """,
        unsafe_allow_html=True,
    )
