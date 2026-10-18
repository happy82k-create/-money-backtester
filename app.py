"""떨사오팔 Pro3 백테스터 (Streamlit)."""
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from engine import Params, load_prices, run_backtest  # noqa: E402

# 데이터 갱신 버튼은 내 컴퓨터(run_app.bat 이 ENABLE_REFRESH=1 설정)에서만 표시. 공개 서버에서는 숨김.
ENABLE_REFRESH = os.environ.get("ENABLE_REFRESH", "0") == "1"

st.set_page_config(page_title="돈을벌자 초보자용 백테스터", page_icon="📈", layout="wide")


@st.cache_data(show_spinner=False)
def get_prices(ticker: str) -> pd.Series:
    return load_prices(ticker)


# 두 종목이 모두 가진 기간을 선택 가능 범위로 사용
_soxl, _tqqq = get_prices("SOXL"), get_prices("TQQQ")
DATA_MIN = max(_soxl.index.min(), _tqqq.index.min()).date()
DATA_MAX = min(_soxl.index.max(), _tqqq.index.max()).date()


@st.cache_data(show_spinner=False)
def backtest(params_dict: dict):
    p = Params(**params_dict)
    prices = get_prices(p.ticker)
    prices = prices[(prices.index >= pd.Timestamp(p.start)) & (prices.index <= pd.Timestamp(p.end))]
    res = run_backtest(prices, p)
    return res, prices


# ---------------------------------------------------------------- 사이드바
st.sidebar.header("⚙️ 백테스트 설정")
ticker = st.sidebar.selectbox("종목", ["SOXL", "TQQQ"])
c1, c2 = st.sidebar.columns(2)
start = c1.date_input("시작일", value=DATA_MIN, min_value=DATA_MIN, max_value=DATA_MAX)
end = c2.date_input("종료일", value=DATA_MAX, min_value=DATA_MIN, max_value=DATA_MAX)

initial_capital = st.sidebar.number_input(
    "초기자본 (USD)", min_value=100.0, max_value=1_000_000_000.0,
    value=10_000.0, step=1_000.0, format="%.0f",
    help="직접 입력할 수 있습니다. 기본값은 $10,000 입니다.",
)

ENTRY_OPTIONS = ["균등 (16.7% × 6)", "차등 (10/15/20/25/15/10%)", "직접 입력 (6개 %)"]
entry_label = st.sidebar.radio("진입 방식", ENTRY_OPTIONS)
entry_mode = {"균": "equal", "차": "tiered", "직": "custom"}[entry_label[0]]

custom_weights = None
if entry_mode == "custom":
    st.sidebar.caption("1번~6번 분할의 시드 비중(%)을 입력하세요. 1번은 가장 먼저 진입하는 칸이며, "
                       "비어 있는 가장 앞 번호부터 차례로 사용합니다.")
    defaults = [10.0, 15.0, 20.0, 25.0, 15.0, 10.0]
    cols = st.sidebar.columns(2)
    vals = []
    for i, d in enumerate(defaults):
        vals.append(cols[i % 2].number_input(f"{i + 1}번 분할 (%)", min_value=0.1, max_value=100.0,
                                             value=d, step=1.0, format="%.1f", key=f"cw{i}"))
    total_w = sum(vals)
    if total_w > 100.0 + 1e-6:
        st.sidebar.error(f"합계 {total_w:.1f}% — 100%를 넘을 수 없습니다.")
        st.error("진입 비중의 합계가 100%를 넘습니다. 사이드바에서 수정해 주세요.")
        st.stop()
    elif total_w < 100.0 - 1e-6:
        st.sidebar.info(f"합계 {total_w:.1f}% (남는 {100 - total_w:.1f}%는 항상 현금으로 보유)")
    else:
        st.sidebar.success("합계 100.0%")
    custom_weights = tuple(float(v) for v in vals)
    entry_label = "직접 입력 (" + "/".join(f"{v:g}" for v in vals) + "%)"

tp_choice = st.sidebar.radio("익절 (진입가 대비)", ["+0.01%", "+1.00%", "+2.00%", "직접 입력"], index=2, horizontal=True)
if tp_choice == "직접 입력":
    tp_pct = st.sidebar.number_input("익절 % 직접 입력", min_value=0.01, max_value=50.0, value=2.0, step=0.1)
else:
    tp_pct = float(tp_choice.replace("%", "").replace("+", ""))

tc_choice = st.sidebar.radio("타임컷 (거래일)", ["10일", "12일", "직접 입력"], horizontal=True)
if tc_choice == "직접 입력":
    timecut_days = int(st.sidebar.number_input("타임컷 일수", min_value=1, max_value=60, value=10, step=1))
else:
    timecut_days = int(tc_choice.replace("일", ""))

with st.sidebar.expander("고급 설정"):
    buy_drop_pct = st.number_input("매수 기준: 전일 종가 대비 하락 %", min_value=0.0, max_value=20.0, value=0.10, step=0.01, format="%.2f")
    fee_pct = st.number_input("편도 수수료·슬리피지 %", min_value=0.0, max_value=5.0, value=0.0, step=0.01, format="%.2f")
    compound = st.checkbox("복리 (분할 금액을 직전 총자산 기준으로 재계산)", value=False)
    fractional = st.checkbox("소수점 주식 허용", value=False)

st.sidebar.divider()
st.sidebar.caption(f"📅 보유 데이터: {DATA_MIN} ~ {DATA_MAX}")
if ENABLE_REFRESH and st.sidebar.button(
        "🔄 최신 데이터 갱신", help="야후 파이낸스에서 오늘까지의 종가를 다시 받아 저장합니다. (시간이 몇 초 걸립니다)"):
    from fetch_data import update_all  # 필요할 때만 불러옴 (yfinance 사용)
    with st.spinner("최신 종가를 내려받는 중..."):
        report = update_all()
    st.cache_data.clear()
    for tk, msg in report.items():
        (st.sidebar.warning if msg.startswith(("실패", "건너뜀")) else st.sidebar.success)(f"{tk}: {msg}")
    st.sidebar.info("새 데이터를 쓰려면 아래 버튼을 눌러 화면을 새로고침하세요.")
    st.sidebar.button("화면 새로고침")
st.sidebar.caption("⚠️ 교육·참고용 과거 데이터 시뮬레이션입니다. 투자 조언이 아니며 실제 수익을 보장하지 않습니다.")

if start >= end:
    st.error("시작일은 종료일보다 앞이어야 합니다.")
    st.stop()

params = dict(
    ticker=ticker, start=str(start), end=str(end), initial_capital=float(initial_capital),
    entry_mode=entry_mode, custom_weights=custom_weights, tp_pct=float(tp_pct), timecut_days=timecut_days,
    buy_drop_pct=float(buy_drop_pct), fee_pct=float(fee_pct),
    compound=compound, fractional=fractional,
)
res, prices = backtest(params)
m = res.metrics
eq = res.equity["equity"]
bh = prices / prices.iloc[0] * initial_capital

# ---------------------------------------------------------------- 본문
st.title("📈 돈을벌자 초보자용 백테스터")
st.caption(
    f"{ticker} · {m['기간 시작']} ~ {m['기간 종료']} · 초기자본 ${initial_capital:,.0f} · "
    f"{entry_label} · 익절 +{tp_pct:g}% · 타임컷 {timecut_days}일 · LOC 전용(종가 체결)"
)

tab_result, tab_trades, tab_compare, tab_heat, tab_rules = st.tabs(
    ["📊 결과", "🧾 거래 내역", "🔬 조건 비교", "🗺️ 히트맵", "📖 전략 규칙"])

with tab_result:
    k = st.columns(4)
    k[0].metric("최종 자산", f"${m['최종 자산']:,.0f}", f"{m['총 수익률(%)']:+.1f}%")
    k[1].metric("연환산 수익률(CAGR)", f"{m['연환산 수익률 CAGR(%)']:.1f}%")
    k[2].metric("최대 낙폭(MDD)", f"{m['최대 낙폭 MDD(%)']:.1f}%")
    k[3].metric("승률", f"{m['승률(%)']:.1f}%")
    k = st.columns(4)
    k[0].metric("청산 거래 수", f"{m['총 거래 수(청산)']:,}")
    k[1].metric("타임컷(손절) 비율", f"{m['타임컷 비율(%)']:.1f}%")
    k[2].metric("평균 보유일", f"{m['평균 보유일']:.1f}일")
    k[3].metric("미청산 포지션", f"{m['미청산 포지션']}개")

    st.subheader("자산 곡선 비교")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05,
                        subplot_titles=("계좌 자산 (USD)", "낙폭 (Drawdown %)"))
    fig.add_trace(go.Scatter(x=eq.index, y=eq, name="떨사오팔", line=dict(width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=bh.index, y=bh, name="Buy & Hold", line=dict(width=1.5, dash="dot")), row=1, col=1)
    fig.add_trace(go.Scatter(x=eq.index, y=(eq / eq.cummax() - 1) * 100, name="떨사오팔 낙폭", fill="tozeroy",
                             line=dict(width=1)), row=2, col=1)
    fig.add_trace(go.Scatter(x=bh.index, y=(bh / bh.cummax() - 1) * 100, name="B&H 낙폭",
                             line=dict(width=1, dash="dot")), row=2, col=1)
    fig.update_layout(height=620, hovermode="x unified", legend=dict(orientation="h", y=1.08))
    st.plotly_chart(fig, width="stretch")

    st.subheader("전략 vs Buy & Hold")
    cmp_df = pd.DataFrame({
        "": ["총 수익률(%)", "최대 낙폭 MDD(%)", "최종 자산($)"],
        "떨사오팔": [m["총 수익률(%)"], m["최대 낙폭 MDD(%)"], m["최종 자산"]],
        "Buy & Hold": [m["Buy&Hold 수익률(%)"], m["Buy&Hold MDD(%)"], bh.iloc[-1]],
    }).set_index("")
    st.dataframe(cmp_df.style.format("{:,.1f}"), width="stretch")

    st.subheader("현금 vs 보유 평가액")
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=res.equity.index, y=res.equity["holdings"], name="보유 평가액", stackgroup="a"))
    fig2.add_trace(go.Scatter(x=res.equity.index, y=res.equity["cash"], name="현금", stackgroup="a"))
    fig2.update_layout(height=320, hovermode="x unified", legend=dict(orientation="h"))
    st.plotly_chart(fig2, width="stretch")

with tab_trades:
    t = res.trades
    st.subheader(f"청산된 거래 ({len(t):,}건)")
    if len(t):
        show = t.copy()
        for col in ("entry_date", "exit_date"):
            show[col] = pd.to_datetime(show[col]).dt.date
        show = show.rename(columns={
            "ticker": "종목", "slot": "티어", "entry_date": "진입일", "entry_price": "진입가",
            "exit_date": "청산일", "exit_price": "청산가", "shares": "수량", "hold_days": "보유일",
            "reason": "사유", "pnl": "손익($)", "return_pct": "수익률(%)",
        })
        reasons = st.multiselect("사유 필터", ["익절", "타임컷"], default=["익절", "타임컷"])
        show = show[show["사유"].isin(reasons)]
        st.dataframe(show.style.format({"진입가": "{:.2f}", "청산가": "{:.2f}", "수량": "{:,.2f}",
                                          "손익($)": "{:,.2f}", "수익률(%)": "{:+.2f}"}),
                     width="stretch", height=420)
        st.download_button("거래 내역 CSV 다운로드", show.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"trades_{ticker}.csv", mime="text/csv")
    else:
        st.info("청산된 거래가 없습니다.")

    st.subheader("종료일 기준 미청산 포지션")
    o = res.open_positions
    if len(o):
        o = o.copy()
        o["entry_date"] = pd.to_datetime(o["entry_date"]).dt.date
        o = o.rename(columns={"slot": "티어", "entry_date": "진입일", "entry_price": "진입가", "shares": "수량",
                              "hold_days": "보유일", "last_close": "종료일 종가", "unrealized_pct": "평가수익률(%)"})
        st.dataframe(o.style.format({"진입가": "{:.2f}", "수량": "{:,.2f}", "종료일 종가": "{:.2f}",
                                       "평가수익률(%)": "{:+.2f}"}), width="stretch")
    else:
        st.write("없음")

    st.subheader("일별 계좌 상태")
    st.dataframe(res.equity.round(2), width="stretch", height=300)

with tab_compare:
    st.subheader("익절 × 타임컷 조합 비교")
    st.caption("현재 사이드바의 종목·기간·초기자본·진입 방식·고급 설정은 그대로 두고, 익절과 타임컷만 바꿔 비교합니다.")
    rows = []
    for tp in (0.01, 1.0, 2.0):
        for tc in (10, 12):
            r, _ = backtest({**params, "tp_pct": tp, "timecut_days": tc})
            mm = r.metrics
            rows.append({
                "익절(%)": tp, "타임컷(일)": tc,
                "최종 자산($)": mm["최종 자산"], "총수익(%)": mm["총 수익률(%)"],
                "CAGR(%)": mm["연환산 수익률 CAGR(%)"], "MDD(%)": mm["최대 낙폭 MDD(%)"],
                "승률(%)": mm["승률(%)"], "타임컷(%)": mm["타임컷 비율(%)"],
                "거래 수": mm["총 거래 수(청산)"], "평균 보유일": mm["평균 보유일"],
            })
    cdf = pd.DataFrame(rows)
    st.dataframe(cdf.style.format({
        "익절(%)": "{:.2f}", "최종 자산($)": "{:,.0f}", "총수익(%)": "{:.1f}", "CAGR(%)": "{:.1f}",
        "MDD(%)": "{:.1f}", "승률(%)": "{:.1f}", "타임컷(%)": "{:.1f}", "평균 보유일": "{:.1f}",
    }), width="stretch", hide_index=True)

    st.subheader("진입 방식 비교 (현재 익절·타임컷 기준)")
    rows = []
    modes = [("equal", "균등"), ("tiered", "차등")]
    if entry_mode == "custom":
        modes.append(("custom", entry_label))
    for mode, label in modes:
        r, _ = backtest({**params, "entry_mode": mode})
        mm = r.metrics
        rows.append({"진입": label, "최종 자산($)": mm["최종 자산"], "총수익(%)": mm["총 수익률(%)"],
                     "CAGR(%)": mm["연환산 수익률 CAGR(%)"], "MDD(%)": mm["최대 낙폭 MDD(%)"]})
    st.dataframe(pd.DataFrame(rows).style.format({"최종 자산($)": "{:,.0f}", "총수익(%)": "{:.1f}",
                                                    "CAGR(%)": "{:.1f}", "MDD(%)": "{:.1f}"}),
                 width="stretch", hide_index=True)

HEAT_TP = [0.01, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0]
HEAT_TC = [6, 8, 10, 12, 14, 16, 20]
HEAT_METRICS = {
    "최종 자산($)": ("최종 자산", "{:,.0f}"),
    "총수익(%)": ("총 수익률(%)", "{:.0f}"),
    "CAGR(%)": ("연환산 수익률 CAGR(%)", "{:.1f}"),
    "MDD(%)": ("최대 낙폭 MDD(%)", "{:.1f}"),
    "승률(%)": ("승률(%)", "{:.1f}"),
    "타임컷 비율(%)": ("타임컷 비율(%)", "{:.1f}"),
}


@st.cache_data(show_spinner=False)
def heat_grid(base_params: dict) -> dict:
    out = {k: [] for k in HEAT_METRICS}
    for tp in HEAT_TP:
        rows = {k: [] for k in HEAT_METRICS}
        for tc in HEAT_TC:
            mm = backtest({**base_params, "tp_pct": tp, "timecut_days": tc})[0].metrics
            for label, (key, _) in HEAT_METRICS.items():
                rows[label].append(mm[key])
        for label in HEAT_METRICS:
            out[label].append(rows[label])
    return out


with tab_heat:
    st.subheader("파라미터 히트맵: 익절% × 타임컷 일수")
    st.caption("사이드바의 종목·기간·초기자본·진입 방식·고급 설정을 고정하고 익절%와 타임컷 일수 49개 조합을 한 번에 돌려 봅니다. "
               "(처음 계산 시 10~20초 걸립니다.)")
    base = {k: v for k, v in params.items() if k not in ("tp_pct", "timecut_days")}
    if st.button("🗺️ 히트맵 계산"):
        st.session_state["heat_base"] = base
    stored = st.session_state.get("heat_base")
    if stored is None:
        st.info("위 버튼을 눌러 계산하세요.")
    else:
        if stored != base:
            st.warning("사이드바 설정이 바뀌었습니다. 아래는 이전 설정의 결과이니, 새 설정으로 보려면 다시 계산하세요.")
        with st.spinner("49개 조합 계산 중..."):
            grid = heat_grid(stored)
        pick = st.selectbox("표시 지표", list(HEAT_METRICS), index=2)
        z = pd.DataFrame(grid[pick], index=[f"+{x:g}%" for x in HEAT_TP], columns=[f"{c}일" for c in HEAT_TC])
        fmt = HEAT_METRICS[pick][1]
        hm = go.Figure(go.Heatmap(
            z=z.values, x=z.columns, y=z.index,
            text=[[fmt.format(v) for v in row] for row in z.values], texttemplate="%{text}",
            colorscale="RdYlGn", reversescale=(pick == "타임컷 비율(%)"), colorbar=dict(title=pick),
        ))
        hm.update_layout(height=480, xaxis_title="타임컷", yaxis_title="익절", yaxis=dict(autorange="reversed"))
        st.plotly_chart(hm, width="stretch")
        best_i = z.stack().idxmin() if pick in ("타임컷 비율(%)",) else z.stack().idxmax()
        st.caption(f"'{pick}' 기준 최고 조합: 익절 {best_i[0]} / 타임컷 {best_i[1]} → {fmt.format(z.loc[best_i])}")
        st.caption("⚠️ 가장 좋은 칸만 고르면 과거 데이터에 과적합될 수 있습니다. 주변 칸들도 비슷하게 좋은지(안정적인 영역인지)를 함께 보세요.")
        st.dataframe(z.style.format(fmt), width="stretch")

with tab_rules:
    st.markdown(f"""
### 이 백테스트가 적용하는 규칙
**주문 방식** — 모든 주문은 LOC(종가 지정가)이며, 조건이 맞으면 **그날 종가**로 체결됩니다.

**매수** — 미진입 티어가 있으면 매일 *전일 종가 × (1 − {buy_drop_pct:.2f}%)* 이하로 마감할 때 1분할을 종가에 매수합니다. 하루 최대 1건, 정액 매수는 없습니다.

**매도(익절)** — 티어별 진입가 × (1 + {tp_pct:g}%) 이상으로 마감하면 해당 티어만 종가에 매도합니다. 진입 당일에는 매도하지 않습니다.

**타임컷(손절)** — 진입 후 {timecut_days}거래일째까지 익절되지 않으면 그날 종가에 기계적으로 매도합니다.
타임컷 당일에도 매수 조건을 충족하면 신규 1분할을 같은 날 매수합니다. 익절로 빈 티어는 **다음 거래일**부터 매수할 수 있습니다.

**분할** — 6분할. 균등은 시드의 16.7%씩, 차등은 비어 있는 가장 앞 티어부터 10/15/20/25/15/10%를 사용합니다.
직접 입력은 1~6번 비중을 원하는 %로 정하며(합계 100% 이하), 같은 방식으로 비어 있는 가장 앞 번호부터 사용합니다.
분할 금액은 {'직전 총자산' if compound else '초기자본'} 기준이며, 보유 현금을 넘지 않습니다.

**가격 데이터** — SOXL·TQQQ 일별 종가(분할 조정, 배당 미반영), 2020-01-02 ~ 2026-10-15.

> ⚠️ 과거 시뮬레이션 결과이며 미래 수익을 보장하지 않습니다. 3배 레버리지 ETF는 변동성이 매우 큽니다.
""")
