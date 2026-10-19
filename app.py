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
from infinite import IParams, run_infinite  # noqa: E402

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


@st.cache_data(show_spinner=False)
def infinite_backtest(params_dict: dict):
    p = IParams(**params_dict)
    prices = get_prices(p.ticker)
    prices = prices[(prices.index >= pd.Timestamp(p.start)) & (prices.index <= pd.Timestamp(p.end))]
    return run_infinite(prices, p), prices


def render_infinite(res, prices, ticker, capital, n_split, target_pct, iparams):
    """무한매수법 V4 결과 화면. 돈을벌자 화면은 건드리지 않는다."""
    m = res.metrics
    eq = res.equity["equity"]
    bh = prices / prices.iloc[0] * capital
    st.title("📈 돈을벌자 초보자용 백테스터")
    st.caption(
        f"무한매수법 V4 · {ticker} · {m['기간 시작']} ~ {m['기간 종료']} · "
        f"초기자본 ${capital:,.0f} · {n_split}분할 · 목표 +{target_pct:g}% · LOC(종가 체결)"
    )

    tab_result, tab_fills, tab_cycles, tab_cmp, tab_rules = st.tabs(
        ["📊 결과", "🧾 매수·매도", "🔁 사이클", "🔬 수익률 비교", "📖 전략 규칙"])

    with tab_result:
        k = st.columns(4)
        k[0].metric("최종 자산", f"${m['최종 자산']:,.0f}", f"{m['총 수익률(%)']:+.1f}%")
        k[1].metric("연환산 수익률(CAGR)", f"{m['연환산 수익률 CAGR(%)']:.1f}%")
        k[2].metric("최대 낙폭(MDD)", f"{m['최대 낙폭 MDD(%)']:.1f}%")
        k[3].metric("사이클 승률", f"{m['사이클 승률(%)']:.1f}%")
        k = st.columns(4)
        k[0].metric("완료 사이클", f"{m['완료 사이클 수']}")
        k[1].metric("사이클 평균 수익률", f"{m['사이클 평균 수익률(%)']:+.1f}%")
        k[2].metric("평균 소요일", f"{m['사이클 평균 소요일']:.0f}일")
        k[3].metric("리버스 경험 사이클", f"{m['리버스 경험 사이클']}")

        st.subheader("자산 곡선 비교")
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05,
                            subplot_titles=("계좌 자산 (USD)", "낙폭 (Drawdown %)"))
        fig.add_trace(go.Scatter(x=eq.index, y=eq, name="무한매수법 V4", line=dict(width=2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=bh.index, y=bh, name="Buy & Hold", line=dict(width=1.5, dash="dot")), row=1, col=1)
        fig.add_trace(go.Scatter(x=eq.index, y=(eq / eq.cummax() - 1) * 100, name="무한매수 낙폭", fill="tozeroy",
                                 line=dict(width=1)), row=2, col=1)
        fig.add_trace(go.Scatter(x=bh.index, y=(bh / bh.cummax() - 1) * 100, name="B&H 낙폭",
                                 line=dict(width=1, dash="dot")), row=2, col=1)
        fig.update_layout(height=620, hovermode="x unified", legend=dict(orientation="h", y=1.08))
        st.plotly_chart(fig, width="stretch")

        st.subheader("전략 vs Buy & Hold")
        cmp_df = pd.DataFrame({
            "": ["총 수익률(%)", "최대 낙폭 MDD(%)", "최종 자산($)"],
            "무한매수법 V4": [m["총 수익률(%)"], m["최대 낙폭 MDD(%)"], m["최종 자산"]],
            "Buy & Hold": [m["Buy&Hold 수익률(%)"], m["Buy&Hold MDD(%)"], bh.iloc[-1]],
        }).set_index("")
        st.dataframe(cmp_df.style.format("{:,.1f}"), width="stretch")

        st.subheader("현금 vs 보유 평가액 · 회차 T")
        fig2 = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35], vertical_spacing=0.08,
                             subplot_titles=("현금 / 보유 평가액", "회차 T"))
        fig2.add_trace(go.Scatter(x=res.equity.index, y=res.equity["holdings"], name="보유 평가액", stackgroup="a"), 1, 1)
        fig2.add_trace(go.Scatter(x=res.equity.index, y=res.equity["cash"], name="현금", stackgroup="a"), 1, 1)
        fig2.add_trace(go.Scatter(x=res.equity.index, y=res.equity["T"], name="T", line=dict(width=1.5)), 2, 1)
        fig2.update_layout(height=460, hovermode="x unified", legend=dict(orientation="h"))
        st.plotly_chart(fig2, width="stretch")

    with tab_fills:
        ev = res.events
        st.subheader(f"매수·매도 체결 ({len(ev):,}건)")
        st.caption("매수 행의 수익률(%)은 체결 직후 종가 대비 평가수익률, 매도 행은 그 매도 건의 실현 수익률입니다.")
        if len(ev):
            show = ev.copy()
            show["date"] = pd.to_datetime(show["date"]).dt.date
            is_sell = show["pnl"].notna()
            side = is_sell.map({True: "매도", False: "매수"})
            kinds = sorted(show["kind"].unique().tolist())
            c1, c2 = st.columns(2)
            side_f = c1.multiselect("매수/매도", ["매수", "매도"], default=["매수", "매도"])
            kind_f = c2.multiselect("종류", kinds, default=kinds)
            show.insert(2, "구분", side)
            show = show[show["구분"].isin(side_f) & show["kind"].isin(kind_f)]
            show = show.rename(columns={
                "date": "날짜", "cycle": "사이클", "mode": "모드", "kind": "종류",
                "price": "체결가", "qty": "수량", "amount": "금액($)",
                "T_before": "T(전)", "T_after": "T(후)",
                "star_pct": "별%", "star_price": "별지점", "target_price": "목표가",
                "avg_after": "평단(후)", "shares_after": "보유(후)", "cash_after": "현금(후)",
                "pnl": "손익($)", "ret_pct": "수익률(%)",
            })
            st.dataframe(show.style.format({
                "체결가": "{:.2f}", "수량": "{:,.0f}", "금액($)": "{:,.2f}",
                "T(전)": "{:.3f}", "T(후)": "{:.3f}", "별%": "{:.2f}",
                "별지점": "{:.2f}", "목표가": "{:.2f}", "평단(후)": "{:.2f}",
                "보유(후)": "{:,.0f}", "현금(후)": "{:,.2f}",
                "손익($)": "{:,.2f}", "수익률(%)": "{:+.2f}",
            }, na_rep="-"), width="stretch", height=440)
            st.download_button("매수·매도 CSV 다운로드", show.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"infinite_fills_{ticker}_{n_split}.csv", mime="text/csv")
            sells = ev[ev["pnl"].notna()]
            buys = ev[ev["pnl"].isna()]
            k = st.columns(3)
            k[0].metric("매수 체결 수", f"{len(buys):,}")
            k[1].metric("매도 체결 수", f"{len(sells):,}")
            if len(sells):
                k[2].metric("매도 평균 실현수익률", f"{sells['ret_pct'].mean():+.2f}%")
        else:
            st.info("체결된 주문이 없습니다.")

        if res.open_cycle:
            st.subheader("종료일 기준 진행 중 사이클")
            o = res.open_cycle
            st.write(
                f"사이클 {o['cycle']} · {pd.Timestamp(o['start']).date()} 시작 · {o['days']}일 · "
                f"{o['mode']} · T={o['T']:.3f} · {o['shares']}주 · 평단 ${o['avg']:.2f} · "
                f"평가 {o['unrealized_pct']:+.2f}% · 사이클 평가수익 {o['equity_ret_pct']:+.2f}%"
            )

        st.subheader("일별 계좌 상태")
        st.dataframe(res.equity.round(2), width="stretch", height=280)

    with tab_cycles:
        cy = res.cycles
        st.subheader(f"완료된 사이클 ({len(cy):,}개)")
        if len(cy):
            show = cy.copy()
            show["start"] = pd.to_datetime(show["start"]).dt.date
            show["end"] = pd.to_datetime(show["end"]).dt.date
            show = show.rename(columns={
                "cycle": "사이클", "start": "시작", "end": "종료", "days": "일수",
                "start_cash": "시작 원금($)", "pnl": "손익($)", "ret_pct": "수익률(%)",
                "max_T": "최대 T", "reverse_used": "리버스", "reverse_days": "리버스 일수",
            })
            st.dataframe(show.style.format({
                "시작 원금($)": "{:,.0f}", "손익($)": "{:,.2f}", "수익률(%)": "{:+.2f}", "최대 T": "{:.2f}",
            }), width="stretch", height=380)
            st.download_button("사이클 CSV 다운로드", show.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"infinite_cycles_{ticker}_{n_split}.csv", mime="text/csv")
            figc = go.Figure(go.Bar(x=show["사이클"], y=show["수익률(%)"], name="사이클 수익률"))
            figc.update_layout(height=300, yaxis_title="수익률(%)")
            st.plotly_chart(figc, width="stretch")
        else:
            st.info("완료된 사이클이 없습니다. 기간이 짧거나 아직 청산되지 않았습니다.")

    with tab_cmp:
        def _row(label, mm):
            return {
                "설정": label,
                "최종 자산($)": mm["최종 자산"], "총수익(%)": mm["총 수익률(%)"],
                "CAGR(%)": mm["연환산 수익률 CAGR(%)"], "MDD(%)": mm["최대 낙폭 MDD(%)"],
                "사이클 수": mm["완료 사이클 수"], "사이클 승률(%)": mm["사이클 승률(%)"],
                "사이클 평균수익(%)": mm["사이클 평균 수익률(%)"],
                "리버스 사이클": mm["리버스 경험 사이클"],
            }

        fmt = {
            "최종 자산($)": "{:,.0f}", "총수익(%)": "{:.1f}", "CAGR(%)": "{:.1f}", "MDD(%)": "{:.1f}",
            "사이클 승률(%)": "{:.1f}", "사이클 평균수익(%)": "{:.1f}",
        }

        st.subheader("목표수익률 +10% / +15% / +20%")
        st.caption("종목·기간·초기자본·분할 수·고급 설정은 그대로 두고, 지정가 매도 목표만 바꿔 비교합니다.")
        rows = [_row(f"+{tp:g}%", infinite_backtest({**iparams, "target_pct": tp})[0].metrics)
                for tp in (10.0, 15.0, 20.0)]
        st.dataframe(pd.DataFrame(rows).style.format(fmt), width="stretch", hide_index=True)

        st.subheader("같은 목표에서 20 / 30 / 40분할")
        rows = [_row(f"{n}분할", infinite_backtest({**iparams, "n": n})[0].metrics) for n in (20, 30, 40)]
        st.dataframe(pd.DataFrame(rows).style.format(fmt), width="stretch", hide_index=True)

    with tab_rules:
        st.markdown(f"""
### 무한매수법 V4.0 (이 백테스터의 해석)

공개된 V4.0 일반모드·리버스모드 규칙을 **일별 종가**로 단순화한 비공식 구현입니다. 실전 주문(하방 사다리, 장중 고가 지정가)과는 차이가 날 수 있습니다.

**분할** — {n_split}분할. 1회 매수금 = 잔금 ÷ (분할수 − T). 매일 T와 잔금에 따라 조금씩 바뀝니다.

**T (회차)** — 1회분 매수 +1, 절반 매수 +0.5, 쿼터매도 ×0.75. 이력이 아니라 현재 얼마나 들어와 있는지의 상태값입니다.

**별%** — {ticker} 목표 {target_pct:g}% 기준 `목표 × (1 − 2T/분할수)`. 별지점 = 평단 × (1+별%). 매수는 별지점 − $0.01, 매도(1/4)는 별지점.

**처음 매수** — 보유 0일 때 1회분을 큰수(전일 종가 +{st.session_state.get('inf_big', 12):g}%) 이하 종가에 매수합니다. 사실상 거의 항상 체결됩니다.

**전반전** (T < 분할수/2) — 1회분의 절반을 별지점 LOC, 절반을 평단 LOC.

**후반전** (T ≥ 분할수/2) — 1회분 전부를 별지점 LOC.

**매도** — 보유 1/4은 별지점 LOC(쿼터매도), 나머지 3/4는 평단 +{target_pct:g}% 지정가. 종가가 목표가 이상이면 사이클 종료.

**리버스모드** — T > 분할수−1 이면 전환. 첫날은 보유량의 1/{n_split // 2}을 MOC 매도. 이후 직전 5일 종가 평균 위에서 같은 비율 매도, 아래에서 잔금/4 쿼터매수. 종가가 평단 −{target_pct:g}% 위로 오면 다음 날 일반모드 복귀(T 승계).

**단순화** — 종가만 사용합니다. 지정가 매도는 종가 ≥ 목표가일 때 목표가에 체결(장중 고가 미반영, 보수적). 하방 사다리 추가 주문은 “종가에서 금액만큼 매수”로 묶었습니다.

> ⚠️ 교육·참고용 과거 시뮬레이션이며 투자 조언이 아닙니다. 공식 방법론과 100% 같지 않을 수 있습니다.
""")


# ---------------------------------------------------------------- 사이드바
st.sidebar.header("⚙️ 백테스트 설정")
strategy = st.sidebar.radio("전략", ["돈을벌자", "무한매수법 V4"], horizontal=True,
                            help="종목 선정 전에 전략을 고릅니다. 돈을벌자는 기존 6분할 LOC 전략입니다.")
ticker = st.sidebar.selectbox("종목", ["SOXL", "TQQQ"])
c1, c2 = st.sidebar.columns(2)
start = c1.date_input("시작일", value=DATA_MIN, min_value=DATA_MIN, max_value=DATA_MAX)
end = c2.date_input("종료일", value=DATA_MAX, min_value=DATA_MIN, max_value=DATA_MAX)

initial_capital = st.sidebar.number_input(
    "초기자본 (USD)", min_value=100.0, max_value=1_000_000_000.0,
    value=10_000.0, step=1_000.0, format="%.0f",
    help="직접 입력할 수 있습니다. 기본값은 $10,000 입니다.",
)

if strategy == "돈을벌자":
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
else:
    split_label = st.sidebar.radio("분할 수", ["40분할 (안정)", "20분할 (공격적)", "30분할"], index=0)
    n_split = int(split_label[:2])
    default_tgt = 20.0 if ticker == "SOXL" else 15.0
    tgt_choice = st.sidebar.radio(
        "목표수익률 (지정가 매도)",
        ["+10%", "+15%", "+20%"],
        index={10.0: 0, 15.0: 1, 20.0: 2}[default_tgt],
        horizontal=True,
        help="평단 대비 지정가 매도 목표입니다. 공식 기본은 TQQQ +15%, SOXL +20%입니다.",
    )
    target_pct = float(tgt_choice.replace("%", "").replace("+", ""))
    if target_pct != default_tgt:
        st.sidebar.caption(f"참고: {ticker} 공식 기본값은 +{default_tgt:.0f}% 입니다.")
    with st.sidebar.expander("고급 설정"):
        fee_pct = st.number_input("편도 수수료·슬리피지 %", min_value=0.0, max_value=5.0, value=0.0, step=0.01,
                                  format="%.2f", key="inf_fee")
        compound = st.checkbox("복리 (사이클 종료 후 수익금까지 재투자)", value=True, key="inf_comp")
        big_pct = st.number_input("큰수 상한: 전일 종가 대비 +%", min_value=0.0, max_value=30.0, value=12.0, step=1.0,
                                  format="%.0f", key="inf_big",
                                  help="첫 매수·일반 매수 주문의 상한. 0이면 끔. 공식 예시는 10~15%입니다.")

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

if strategy == "무한매수법 V4":
    iparams = dict(
        ticker=ticker, start=str(start), end=str(end), capital=float(initial_capital),
        n=n_split, target_pct=float(target_pct), big_pct=float(big_pct),
        fee_pct=float(fee_pct), compound=compound,
    )
    ires, prices = infinite_backtest(iparams)
    render_infinite(ires, prices, ticker, initial_capital, n_split, target_pct, iparams)
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
