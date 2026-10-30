import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


def weeks(symbol):
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + symbol
        + "?interval=1wk&range=3y"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.load(response)
    result = data["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    rows = []
    for stamp, open_, high, low, close in zip(
        result["timestamp"], quote["open"], quote["high"], quote["low"], quote["close"]
    ):
        if None in (open_, high, low, close):
            continue
        start = datetime.fromtimestamp(stamp, timezone.utc).date()
        rows.append({"start": start, "o": open_, "h": high, "l": low, "c": close})
    return rows


def cci(rows, period=30):
    typical = [(row["h"] + row["l"] + row["c"]) / 3 for row in rows]
    values = []
    for index in range(len(rows)):
        if index + 1 < period:
            values.append(None)
            continue
        window = typical[index + 1 - period : index + 1]
        average = sum(window) / period
        deviation = sum(abs(price - average) for price in window) / period
        values.append(None if deviation == 0 else (typical[index] - average) / (0.015 * deviation))
    return values


def card(name, rows):
    high = max(row["h"] for row, _ in rows)
    low = min(row["l"] for row, _ in rows)
    span = high - low or 1
    last = round(rows[-1][1])
    direction = "up" if last >= 0 else "down"
    word = "상승" if direction == "up" else "하락"
    columns = []
    previous_down = False
    for row, value in rows:
        friday = row["start"] + timedelta(days=4)

        def place(price, high=high, span=span):
            return (high - price) / span * 64 + 4

        top = place(row["h"])
        bottom = place(row["l"])
        body_top = place(max(row["o"], row["c"]))
        body_bottom = place(min(row["o"], row["c"]))
        down = value < 0
        classes = "col"
        if down:
            classes += " down start" if not previous_down else " down"
        previous_down = down
        side = "rise" if row["c"] >= row["o"] else "fall"
        sign = "neg" if down else "pos"
        columns.append(
            f'<div class="{classes}"><div class="date">{friday.month}/{friday.day}</div>'
            f'<div class="candle-box"><div class="wick" style="top:{top:.1f}px;height:{max(1, bottom - top):.1f}px"></div>'
            f'<div class="body {side}" style="top:{body_top:.1f}px;height:{max(2, body_bottom - body_top):.1f}px"></div></div>'
            f'<div class="cci {sign}">{round(value):+d}</div><div class="bar {sign}"></div></div>'
        )
    friday = rows[-1][0]["start"] + timedelta(days=4)
    close = rows[-1][0]["c"]
    return (
        f'<article class="card {direction}"><div class="head"><div class="name">{name}</div>'
        f'<div class="signal"><span class="point">{close:,.2f}</span><div class="pill">{word}</div></div></div>'
        f'<p class="judge">판단 CCI <b>{last:+d}</b> · {friday.month}월 {friday.day}일 주봉</p>'
        f'<div class="cols">{"".join(columns)}</div></article>'
    )


def main():
    cutoff = datetime(2026, 10, 26, tzinfo=timezone.utc).date()
    series = {}
    for symbol in ("QQQ", "SOXX"):
        paired = [
            (row, value)
            for row, value in zip(weeks(symbol), cci(weeks(symbol)))
            if row["start"] < cutoff and value is not None
        ]
        series[symbol] = paired[-30:]
        print(symbol, series[symbol][0][0]["start"], series[symbol][-1][0]["start"])

    css = Path(__file__).with_name("sample.css").read_text(encoding="utf-8")
    html = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap" rel="stylesheet" />
<style>
%s
</style>
</head>
<body>
  <div class="wrap">
    <h2>주봉 추세</h2>
    <p class="sub">CCI 30 · 0 이상 상승 · 지난주 확정 · 최근 30주</p>
    %s
    <p class="note">샘플입니다. 파란 빗금은 CCI가 0 미만인 주이고, 세로선은 하락이 시작된 주입니다.</p>
  </div>
</body>
</html>
""" % (css, card("QQQ", series["QQQ"]) + card("SOXX", series["SOXX"]))
    out = Path(__file__).with_name("trend_sample.html")
    out.write_text(html, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
