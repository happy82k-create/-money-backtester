"""실데이터 거래 검증.

1) 불변 조건 검사: 엔진 결과를 원본 CSV 종가와 대조
2) 독립 재구현(규칙 문장 그대로, 엔진 코드와 별개)과 거래 목록 비교
3) 대표 사례 출력 (손계산 대조용)
"""
import itertools
import sys

import pandas as pd

from engine import Params, load_prices, run_backtest

TOL = 1e-9


# ----------------------------------------------------------------- 독립 재구현
def reference_sim(close: pd.Series, p: Params):
    """'장 시작 전 주문 세팅 -> 종가 체결' 모델을 문장 그대로 구현 (정수 주식)."""
    px = list(close.values)
    dt = list(close.index)
    w = p.weights()
    cash = p.initial_capital
    lots = []      # dict(i, price, qty, cost, slot)
    done = []      # (entry_date, exit_date, qty, entry, exit, reason)
    for day in range(1, len(px)):
        today, yday = px[day], px[day - 1]
        # --- 장 시작 전: 오늘 낼 주문 확정 ---
        sell_orders = []
        for lot in lots:
            age = day - lot["i"]
            if age >= p.timecut_days:
                sell_orders.append((lot, "타임컷"))   # 한도 0 LOC: 반드시 체결
            else:
                sell_orders.append((lot, "익절"))     # 익절가 LOC
        timecut_n = sum(1 for _, r in sell_orders if r == "타임컷")
        want_buy = (len(lots) < p.n_slots) or timecut_n > 0
        buy_limit = yday * (1 - p.buy_drop_pct / 100)
        # --- 장 마감: 체결 판정 ---
        for lot, kind in sell_orders:
            tp_price = lot["price"] * (1 + p.tp_pct / 100)
            if kind == "타임컷" or today >= tp_price:
                reason = "익절" if today >= tp_price else "타임컷"
                cash += lot["qty"] * today
                done.append((dt[lot["i"]], dt[day], lot["qty"], lot["price"], today, reason))
                lots.remove(lot)
        if want_buy and today <= buy_limit:
            taken = {l["slot"] for l in lots}
            slot = min(s for s in range(p.n_slots) if s not in taken)
            budget = min(p.initial_capital * w[slot], cash)
            qty = int((budget + 1e-9) // today)
            if qty > 0:
                cash -= qty * today
                lots.append(dict(i=day, price=today, qty=qty, cost=qty * today, slot=slot))
    return done, lots


# ----------------------------------------------------------------- 불변 조건
def check_invariants(res, close: pd.Series, p: Params) -> list[str]:
    errs = []
    t = res.trades
    idx = {d: k for k, d in enumerate(close.index)}
    for r in t.itertuples():
        e_i, x_i = idx[r.entry_date], idx[r.exit_date]
        if abs(close.iloc[e_i] - r.entry_price) > TOL:
            errs.append(f"진입가≠종가 {r.entry_date.date()}")
        if abs(close.iloc[x_i] - r.exit_price) > TOL:
            errs.append(f"청산가≠종가 {r.exit_date.date()}")
        if close.iloc[e_i] > close.iloc[e_i - 1] * (1 - p.buy_drop_pct / 100) + TOL:
            errs.append(f"매수 조건 위반 {r.entry_date.date()}")
        target = r.entry_price * (1 + p.tp_pct / 100)
        if r.hold_days != x_i - e_i:
            errs.append(f"보유일 불일치 {r.entry_date.date()}")
        if r.reason == "익절":
            if r.exit_price < target - TOL or r.hold_days < 1 or r.hold_days > p.timecut_days:
                errs.append(f"익절 조건 위반 {r.entry_date.date()}")
        else:
            if r.hold_days != p.timecut_days or r.exit_price >= target:
                errs.append(f"타임컷 조건 위반 {r.entry_date.date()}")
    # 하루 1건 매수 / 동시 보유 최대 6
    entries = pd.concat([t["entry_date"], res.open_positions["entry_date"]]) if len(res.open_positions) else t["entry_date"]
    if entries.duplicated().any():
        errs.append("하루 2건 이상 매수")
    if res.equity["open_positions"].max() > p.n_slots:
        errs.append("동시 보유 6 초과")
    if (res.equity["cash"] < -TOL).any():
        errs.append("현금 음수")
    # 놓친 매수 검사: 조건 충족 + 장전 빈 슬롯(또는 타임컷 예정) + 현금 충분 인데 매수 안 함
    all_entries = set(pd.to_datetime(entries))
    ex = res.trades[["entry_date", "exit_date"]].copy()
    if len(res.open_positions):
        o = res.open_positions[["entry_date"]].copy()
        o["exit_date"] = pd.NaT
        ex = pd.concat([ex, o])
    for i in range(1, len(close)):
        d = close.index[i]
        if close.iloc[i] > close.iloc[i - 1] * (1 - p.buy_drop_pct / 100):
            continue
        held = ex[(ex["entry_date"] < d) & (ex["exit_date"].isna() | (ex["exit_date"] >= d))]
        n_open_at_start = len(held)
        n_timecut = sum(1 for r in held.itertuples() if close.index.get_loc(d) - idx[r.entry_date] >= p.timecut_days)
        if (n_open_at_start < p.n_slots or n_timecut > 0) and d not in all_entries:
            eq_cash = res.equity["cash"].iloc[i - 1]
            # 현금 부족 또는 1주도 못 사는 경우는 정상
            budget_min = min(p.initial_capital * min(p.weights()), eq_cash)
            if budget_min >= close.iloc[i] * 1.0:
                errs.append(f"놓친 매수 {d.date()}")
    return errs


def compare_with_reference(res, close, p) -> list[str]:
    done, open_lots = reference_sim(close, p)
    eng = [(r.entry_date, r.exit_date, int(r.shares), r.entry_price, r.exit_price, r.reason)
           for r in res.trades.itertuples()]
    ref = sorted(done, key=lambda x: (x[1], x[0]))
    eng_s = sorted(eng, key=lambda x: (x[1], x[0]))
    errs = []
    if len(ref) != len(eng_s):
        errs.append(f"거래 수 불일치 엔진 {len(eng_s)} / 재구현 {len(ref)}")
    for a, b in zip(eng_s, ref):
        if a[:3] != b[:3] or a[5] != b[5] or abs(a[3] - b[3]) > TOL or abs(a[4] - b[4]) > TOL:
            errs.append(f"거래 불일치 {a} vs {b}")
            break
    if len(open_lots) != len(res.open_positions):
        errs.append(f"미청산 수 불일치 {len(res.open_positions)} / {len(open_lots)}")
    return errs


def main():
    total_fail = 0
    n = 0
    for ticker, mode, tp, tc in itertools.product(["SOXL", "TQQQ"], ["equal", "tiered"], [0.01, 1.0, 2.0], [10, 12]):
        p = Params(ticker=ticker, entry_mode=mode, tp_pct=tp, timecut_days=tc)
        close = load_prices(ticker, p.start, p.end)
        res = run_backtest(close, p)
        errs = check_invariants(res, close, p) + compare_with_reference(res, close, p)
        n += 1
        status = "OK " if not errs else "FAIL"
        print(f"[{status}] {ticker} {mode:6s} tp={tp:<4} tc={tc:2d} 거래 {len(res.trades)}건"
              + ("" if not errs else f" -> {errs[:3]}"))
        total_fail += bool(errs)
    print(f"\n조합 {n}개 중 실패 {total_fail}개")
    return total_fail


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
