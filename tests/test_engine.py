import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from engine import Params, run_backtest  # noqa: E402


def series(values):
    idx = pd.bdate_range("2024-01-01", periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


class EngineTest(unittest.TestCase):
    def test_buy_then_take_profit_at_close(self):
        # day1: 99.8 <= 100*0.999 -> 매수. target=99.8*1.01=100.798. day2 종가 101 -> 종가 101 매도
        r = run_backtest(series([100, 99.8, 101]), Params(tp_pct=1.0, timecut_days=10, fractional=True))
        self.assertEqual(len(r.trades), 1)
        t = r.trades.iloc[0]
        self.assertEqual(t["reason"], "익절")
        self.assertAlmostEqual(t["entry_price"], 99.8)
        self.assertAlmostEqual(t["exit_price"], 101)
        self.assertEqual(t["hold_days"], 1)

    def test_no_buy_without_drop(self):
        r = run_backtest(series([100, 100, 100.05, 101]), Params())
        self.assertEqual(len(r.trades), 0)
        self.assertEqual(len(r.open_positions), 0)

    def test_buy_threshold_is_inclusive(self):
        # 정확히 -0.10% (부동소수 오차 피하려고 큰 값 사용)
        r = run_backtest(series([1000, 999, 999]), Params(tp_pct=50, fractional=True))
        self.assertEqual(len(r.open_positions), 1)

    def test_no_sale_on_entry_day(self):
        # 진입일 종가가 곧 진입가 -> 같은 날 매도 없음
        r = run_backtest(series([100, 99.8]), Params(tp_pct=0.01))
        self.assertEqual(len(r.trades), 0)
        self.assertEqual(len(r.open_positions), 1)

    def test_timecut_and_same_day_rebuy(self):
        # n_slots=1: 타임컷 당일 비는 슬롯으로 신규 매수 가능해야 함
        # idx1 매수 99 / idx2,3 보합 / idx4 age=3 -> 타임컷 98에 매도, 98 <= 99*0.999 이므로 재매수
        r = run_backtest(series([100, 99, 99, 99, 98]),
                         Params(tp_pct=2.0, timecut_days=3, n_slots=1, fractional=True))
        self.assertEqual(len(r.trades), 1)
        t = r.trades.iloc[0]
        self.assertEqual(t["reason"], "타임컷")
        self.assertEqual(t["hold_days"], 3)
        self.assertAlmostEqual(t["exit_price"], 98)
        self.assertEqual(len(r.open_positions), 1)
        self.assertAlmostEqual(r.open_positions.iloc[0]["entry_price"], 98)

    def test_tp_frees_slot_only_next_day(self):
        # n_slots=1: idx1 매수 99.8(target 100.798). idx2 종가 98 은 타임컷 아님,
        # 익절도 아님 -> 보유 유지, 매수 불가. 별도로 익절 당일 재매수 불가 확인
        r = run_backtest(series([100, 99.8, 101, 100.95, 99.0]),
                         Params(tp_pct=1.0, timecut_days=10, n_slots=1, fractional=True))
        # idx2 익절(101). idx3 100.95 > 101*0.999(=100.899) -> 매수 X.
        # idx4 99.0 <= 100.95*0.999 -> 매수
        self.assertEqual(len(r.trades), 1)
        self.assertEqual(len(r.open_positions), 1)
        self.assertAlmostEqual(r.open_positions.iloc[0]["entry_price"], 99.0)

        r2 = run_backtest(series([100, 99.8, 101, 100.8]),
                          Params(tp_pct=1.0, timecut_days=10, n_slots=1, fractional=True))
        # idx3 100.8 <= 100.899 -> 익절 다음 날 매수 가능
        self.assertEqual(len(r2.open_positions), 1)
        self.assertAlmostEqual(r2.open_positions.iloc[0]["entry_price"], 100.8)

    def test_tp_day_no_same_day_buy_even_if_drop(self):
        # target 도달 + 전일 대비 하락 동시 충족: idx1 매수 90, idx2 종가 95(익절, +5.5%) 상승이라 하락 불가
        # 대신 tp를 음수로 줘서 '익절 + 하락' 동시 발생 상황을 만든다 (tp=-10%: target=81)
        r = run_backtest(series([100, 90, 89]),
                         Params(tp_pct=-10.0, timecut_days=10, n_slots=1, fractional=True))
        # idx2: 89 >= 81 익절 + 89 <= 90*0.999 하락. 슬롯은 장 시작 시 점유 -> 당일 매수 불가
        self.assertEqual(len(r.trades), 1)
        self.assertEqual(r.trades.iloc[0]["reason"], "익절")
        self.assertEqual(len(r.open_positions), 0)

    def test_max_slots_and_one_buy_per_day(self):
        vals = [100 * 0.99 ** i for i in range(10)]
        r = run_backtest(series(vals), Params(tp_pct=50, timecut_days=100, fractional=True))
        self.assertEqual(len(r.open_positions), 6)
        self.assertEqual(r.equity["open_positions"].tolist()[:8], [0, 1, 2, 3, 4, 5, 6, 6])

    def test_tiered_amounts(self):
        r = run_backtest(series([100, 90, 80]),
                         Params(entry_mode="tiered", tp_pct=50, timecut_days=100,
                                initial_capital=10_000, fractional=True))
        o = r.open_positions.set_index("slot")
        self.assertAlmostEqual(o.loc[1, "shares"] * o.loc[1, "entry_price"], 1000)  # 10%
        self.assertAlmostEqual(o.loc[2, "shares"] * o.loc[2, "entry_price"], 1500)  # 15%

    def test_custom_amounts(self):
        r = run_backtest(series([100, 90, 80, 70]),
                         Params(entry_mode="custom", custom_weights=(5, 30, 10, 20, 15, 20),
                                tp_pct=50, timecut_days=100, initial_capital=10_000, fractional=True))
        o = r.open_positions.set_index("slot")
        for slot, pct in ((1, 5), (2, 30), (3, 10)):
            self.assertAlmostEqual(o.loc[slot, "shares"] * o.loc[slot, "entry_price"], 100 * pct)

    def test_custom_equals_tiered_when_same_values(self):
        import numpy as np
        rng = np.random.default_rng(0)
        vals = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, 400)))
        a = run_backtest(series(vals), Params(entry_mode="tiered"))
        b = run_backtest(series(vals), Params(entry_mode="custom", custom_weights=(10, 15, 20, 25, 15, 10)))
        pd.testing.assert_frame_equal(a.trades, b.trades)
        self.assertAlmostEqual(a.metrics["최종 자산"], b.metrics["최종 자산"])

    def test_custom_validation(self):
        s = series([100, 99])
        with self.assertRaises(ValueError):
            run_backtest(s, Params(entry_mode="custom", custom_weights=(20, 20, 20, 20, 20, 20)))  # 120%
        with self.assertRaises(ValueError):
            run_backtest(s, Params(entry_mode="custom", custom_weights=(10, 10, 10)))              # 개수
        with self.assertRaises(ValueError):
            run_backtest(s, Params(entry_mode="custom", custom_weights=(0, 20, 20, 20, 20, 20)))   # 0%
        run_backtest(s, Params(entry_mode="custom", custom_weights=(50, 10, 10, 10, 10, 10)))      # 100% OK

    def test_exact_division_not_short_by_float_error(self):
        # $4,000 / $6.40 = 정확히 625주 (부동소수점 오차로 624주가 되면 안 됨)
        r = run_backtest(series([7.0, 6.4]),
                         Params(entry_mode="custom", custom_weights=(40, 10, 10, 10, 10, 20),
                                tp_pct=50, timecut_days=100, initial_capital=10_000))
        self.assertEqual(r.open_positions.iloc[0]["shares"], 625)

    def test_integer_shares(self):
        r = run_backtest(series([100, 99]), Params(initial_capital=10_000, tp_pct=50))
        # 10000/6 = 1666.67 / 99 = 16.8 -> 16주
        self.assertEqual(r.open_positions.iloc[0]["shares"], 16)

    def test_fee_applied_both_sides(self):
        r = run_backtest(series([100, 99, 110]),
                         Params(tp_pct=1.0, fee_pct=1.0, fractional=True))
        t = r.trades.iloc[0]
        gross = 110 / 99 - 1
        expected = (110 * 0.99) / (99 * 1.01) - 1
        self.assertAlmostEqual(t["return_pct"] / 100, expected, places=9)
        self.assertLess(expected, gross)

    def test_cash_never_negative(self):
        vals = [100 * 0.98 ** i for i in range(30)]
        r = run_backtest(series(vals), Params(tp_pct=50, timecut_days=100, entry_mode="tiered"))
        self.assertTrue((r.equity["cash"] >= -1e-9).all())

    def test_equity_consistency(self):
        # 모든 거래 청산 후(미청산 없음) 최종자산 = 초기자본 + 실현손익
        r = run_backtest(series([100, 99, 101, 99, 101]),
                         Params(tp_pct=1.0, fractional=True, timecut_days=10))
        if len(r.open_positions) == 0:
            self.assertAlmostEqual(r.equity["equity"].iloc[-1],
                                   r.params.initial_capital + r.trades["pnl"].sum())


if __name__ == "__main__":
    unittest.main()
