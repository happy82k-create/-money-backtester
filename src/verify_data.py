"""저장된 CSV 검증 리포트."""
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def report(name: str) -> None:
    df = pd.read_csv(DATA_DIR / f"{name}.csv", parse_dates=["date"], index_col="date")
    s = df["close"]
    ret = s.pct_change().dropna()
    gaps = df.index.to_series().diff().dt.days.dropna()
    print(f"=== {name.upper()} ===")
    print(f"행 수: {len(s)}  기간: {s.index.min().date()} ~ {s.index.max().date()}")
    print(f"결측: {s.isna().sum()}  중복 날짜: {s.index.duplicated().sum()}  0 이하 가격: {(s <= 0).sum()}")
    print(f"종가 최소 {s.min():.2f} ({s.idxmin().date()}) / 최대 {s.max():.2f} ({s.idxmax().date()})")
    print(f"첫날 {s.iloc[0]:.2f} / 마지막날 {s.iloc[-1]:.2f}")
    print(f"4일 초과 공백(휴장 이상): {(gaps > 4).sum()}")
    big = ret[ret.abs() > 0.25]
    print(f"일간 변동 ±25% 초과: {len(big)}건")
    for d, r in big.items():
        print(f"   {d.date()}: {r:+.1%}")
    print("연도별 거래일 수:", s.groupby(s.index.year).size().to_dict())
    print()


if __name__ == "__main__":
    for n in ("soxl", "tqqq"):
        report(n)
