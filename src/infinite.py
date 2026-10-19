"""무한매수법 V4.0 백테스트 엔진 (일별 종가 기준 단순화 모델, 비공식 구현).

규칙 요약 (라오어 무한매수법 V4.0, 공개된 해설 기준)
- 원금을 N분할(20/40). T = 매수 회차 누적(전체 매수 +1, 절반 매수 +0.5, 쿼터매도 x0.75).
- 1회 매수금 B = 잔금 / (N - T)
- 별% = 목표% x (1 - 2T/N)   (TQQQ 목표 15%, SOXL 20%)   별지점 = 평단 x (1 + 별%)
- 처음매수: 사이클 첫날 1회분(원금/N)을 '큰수' LOC(전일 종가 x 1.12)로 매수 -> 사실상 종가 체결
- 전반전(T < N/2): B/2 는 별지점-0.01 LOC, B/2 는 평단 LOC 매수
- 후반전(T >= N/2): B 전부 별지점-0.01 LOC 매수
- 매도: 보유 1/4(내림)은 별지점 LOC(쿼터매도, T x 0.75), 나머지 3/4 은 평단 x (1+목표%) 지정가
- 소진(T > N-1): 리버스모드
    첫날: 보유량/(N/2)(내림) MOC 매도, T x (1 - 2/N)
    이후: 리버스 별지점 R = 직전 5거래일 종가 평균
          종가 >= R  -> 보유량/(N/2) 매도, T x (1 - 2/N)
          종가 <= R-0.01 -> 잔금/4 쿼터매수, T = T + (N-T) x 0.25
          쿼터매수로 1주도 못 사면 소진으로 보고 MOC 매도
    종료: 종가 > 평단 x (1 - 목표%)  (쿼터매수 1주 가능할 때) -> 다음 날 일반모드(T 승계)

종가만 있는 데이터의 단순화
- LOC 는 조건 충족 시 '종가'로 체결. 하방 사다리(낮은 가격에 1주씩 추가 주문)는 '종가에서 금액만큼 매수'로 반영.
- 지정가(목표가) 매도: 종가 >= 목표가 이면 목표가에 체결 (장중 고가 미반영, 보수적).
- 지정가 체결 후 같은 날 급락해 LOC 매수가 체결되는 경우는 종가 기준에서 발생하지 않음.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DEFAULT_TARGET = {"TQQQ": 15.0, "SOXL": 20.0}


@dataclass
class IParams:
    ticker: str = "TQQQ"
    start: str = "2020-01-01"
    end: str = "2026-10-15"
    capital: float = 10_000.0
    n: int = 40                      # 분할 수 (20 | 40)
    target_pct: float | None = None  # None 이면 종목 기본값 (TQQQ 15, SOXL 20)
    big_pct: float = 12.0            # 큰수 %: 전일 종가 x (1+%) 보다 높은 가격에는 매수 주문을 넣지 않음. 0 이면 끔
    fee_pct: float = 0.0             # 편도 수수료·슬리피지 %
    compound: bool = True            # True: 수익 재투자(복리). False: 사이클마다 원금 초과분은 따로 보관

    def target(self) -> float:
        return self.target_pct if self.target_pct is not None else DEFAULT_TARGET[self.ticker]


@dataclass
class IResult:
    params: IParams
    events: pd.DataFrame
    cycles: pd.DataFrame
    equity: pd.DataFrame
    open_cycle: dict | None
    metrics: dict = field(default_factory=dict)


def _floor(x: float) -> int:
    return int(math.floor(x + 1e-9))


def run_infinite(prices: pd.Series, p: IParams) -> IResult:
    dates = prices.index
    close = prices.to_numpy(dtype=float)
    n_days = len(close)
    N = p.n
    tgt = p.target() / 100.0
    fee = p.fee_pct / 100.0
    big = p.big_pct / 100.0

    cash = p.capital
    side_cash = 0.0
    shares = 0
    cost_total = 0.0          # 보유 주식 취득원가 합 (평단 = cost_total / shares)
    T = 0.0
    mode = "normal"
    rev_first = False
    cyc = None                # 진행 중 사이클
    cyc_no = 0

    events: list[dict] = []
    cycles: list[dict] = []
    eq_rows = [{"date": dates[0], "cash": cash, "holdings": 0.0, "equity": cash, "T": 0.0,
                "mode": "대기", "shares": 0, "avg": np.nan}]

    def log(i, kind, price, qty, amount, T_before, T_after, pnl=None, ret=None, star=None, S=None, G=None):
        avg_after = cost_total / shares if shares > 0 else np.nan
        events.append({
            "date": dates[i], "cycle": cyc_no, "mode": "리버스" if mode == "reverse" else "일반",
            "kind": kind, "price": price, "qty": qty, "amount": amount,
            "T_before": T_before, "T_after": T_after,
            "star_pct": star, "star_price": S, "target_price": G,
            "avg_after": avg_after, "shares_after": shares, "cash_after": cash,
            "pnl": pnl, "ret_pct": ret,
        })

    def buy(i, price, amount, kind, T_before, T_after, star=None, S=None, G=None):
        nonlocal cash, shares, cost_total
        unit = price * (1 + fee)
        qty = _floor(min(amount, cash) / unit)
        if qty < 1:
            return False
        cost = qty * unit
        cash -= cost
        shares += qty
        cost_total += cost
        log(i, kind, price, qty, cost, T_before, T_after, star=star, S=S, G=G,
            ret=(close[i] / (cost_total / shares) - 1) * 100)
        return True

    def sell(i, price, qty, kind, T_before, T_after, star=None, S=None, G=None):
        nonlocal cash, shares, cost_total
        qty = min(qty, shares)
        if qty < 1:
            return 0
        avg = cost_total / shares
        proceeds = qty * price * (1 - fee)
        pnl = proceeds - qty * avg
        cash += proceeds
        shares -= qty
        cost_total = avg * shares if shares > 0 else 0.0
        log(i, kind, price, qty, proceeds, T_before, T_after, pnl=pnl, ret=(price * (1 - fee) / avg - 1) * 100,
            star=star, S=S, G=G)
        return qty

    def close_cycle(i):
        nonlocal cyc, cash, side_cash, T, mode, rev_first
        total_now = cash + side_cash
        pnl = total_now - cyc["start_total"]
        cycles.append({
            "cycle": cyc_no, "start": cyc["start_date"], "end": dates[i],
            "days": i - cyc["start_idx"], "start_cash": cyc["start_cash"],
            "pnl": pnl, "ret_pct": pnl / cyc["start_cash"] * 100,
            "max_T": cyc["max_T"], "reverse_used": cyc["reverse_used"], "reverse_days": cyc["reverse_days"],
        })
        if not p.compound and cash > p.capital:
            side_cash += cash - p.capital
            cash = p.capital
        cyc = None
        T = 0.0
        mode = "normal"
        rev_first = False

    for i in range(1, n_days):
        c = close[i]
        pv = close[i - 1]
        cap = pv * (1 + big) if big > 0 else float("inf")   # 큰수 상한

        if shares == 0:
            # ---------------- 사이클 시작: 처음매수 ----------------
            B = cash / N
            if c <= cap:
                cyc_no_next = cyc_no + 1
                start_cash, start_total = cash, cash + side_cash
                qty_ok = _floor(min(B, cash) / (c * (1 + fee))) >= 1
                if qty_ok:
                    cyc_no = cyc_no_next
                    cyc = {"start_idx": i, "start_date": dates[i], "start_cash": start_cash,
                           "start_total": start_total, "max_T": 0.0, "reverse_used": False, "reverse_days": 0}
                    buy(i, c, B, "처음매수", 0.0, 1.0)
                    T = 1.0
                    cyc["max_T"] = T
        else:
            if mode == "normal" and T > N - 1 + 1e-9:
                mode = "reverse"
                rev_first = True
                cyc["reverse_used"] = True

            avg = cost_total / shares
            if mode == "normal":
                star = tgt * (1 - 2 * T / N)
                S = avg * (1 + star)
                G = avg * (1 + tgt)
                q = shares // 4
                T0 = T
                if c >= G:
                    # 쿼터매도(LOC, 종가) + 나머지 지정가(목표가) -> 사이클 종료
                    if q >= 1:
                        sell(i, c, q, "쿼터매도", T0, T0 * 0.75, star * 100, S, G)
                    sell(i, G, shares, "목표매도(지정가)", T0 * 0.75 if q >= 1 else T0, 0.0, star * 100, S, G)
                    close_cycle(i)
                elif c >= S and q >= 1:
                    T = T0 * 0.75
                    sell(i, c, q, "쿼터매도", T0, T, star * 100, S, G)
                else:
                    B = cash / (N - T)
                    if T < N / 2:                                   # 전반전
                        L1 = min(S - 0.01, cap)
                        L2 = min(avg, cap)
                        fills = int(c <= L1) + int(c <= L2)
                        if fills:
                            amount = B * fills / 2
                            kind = "매수(1회분)" if fills == 2 else ("매수(절반·별지점)" if c <= L1 else "매수(절반·평단)")
                            if _floor(min(amount, cash) / (c * (1 + fee))) >= 1:
                                T = T0 + 0.5 * fills
                                buy(i, c, amount, kind, T0, T, star * 100, S, G)
                    else:                                           # 후반전
                        L = min(S - 0.01, cap)
                        if c <= L and _floor(min(B, cash) / (c * (1 + fee))) >= 1:
                            T = T0 + 1.0
                            buy(i, c, B, "매수(후반전)", T0, T, star * 100, S, G)
                    if cyc is not None:
                        cyc["max_T"] = max(cyc["max_T"], T)
            else:
                # ---------------- 리버스모드 ----------------
                cyc["reverse_days"] += 1
                T0 = T
                half = N / 2
                sell_qty = max(1, _floor(shares / half))
                hist = close[max(0, i - 5):i]
                R = float(np.mean(hist))
                exhausted = cash / 4 < (R - 0.01) * (1 + fee)
                factor = 1 - 2 / N
                if rev_first or exhausted:
                    T = T0 * factor
                    sell(i, c, sell_qty, "리버스 MOC매도", T0, T)
                    rev_first = False
                elif c >= R:
                    T = T0 * factor
                    sell(i, c, sell_qty, "리버스 매도", T0, T)
                elif c <= R - 0.01:
                    T = T0 + (N - T0) * 0.25
                    if not buy(i, c, cash / 4, "리버스 쿼터매수", T0, T):
                        T = T0
                if shares == 0:
                    close_cycle(i)
                else:
                    avg2 = cost_total / shares
                    can_q = _floor((cash / 4) / (c * (1 + fee))) >= 1
                    if c > avg2 * (1 - tgt) and can_q:
                        mode = "normal"          # 다음 날부터 일반모드 (T 승계)

        holdings = shares * c
        mode_label = "대기" if shares == 0 else ("리버스" if mode == "reverse" else "일반")
        eq_rows.append({"date": dates[i], "cash": cash + side_cash, "holdings": holdings,
                        "equity": cash + side_cash + holdings, "T": T if shares > 0 else 0.0,
                        "mode": mode_label, "shares": shares,
                        "avg": cost_total / shares if shares > 0 else np.nan})

    ev = pd.DataFrame(events)
    cy = pd.DataFrame(cycles)
    eq = pd.DataFrame(eq_rows).set_index("date")
    open_cycle = None
    if cyc is not None and shares > 0:
        avg = cost_total / shares
        total_now = cash + side_cash + shares * close[-1]
        open_cycle = {
            "cycle": cyc_no, "start": cyc["start_date"], "days": n_days - 1 - cyc["start_idx"],
            "T": T, "mode": "리버스" if mode == "reverse" else "일반", "shares": shares, "avg": avg,
            "last_close": close[-1], "unrealized_pct": (close[-1] / avg - 1) * 100,
            "equity_ret_pct": (total_now / cyc["start_total"] - 1) * 100,
            "max_T": cyc["max_T"], "reverse_used": cyc["reverse_used"],
        }
    res = IResult(p, ev, cy, eq, open_cycle)
    res.metrics = compute_metrics(res, prices)
    return res


def compute_metrics(res: IResult, prices: pd.Series) -> dict:
    p = res.params
    eq = res.equity["equity"]
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    total = eq.iloc[-1] / p.capital - 1
    cagr = (eq.iloc[-1] / p.capital) ** (1 / years) - 1
    mdd = (eq / eq.cummax() - 1).min()
    bh = prices / prices.iloc[0] * p.capital
    cy = res.cycles
    ev = res.events
    n_cyc = len(cy)
    sells = ev[ev["pnl"].notna()] if len(ev) else ev
    return {
        "기간 시작": eq.index[0].date(), "기간 종료": eq.index[-1].date(),
        "최종 자산": float(eq.iloc[-1]),
        "총 수익률(%)": total * 100,
        "연환산 수익률 CAGR(%)": cagr * 100,
        "최대 낙폭 MDD(%)": mdd * 100,
        "완료 사이클 수": n_cyc,
        "사이클 승률(%)": float((cy["pnl"] > 0).mean() * 100) if n_cyc else 0.0,
        "사이클 평균 수익률(%)": float(cy["ret_pct"].mean()) if n_cyc else 0.0,
        "사이클 최저 수익률(%)": float(cy["ret_pct"].min()) if n_cyc else 0.0,
        "사이클 평균 소요일": float(cy["days"].mean()) if n_cyc else 0.0,
        "리버스 경험 사이클": int(cy["reverse_used"].sum()) if n_cyc else 0,
        "매수 체결 수": int((ev["pnl"].isna()).sum()) if len(ev) else 0,
        "매도 체결 수": int(len(sells)),
        "최대 T": float(res.equity["T"].max()),
        "미청산 사이클": 1 if res.open_cycle else 0,
        "Buy&Hold 수익률(%)": (bh.iloc[-1] / p.capital - 1) * 100,
        "Buy&Hold MDD(%)": ((bh / bh.cummax() - 1).min()) * 100,
    }
