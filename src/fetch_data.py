"""SOXL / TQQQ 일별 종가 수집·갱신 스크립트.

- 가격 기준: 분할(split)만 조정, 배당 미반영 (yfinance auto_adjust=False 의 'Close')
- 시작: 2020-01-01 고정 / 종료: 기본 오늘(미래 날짜는 자동으로 마지막 거래일까지)
- 출력: data/soxl.csv, data/tqqq.csv  (컬럼: date, close)
- 수집 실패·빈 결과·기존보다 짧은 데이터면 기존 파일을 덮어쓰지 않음
"""
from pathlib import Path

import pandas as pd
import yfinance as yf

START = "2020-01-01"
TICKERS = ["SOXL", "TQQQ"]
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def fetch(ticker: str, end_inclusive: str | None = None) -> pd.DataFrame:
    end_inclusive = end_inclusive or pd.Timestamp.today().strftime("%Y-%m-%d")
    end_exclusive = (pd.Timestamp(end_inclusive) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = yf.download(
        ticker,
        start=START,
        end=end_exclusive,
        auto_adjust=False,  # 'Close' = 분할 조정, 배당 미조정
        progress=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    out = df[["Close"]].rename(columns={"Close": "close"}).dropna()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out.index.name = "date"
    return out.round(4)


def update_all(end_inclusive: str | None = None) -> dict:
    """모든 종목 갱신. 종목별 결과 메시지를 dict로 반환."""
    DATA_DIR.mkdir(exist_ok=True)
    report = {}
    for t in TICKERS:
        path = DATA_DIR / f"{t.lower()}.csv"
        try:
            df = fetch(t, end_inclusive)
        except Exception as e:  # 네트워크 오류 등
            report[t] = f"실패: {e}"
            continue
        old_rows = len(pd.read_csv(path)) if path.exists() else 0
        if df.empty or len(df) < old_rows:
            report[t] = f"건너뜀: 새 데이터({len(df)}행)가 기존({old_rows}행)보다 적음"
            continue
        df.to_csv(path)
        report[t] = f"{len(df)}행 (기존 {old_rows}행), {df.index.min().date()} ~ {df.index.max().date()}"
    return report


if __name__ == "__main__":
    for k, v in update_all().items():
        print(f"{k}: {v}")
