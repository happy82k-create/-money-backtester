from __future__ import annotations

from dataclasses import dataclass


WEIGHTS = {
    "drawdown": 0.30,
    "weekly_rsi": 0.20,
    "vix": 0.15,
    "ma200": 0.15,
    "daily_rsi": 0.10,
    "fear_greed": 0.10,
}

DRAWDOWN_FULL = 0.12
MA200_FULL = 0.12
VIX_FULL_RATIO = 1.40
RSI_ZERO = 70.0
RSI_FULL = 30.0
RSI_PERIOD = 14
MA200_PERIOD = 200
VIX_SMA_PERIOD = 50
RATE_SMA_PERIOD = 50
RATE_LOOKBACK = 63
RATE_DROP = 0.25


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def cutler_rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains += change
        else:
            losses += -change
    total = gains + losses
    if total == 0:
        return 50.0
    return 100.0 * gains / total


def rsi_cell(rsi: float | None) -> float | None:
    if rsi is None:
        return None
    return clamp((RSI_ZERO - rsi) / (RSI_ZERO - RSI_FULL) * 100.0)


def drawdown_cell(price: float, high: float) -> float:
    if high <= 0:
        return 0.0
    return clamp(((high - price) / high) / DRAWDOWN_FULL * 100.0)


def vix_cell(vix: float, vix_sma: float) -> float:
    if vix_sma <= 0:
        return 0.0
    return clamp((vix / vix_sma - 1.0) / (VIX_FULL_RATIO - 1.0) * 100.0)


def ma200_cell(price: float, sma200: float) -> float:
    if sma200 <= 0:
        return 0.0
    return clamp((1.0 - price / sma200) / MA200_FULL * 100.0)


def fear_greed_cell(cnn_score: float) -> float:
    return clamp(100.0 - cnn_score)


@dataclass(frozen=True)
class ComponentScore:
    key: str
    label: str
    weight: float
    cell: float
    raw_label: str
    raw_value: float | None
    detail: str

    @property
    def contribution(self) -> float:
        return self.weight * self.cell


def total_score(cells: dict[str, float]) -> float:
    return sum(WEIGHTS[key] * cells[key] for key in WEIGHTS)
