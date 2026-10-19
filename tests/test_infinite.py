import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from engine import load_prices  # noqa: E402
from infinite import IParams, run_infinite  # noqa: E402


def series(values):
    idx = pd.bdate_range("2024-01-01", periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def P(**kw):
    base = dict(ticker="TQQQ", n=20, capital=10_000.0, big_pct=0.0)
    base.update(kw)
    return IParams(**base)


class InfiniteTest(unittest.TestCase):
    def test_first_buy_at_close(self):
        r = run_infinite(series([50, 50]), P())
        e = r.events.iloc[0]
        self.assertEqual(e["kind"], "처음매수")
        self.assertEqual(e["qty"], 10)                  # 500 / 50
        self.assertAlmostEqual(r.equity["cash"].iloc[-1], 9500)
        self.assertAlmostEqual(r.equity["T"].iloc[-1], 1.0)

    def test_big_number_blocks_huge_gap(self):
        # 큰수 12%: 전일 대비 +20% 급등한 날은 처음매수 불가
        r = run_infinite(series([50, 60, 60]), P(big_pct=12.0))
        self.assertEqual(len(r.events), 1)
        self.assertEqual(r.events.iloc[0]["price"], 60)  # 두 번째 날(60 -> 60, +0%)에 매수
        self.assertEqual(r.events.iloc[0]["date"], r.equity.index[2])

    def test_quarter_sell(self):
        # T=1, 평단 50: 별%=15*(1-2/20)=13.5% -> 별지점 56.75, 목표가 57.5. 종가 57 -> 쿼터매도
        r = run_infinite(series([50, 50, 57]), P())
        e = r.events.iloc[1]
        self.assertEqual(e["kind"], "쿼터매도")
        self.assertEqual(e["qty"], 2)                    # floor(10/4)
        self.assertAlmostEqual(e["price"], 57)
        self.assertAlmostEqual(e["T_after"], 0.75)
        self.assertAlmostEqual(e["ret_pct"], 14.0)
        self.assertAlmostEqual(r.equity["cash"].iloc[-1], 9500 + 2 * 57)
        self.assertEqual(r.equity["shares"].iloc[-1], 8)

    def test_target_sell_and_cycle_end(self):
        # 종가 58 >= 목표가 57.5: 쿼터 2주는 종가 58, 나머지 8주는 목표가 57.5
        r = run_infinite(series([50, 50, 58]), P())
        self.assertEqual(list(r.events["kind"]), ["처음매수", "쿼터매도", "목표매도(지정가)"])
        t = r.events.iloc[2]
        self.assertAlmostEqual(t["price"], 57.5)
        self.assertEqual(t["qty"], 8)
        self.assertEqual(len(r.cycles), 1)
        cy = r.cycles.iloc[0]
        self.assertAlmostEqual(cy["pnl"], 2 * 8 + 8 * 7.5)           # 76
        self.assertAlmostEqual(cy["ret_pct"], 0.76)
        self.assertIsNone(r.open_cycle)
        self.assertEqual(r.equity["shares"].iloc[-1], 0)

    def test_first_half_buys(self):
        # T=1, 평단 50, 별지점 56.75 (L1=56.74), 평단 LOC 50
        # 종가 55: 별지점 절반만 체결 -> B=9500/19=500, 250/55 = 4주, T=1.5
        r = run_infinite(series([50, 50, 55]), P())
        e = r.events.iloc[1]
        self.assertEqual(e["kind"], "매수(절반·별지점)")
        self.assertEqual(e["qty"], 4)
        self.assertAlmostEqual(e["T_after"], 1.5)
        # 종가 49: 두 주문 모두 체결 -> 500/49 = 10주, T=2
        r = run_infinite(series([50, 50, 49]), P())
        e = r.events.iloc[1]
        self.assertEqual(e["kind"], "매수(1회분)")
        self.assertEqual(e["qty"], 10)
        self.assertAlmostEqual(e["T_after"], 2.0)
        # 종가 57(별지점 이상)이면 매수 없이 쿼터매도 -> 매수 이벤트 없음
        r = run_infinite(series([50, 50, 57]), P())
        self.assertNotIn("매수(1회분)", list(r.events["kind"]))

    def test_second_half_all_in_star(self):
        # 매일 1% 하락: 평단 아래라 매일 1회분 체결, T가 N/2 이상이면 후반전
        vals = [100 * 0.99 ** i for i in range(15)]
        r = run_infinite(series(vals), P())
        kinds = list(r.events["kind"])
        self.assertEqual(kinds[0], "처음매수")
        self.assertTrue(all(k == "매수(1회분)" for k in kinds[1:10]))   # T = 2 .. 10
        self.assertTrue(all(k == "매수(후반전)" for k in kinds[10:]))
        T = r.events["T_after"].tolist()
        self.assertEqual(T[:12], [float(x) for x in range(1, 13)])

    def test_reverse_mode(self):
        # 계속 하락 -> T 가 20 에 도달(>19) -> 리버스모드
        vals = [100 * 0.97 ** i for i in range(45)]       # 가파른 하락: 쿼터매도 없이 소진
        r = run_infinite(series(vals), P())
        kinds = list(r.events["kind"])
        self.assertNotIn("쿼터매도", kinds[:25])
        i_rev = kinds.index("리버스 MOC매도")
        self.assertEqual(kinds[i_rev - 1], "매수(후반전)")
        ev = r.events
        self.assertAlmostEqual(ev.iloc[i_rev - 1]["T_after"], 20.0)
        self.assertAlmostEqual(ev.iloc[i_rev]["T_after"], 20 * 0.9)      # 20분할: x0.9
        # MOC 매도 수량 = floor(보유/10)
        held_before = ev.iloc[i_rev - 1]["shares_after"]
        self.assertEqual(ev.iloc[i_rev]["qty"], max(1, int(held_before // 10)))
        # 이후 하락장에서는 리버스 쿼터매수(T + (N-T)*0.25)가 나와야 함
        later = ev.iloc[i_rev + 1:]
        qb = later[later["kind"] == "리버스 쿼터매수"]
        self.assertGreater(len(qb), 0)
        row = qb.iloc[0]
        self.assertAlmostEqual(row["T_after"], row["T_before"] + (20 - row["T_before"]) * 0.25)

    def test_reverse_returns_to_normal(self):
        # 하락 후 큰 반등: 종가 > 평단*(1-15%) 이면 다음 날부터 일반모드
        vals = [100 * 0.985 ** i for i in range(30)] + [100 * 0.985 ** 29 * 1.06 ** k for k in range(1, 15)]
        r = run_infinite(series(vals), P())
        modes = r.equity["mode"].tolist()
        self.assertIn("리버스", modes)
        i_last_rev = max(i for i, m in enumerate(modes) if m == "리버스")
        self.assertTrue(any(m == "일반" for m in modes[i_last_rev + 1:]) or modes[-1] == "대기")

    def test_not_compound_sets_aside_profit(self):
        vals = [50, 50, 58] + [50, 50, 58]
        r = run_infinite(series(vals), P(compound=False))
        self.assertEqual(len(r.cycles), 2)
        # 두 번째 사이클도 원금 10,000 기준 (수익금은 별도 보관)
        self.assertAlmostEqual(r.cycles.iloc[1]["start_cash"], 10_000)
        self.assertAlmostEqual(r.equity["equity"].iloc[-1], 10_000 + r.cycles["pnl"].sum())
        r2 = run_infinite(series(vals), P(compound=True))
        self.assertGreater(r2.cycles.iloc[1]["start_cash"], 10_000)

    def test_fee(self):
        r0 = run_infinite(series([50, 50, 58]), P())
        r1 = run_infinite(series([50, 50, 58]), P(fee_pct=0.5))
        self.assertLess(r1.cycles.iloc[0]["pnl"], r0.cycles.iloc[0]["pnl"])


class RealDataInvariants(unittest.TestCase):
    def _check(self, ticker, n, **kw):
        p = IParams(ticker=ticker, n=n, **kw)
        px = load_prices(ticker, p.start, p.end)
        r = run_infinite(px, p)
        ev, eq = r.events, r.equity
        self.assertTrue((eq["cash"] >= -1e-6).all(), "현금 음수")
        self.assertTrue((eq["shares"] >= 0).all())
        self.assertTrue((eq["T"] >= -1e-9).all() and (eq["T"] <= n + 1e-9).all(), "T 범위")
        # 이벤트 재생(replay)으로 현금·보유수량 대조
        cash, shares = p.capital, 0
        fee = p.fee_pct / 100
        for e in ev.itertuples():
            if e.pnl is None or pd.isna(e.pnl):
                cash -= e.amount
                shares += e.qty
            else:
                cash += e.amount
                shares -= e.qty
            self.assertGreaterEqual(shares, 0)
        side = eq["cash"].iloc[-1] - cash   # compound=False 일 때만 보관 현금이 다름
        if p.compound:
            self.assertAlmostEqual(cash, eq["cash"].iloc[-1], places=4)
        self.assertEqual(shares, eq["shares"].iloc[-1])
        # 목표매도 가격은 평단*(1+목표) 이어야 하고 종가는 그 이상
        tp = ev[ev["kind"] == "목표매도(지정가)"]
        for e in tp.itertuples():
            self.assertAlmostEqual(e.price, e.target_price, places=9)
        # 쿼터매도는 종가 >= 별지점
        for e in ev[ev["kind"] == "쿼터매도"].itertuples():
            self.assertGreaterEqual(e.price + 1e-9, e.star_price)
        # 하루 최대 1개 사이클만 진행, 같은 날 매수 이벤트 2건 이상 없음
        buys = ev[ev["pnl"].isna()]
        self.assertFalse(buys["date"].duplicated().any(), "하루 2회 이상 매수")
        # 사이클 수익률 합산 일관성: 최종자산 = 원금 + 실현손익 + 미청산 평가
        total_pnl = r.cycles["pnl"].sum() if len(r.cycles) else 0.0
        if r.open_cycle is None:
            self.assertAlmostEqual(eq["equity"].iloc[-1], p.capital + total_pnl, places=4)
        return r

    def test_all_combos(self):
        for t in ("TQQQ", "SOXL"):
            for n in (20, 30, 40):
                for comp in (True, False):
                    self._check(t, n, compound=comp)

    def test_with_fee_and_big_off(self):
        self._check("SOXL", 40, fee_pct=0.07, big_pct=0.0)
        self._check("TQQQ", 20, fee_pct=0.07, big_pct=20.0)


if __name__ == "__main__":
    unittest.main()
