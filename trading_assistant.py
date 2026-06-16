#!/usr/bin/env python3
"""
Low-time trading assistant.

This script does NOT connect to any broker and does NOT place real-money orders.
It fetches market data, creates alerts, calculates position size, and records
paper-trading signals so the final decision stays manual.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import io
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_CONFIG = {
    "capital": 10000,
    "risk_per_trade": 100,
    "daily_max_loss": 200,
    "symbols": ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "NIFTYBEES.NS"],
    "use_nse_equity_list": True,
    "nse_equity_url": "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
    "max_symbols": 1000,
    "max_workers": 20,
    "top_alerts": 10,
    "interval": "15m",
    "range": "5d",
    "short_sma": 9,
    "long_sma": 21,
    "rsi_period": 14,
    "rsi_buy_min": 45,
    "rsi_buy_max": 68,
    "rsi_sell_max": 40,
    "stop_loss_percent": 1.0,
    "target_percent": 1.5,
    "paper_trade": True,
    "telegram_bot_token": "",
    "telegram_chat_id": "",
}


def load_config(path: Path) -> dict:
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    with path.open("r", encoding="utf-8") as handle:
        user_config = json.load(handle)
    config = dict(DEFAULT_CONFIG)
    config.update(user_config)
    return config


def resolve_symbols(config: dict) -> list[str]:
    symbols = []
    if config.get("use_nse_equity_list", False):
        try:
            symbols.extend(fetch_nse_equity_symbols(config))
        except Exception as exc:
            print(f"NSE list fetch failed, using config symbols: {exc}", file=sys.stderr)

    if not symbols:
        symbols.extend(config.get("symbols", []))

    seen = set()
    clean_symbols = []
    for symbol in symbols:
        symbol = str(symbol).strip().upper()
        if not symbol:
            continue
        if not symbol.endswith(".NS"):
            symbol = f"{symbol}.NS"
        if symbol not in seen:
            clean_symbols.append(symbol)
            seen.add(symbol)
    max_symbols = int(config.get("max_symbols") or len(clean_symbols))
    return clean_symbols[:max_symbols]


def fetch_nse_equity_symbols(config: dict) -> list[str]:
    url = config.get("nse_equity_url") or DEFAULT_CONFIG["nse_equity_url"]
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 trading-assistant alerts-only",
            "Accept": "text/csv,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        csv_text = response.read().decode("utf-8", errors="replace")

    symbols = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        series = (row.get(" SERIES") or row.get("SERIES") or "").strip().upper()
        symbol = (row.get("SYMBOL") or "").strip().upper()
        if series == "EQ" and symbol:
            symbols.append(f"{symbol}.NS")
    if not symbols:
        raise RuntimeError("No EQ symbols found in NSE list")
    return symbols


def fetch_yahoo_chart(symbol: str, interval: str, data_range: str) -> list[dict]:
    encoded_symbol = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}"
        f"?interval={urllib.parse.quote(interval)}&range={urllib.parse.quote(data_range)}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 trading-assistant alerts-only",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    result = payload.get("chart", {}).get("result", [])
    if not result:
        raise RuntimeError(f"No chart data for {symbol}")

    chart = result[0]
    timestamps = chart.get("timestamp") or []
    quote = (chart.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    opens = quote.get("open") or []
    volumes = quote.get("volume") or []

    candles = []
    for index, ts in enumerate(timestamps):
        close = safe_at(closes, index)
        if close is None:
            continue
        candles.append(
            {
                "time": dt.datetime.fromtimestamp(ts).isoformat(timespec="minutes"),
                "open": safe_at(opens, index),
                "high": safe_at(highs, index),
                "low": safe_at(lows, index),
                "close": close,
                "volume": safe_at(volumes, index),
            }
        )
    if len(candles) < 30:
        raise RuntimeError(f"Not enough candles for {symbol}")
    return candles


def safe_at(items: list, index: int):
    if index >= len(items):
        return None
    return items[index]


def sma(values: list[float], period: int) -> float:
    if len(values) < period:
        return float("nan")
    return sum(values[-period:]) / period


def rsi(values: list[float], period: int) -> float:
    if len(values) <= period:
        return float("nan")
    gains = []
    losses = []
    window = values[-(period + 1) :]
    for previous, current in zip(window, window[1:]):
        change = current - previous
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs_value = avg_gain / avg_loss
    return 100 - (100 / (1 + rs_value))


def decide_signal(symbol: str, candles: list[dict], config: dict) -> dict:
    closes = [float(candle["close"]) for candle in candles if candle["close"] is not None]
    price = closes[-1]
    short = sma(closes, int(config["short_sma"]))
    long = sma(closes, int(config["long_sma"]))
    rsi_value = rsi(closes, int(config["rsi_period"]))
    recent_price = closes[-5] if len(closes) >= 5 else closes[0]
    recent_change_percent = percent_change(price, recent_price)
    trend_strength_percent = percent_change(short, long)

    signal = "WAIT"
    reason = "No clean setup"
    if short > long and config["rsi_buy_min"] <= rsi_value <= config["rsi_buy_max"]:
        signal = "BUY_WATCH"
        reason = "Short SMA above long SMA and RSI is in controlled momentum zone"
    elif short < long or rsi_value <= config["rsi_sell_max"]:
        signal = "AVOID_OR_EXIT"
        reason = "Trend weak or RSI bearish"

    stop_loss = price * (1 - float(config["stop_loss_percent"]) / 100)
    target = price * (1 + float(config["target_percent"]) / 100)
    risk_per_share = max(price - stop_loss, 0.01)
    reward_per_share = max(target - price, 0.0)
    risk_qty = math.floor(float(config["risk_per_trade"]) / risk_per_share)
    capital_qty = math.floor(float(config["capital"]) / price)
    qty = max(0, min(risk_qty, capital_qty))
    estimated_profit = qty * reward_per_share
    risk_reward = reward_per_share / risk_per_share
    score = rank_score(signal, trend_strength_percent, recent_change_percent, rsi_value, estimated_profit)
    action_reason = build_action_reason(signal, trend_strength_percent, recent_change_percent, rsi_value)

    return {
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "symbol": symbol,
        "signal": signal,
        "price": round(price, 2),
        "short_sma": round(short, 2),
        "long_sma": round(long, 2),
        "rsi": round(rsi_value, 2),
        "qty": qty,
        "stop_loss": round(stop_loss, 2),
        "target": round(target, 2),
        "max_loss": round(qty * risk_per_share, 2),
        "estimated_profit": round(estimated_profit, 2),
        "risk_reward": round(risk_reward, 2),
        "trend_strength_percent": round(trend_strength_percent, 2),
        "recent_change_percent": round(recent_change_percent, 2),
        "score": round(score, 2),
        "reason": reason,
        "action_reason": action_reason,
    }


def percent_change(current: float, previous: float) -> float:
    if previous == 0 or math.isnan(previous) or math.isnan(current):
        return 0.0
    return ((current - previous) / previous) * 100


def rank_score(
    signal: str,
    trend_strength_percent: float,
    recent_change_percent: float,
    rsi_value: float,
    estimated_profit: float,
) -> float:
    if signal != "BUY_WATCH":
        return 0.0
    rsi_quality = max(0.0, 25.0 - abs(rsi_value - 56.0))
    trend_score = max(0.0, trend_strength_percent) * 30
    momentum_score = max(0.0, recent_change_percent) * 8
    profit_score = min(30.0, estimated_profit / 5)
    return rsi_quality + trend_score + momentum_score + profit_score


def build_action_reason(
    signal: str,
    trend_strength_percent: float,
    recent_change_percent: float,
    rsi_value: float,
) -> str:
    if signal == "BUY_WATCH":
        return (
            f"Buy-watch because 9 SMA is above 21 SMA by {trend_strength_percent:.2f}%, "
            f"RSI {rsi_value:.1f} is controlled, and recent momentum is {recent_change_percent:.2f}%."
        )
    if signal == "AVOID_OR_EXIT":
        return (
            f"Avoid/exit because trend is weak or RSI {rsi_value:.1f} is bearish; "
            f"recent momentum is {recent_change_percent:.2f}%."
        )
    return (
        f"Wait because trend/momentum is not clean enough; RSI {rsi_value:.1f}, "
        f"recent momentum {recent_change_percent:.2f}%."
    )


def append_signal(path: Path, signal: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(signal.keys()))
        if not exists:
            writer.writeheader()
        writer.writerow(signal)


def format_alert(signal: dict) -> str:
    return (
        f"{signal['symbol']} | {signal['signal']}\n"
        f"Price: {signal['price']} | Qty: {signal['qty']}\n"
        f"SL: {signal['stop_loss']} | Target: {signal['target']} | Max loss: {signal['max_loss']}\n"
        f"Est profit: {signal['estimated_profit']} | Score: {signal['score']}\n"
        f"RSI: {signal['rsi']} | SMA: {signal['short_sma']}/{signal['long_sma']}\n"
        f"Why: {signal['action_reason']}\n"
        "Manual approval required. This script does not place orders."
    )


def format_top_alerts(signals: list[dict], scanned_count: int, top_n: int) -> str:
    ranked = rank_buy_signals(signals)[:top_n]
    lines = [
        f"Trading Assistant: Top {len(ranked)} BUY_WATCH",
        f"Scanned: {scanned_count} | Buy setups: {len([s for s in signals if s['signal'] == 'BUY_WATCH'])}",
        "Manual approval required. No auto order placed.",
        "",
    ]
    for index, signal in enumerate(ranked, start=1):
        lines.extend(
            [
                f"{index}. {signal['symbol']} | Score {signal['score']} | Price {signal['price']}",
                f"Qty {signal['qty']} | SL {signal['stop_loss']} | Target {signal['target']}",
                f"Est profit {signal['estimated_profit']} | Max loss {signal['max_loss']} | R:R {signal['risk_reward']}",
                f"Why: SMA strength {signal['trend_strength_percent']}%, RSI {signal['rsi']}, recent {signal['recent_change_percent']}%",
                "",
            ]
        )
    return "\n".join(lines).strip()


def rank_buy_signals(signals: list[dict]) -> list[dict]:
    buy_signals = [signal for signal in signals if signal["signal"] == "BUY_WATCH"]
    return sorted(
        buy_signals,
        key=lambda signal: (
            float(signal.get("score", 0)),
            float(signal.get("estimated_profit", 0)),
            float(signal.get("trend_strength_percent", 0)),
        ),
        reverse=True,
    )


def send_telegram(config: dict, message: str) -> None:
    token = config.get("telegram_bot_token") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = config.get("telegram_chat_id") or os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return

    for chunk in split_message(message):
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        body = urllib.parse.urlencode({"chat_id": chat_id, "text": chunk}).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()


def split_message(message: str, limit: int = 3900) -> list[str]:
    if len(message) <= limit:
        return [message]
    chunks = []
    current = []
    current_len = 0
    for line in message.splitlines():
        line_len = len(line) + 1
        if current and current_len + line_len > limit:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def scan_symbol(symbol: str, config: dict) -> tuple[dict | None, str | None]:
    try:
        candles = fetch_yahoo_chart(symbol, config["interval"], config["range"])
        return decide_signal(symbol, candles, config), None
    except Exception as exc:
        return None, f"{symbol}: error: {exc}"


def run_once(config: dict, log_path: Path) -> int:
    signals = []
    symbols = resolve_symbols(config)
    max_workers = max(1, int(config.get("max_workers", 1)))
    top_alerts = max(1, int(config.get("top_alerts", 10)))
    print(f"Scanning {len(symbols)} symbols with {max_workers} workers")

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(scan_symbol, symbol, config): symbol for symbol in symbols}
        for future in concurrent.futures.as_completed(futures):
            signal, error = future.result()
            if error:
                print(error, file=sys.stderr)
                continue
            if not signal:
                continue
            append_signal(log_path, signal)
            signals.append(signal)
    ranked = rank_buy_signals(signals)
    if ranked:
        top_message = format_top_alerts(signals, len(symbols), top_alerts)
        print("=" * 72)
        print(top_message)
        send_telegram(config, top_message)
    actionable = len(ranked)
    print(f"BUY_WATCH signals: {actionable}")
    return actionable


def main() -> int:
    parser = argparse.ArgumentParser(description="Alerts-only paper trading assistant")
    parser.add_argument("--config", default="config.json", help="Path to config JSON")
    parser.add_argument("--log", default="paper_trades.csv", help="CSV log path")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--sleep", type=int, default=900, help="Loop sleep seconds")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    log_path = Path(args.log)

    while True:
        run_once(config, log_path)
        if not args.loop:
            break
        time.sleep(max(args.sleep, 60))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
