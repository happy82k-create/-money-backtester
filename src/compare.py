"""실데이터 비교 실행: 종목 x 진입방식 x 익절 x 타임컷."""
import itertools

import pandas as pd

from engine import run

rows = []
for ticker, mode, tp, tc in itertools.product(["SOXL", "TQQQ"], ["equal", "tiered"],
                                              [0.01, 1.0, 2.0], [10, 12]):
    m = run(ticker=ticker, entry_mode=mode, tp_pct=tp, timecut_days=tc).metrics
    rows.append({
        "종목": ticker, "진입": mode, "익절%": tp, "타임컷": tc,
        "총수익%": round(m["총 수익률(%)"], 1),
        "CAGR%": round(m["연환산 수익률 CAGR(%)"], 1),
        "MDD%": round(m["최대 낙폭 MDD(%)"], 1),
        "거래수": m["총 거래 수(청산)"],
        "승률%": round(m["승률(%)"], 1),
        "타임컷%": round(m["타임컷 비율(%)"], 1),
        "평균보유일": round(m["평균 보유일"], 1),
        "미청산": m["미청산 포지션"],
        "B&H%": round(m["Buy&Hold 수익률(%)"], 1),
    })
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
print(pd.DataFrame(rows).to_string(index=False))
