"""떨사오팔 Pro3 백테스트 엔진 (LOC 전용, 종가 체결).

규칙 요약
- 6분할(기본). 하루 최대 1건 신규 매수.
- 매수 LOC: 종가 <= 전일종가 * (1 - buy_drop_pct%) 이면 '종가'에 체결.
- 매도 LOC: 티어별 진입가 * (1 + tp_pct%) 이상 종가면 '종가'에 체결 (진입 당일은 매도 불가).
- 타임컷: 진입 후 timecut_days 거래일째 종가에 무조건 매도(미체결 시 손절).
  타임컷 당일 비는 티어는 같은 날 신규 매수 조건(-0.10%)을 충족하면 매수 가능.
- 익절로 비는 티어는 다음 거래일부터 매수 가능(당일 매수 주문은 장 시작 전 확정되므로).
- 같은 날 청산 현금은 같은 날 매수에 사용 가능(종가 동시 체결 가정).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

EQUAL_WEIGHTS = [1 / 6] * 6
TIERED_WEIGHTS = [0.10, 0.15, 0.20, 0.25, 0.15, 0.10]


@dataclass
class Params:
    ticker: str = "SOXL"
    start: str = "2020-01-01"
    end: str = "2026-10-15"
    initial_capital: float = 10_000.0
    entry_mode: str = "equal"        # 'equal'(16.7% 균등) | 'tiered'(10/15/20/25/15/10) | 'custom'(직접 입력)
    custom_weights: tuple | None = None  # entry_mode='custom' 일 때 6개 비중(%), 예: (10, 15, 20, 25, 15, 10)
    tp_pct: float = 2.0              # 익절 % (0.01 / 1.0 / 2.0 등)
    timecut_days: int = 10           # 10 또는 12
    buy_drop_pct: float = 0.10       # 전일종가 대비 하락 % (매수 기준)
    fee_pct: float = 0.0             # 편도 수수료/슬리피지 %
    compound: bool = False           # True: 분할 금액을 직전 총자산 기준으로 재계산
    fractional: bool = False         # True: 소수점 주식 허용
    n_slots: int = 6

    def weights(self) -> list[float]:
        if self.entry_mode == "custom":
            cw = list(self.custom_weights or [])
            if len(cw) != self.n_slots:
                raise ValueError(f"직접 입력은 비중 {self.n_slots}개가 필요합니다 (입력 {len(cw)}개)")
            if any(x <= 0 for x in cw):
                raise ValueError("각 비중은 0보다 커야 합니다")
            if sum(cw) > 100 + 1e-6:
                raise ValueError(f"비중 합계가 100%를 넘습니다 ({sum(cw):.2f}%)")
            return [x / 100 for x in cw]
        w = EQUAL_WEIGHTS if self.entry_mode == "equal" else TIERED_WEIGHTS
        if len(w) != self.n_slots:
            if self.entry_mode == "equal":
                w = [1 / self.n_slots] * self.n_slots
            else:
                raise ValueError("차등 진입은 n_slots=6 에서만 지원")
        return w


@dataclass
class Result:
    params: Params
    trades: pd.DataFrame
    open_positions: pd.DataFrame
    equity: pd.DataFrame
    metrics: dict = field(default_factory=dict)


def load_prices(ticker: str, start: str | None = None, end: str | None = None) -> pd.Series:
    df = pd.read_csv(DATA_DIR / f"{ticker.lower()}.csv", parse_dates=["date"], index_col="date")
    s = df["close"].astype(float)
    if start:
        s = s[s.index >= pd.Timestamp(start)]
    if end:
        s = s[s.index <= pd.Timestamp(end)]
    return s


def run_backtest(prices: pd.Series, p: Params) -> Result:
    dates = prices.index
    close = prices.to_numpy(dtype=float)
    n = len(close)
    weights = p.weights()
    fee = p.fee_pct / 100.0
    drop = p.buy_drop_pct / 100.0
    tp = p.tp_pct / 100.0

    cash = p.initial_capital
    positions: list[dict] = []  # slot, entry_idx, entry_price, shares, buy_cost, target
    trades: list[dict] = []
    eq_rows: list[dict] = []

    eq_rows.append({"date": dates[0], "cash": cash, "holdings": 0.0, "equity": cash, "open_positions": 0})
    prev_equity = cash

    for i in range(1, n):
        c = close[i]
        prev = close[i - 1]

        # 장 시작 전 확정되는 매수 가능 슬롯 수
        free_at_open = p.n_slots - len(positions)
        timecut_today = sum(1 for pos in positions if i - pos["entry_idx"] >= p.timecut_days)
        buy_allowed = (free_at_open + timecut_today) > 0

        # --- 매도 (LOC) ---
        remaining = []
        for pos in positions:
            age = i - pos["entry_idx"]
            hit_tp = c >= pos["target"]
            if hit_tp or age >= p.timecut_days:
                proceeds = pos["shares"] * c * (1 - fee)
                cash += proceeds
                trades.append({
                    "ticker": p.ticker,
                    "slot": pos["slot"] + 1,
                    "entry_date": dates[pos["entry_idx"]],
                    "entry_price": pos["entry_price"],
                    "exit_date": dates[i],
                    "exit_price": c,
                    "shares": pos["shares"],
                    "hold_days": age,
                    "reason": "익절" if hit_tp else "타임컷",
                    "pnl": proceeds - pos["buy_cost"],
                    "return_pct": (proceeds / pos["buy_cost"] - 1) * 100,
                })
            else:
                remaining.append(pos)
        positions = remaining

        # --- 매수 (LOC, 하루 최대 1건) ---
        if buy_allowed and c <= prev * (1 - drop):
            used = {pos["slot"] for pos in positions}
            slot = next((s for s in range(p.n_slots) if s not in used), None)
            if slot is not None:
                base = prev_equity if p.compound else p.initial_capital
                amount = min(base * weights[slot], cash)
                unit = c * (1 + fee)
                # 1e-9: 부동소수점 오차로 정확히 나누어떨어지는 수량이 1주 모자라게 계산되는 것 방지
                shares = amount / unit if p.fractional else float(np.floor(amount / unit + 1e-9))
                if shares > 0:
                    cost = min(shares * unit, cash)
                    cash -= cost
                    positions.append({
                        "slot": slot,
                        "entry_idx": i,
                        "entry_price": c,
                        "shares": shares,
                        "buy_cost": cost,
                        "target": c * (1 + tp),
                    })

        holdings = sum(pos["shares"] * c for pos in positions)
        equity = cash + holdings
        prev_equity = equity
        eq_rows.append({"date": dates[i], "cash": cash, "holdings": holdings,
                        "equity": equity, "open_positions": len(positions)})

    trades_df = pd.DataFrame(trades)
    open_df = pd.DataFrame([{
        "slot": pos["slot"] + 1,
        "entry_date": dates[pos["entry_idx"]],
        "entry_price": pos["entry_price"],
        "shares": pos["shares"],
        "hold_days": n - 1 - pos["entry_idx"],
        "last_close": close[-1],
        "unrealized_pct": (close[-1] * pos["shares"] / pos["buy_cost"] - 1) * 100,
    } for pos in positions])
    equity_df = pd.DataFrame(eq_rows).set_index("date")

    res = Result(p, trades_df, open_df, equity_df)
    res.metrics = compute_metrics(res, prices)
    return res


def compute_metrics(res: Result, prices: pd.Series) -> dict:
    p = res.params
    eq = res.equity["equity"]
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    total = eq.iloc[-1] / p.initial_capital - 1
    cagr = (eq.iloc[-1] / p.initial_capital) ** (1 / years) - 1
    mdd = (eq / eq.cummax() - 1).min()

    # Buy & Hold (첫날 종가 전액 매수)
    bh = prices / prices.iloc[0] * p.initial_capital
    bh_total = bh.iloc[-1] / p.initial_capital - 1
    bh_mdd = (bh / bh.cummax() - 1).min()

    t = res.trades
    if len(t):
        win_rate = (t["pnl"] > 0).mean()
        timecut_ratio = (t["reason"] == "타임컷").mean()
        avg_hold = t["hold_days"].mean()
        avg_ret = t["return_pct"].mean()
        realized = t["pnl"].sum()
    else:
        win_rate = timecut_ratio = avg_hold = avg_ret = realized = 0.0

    return {
        "기간 시작": eq.index[0].date(),
        "기간 종료": eq.index[-1].date(),
        "최종 자산": float(eq.iloc[-1]),
        "총 수익률(%)": total * 100,
        "연환산 수익률 CAGR(%)": cagr * 100,
        "최대 낙폭 MDD(%)": mdd * 100,
        "총 거래 수(청산)": int(len(t)),
        "승률(%)": win_rate * 100,
        "타임컷 비율(%)": timecut_ratio * 100,
        "평균 보유일": avg_hold,
        "건당 평균 수익률(%)": avg_ret,
        "실현 손익": realized,
        "미청산 포지션": int(len(res.open_positions)),
        "Buy&Hold 수익률(%)": bh_total * 100,
        "Buy&Hold MDD(%)": bh_mdd * 100,
    }


def run(**kwargs) -> Result:
    p = Params(**kwargs)
    prices = load_prices(p.ticker, p.start, p.end)
    return run_backtest(prices, p)
