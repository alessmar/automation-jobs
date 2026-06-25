#!/usr/bin/env python3
"""Fetch ETH price from CoinMarketCap and post the value to Slack."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime

import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

REQUEST_TIMEOUT_SECONDS = 30

@dataclass(frozen=True)
class Settings:
    coinmarketcap_api_key: str | None
    coinmarketcap_url: str
    symbol: str
    convert_currency: str
    multiplier: float
    slack_bot_token: str | None
    slack_channel_id: str | None


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def log(message: str) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", file=sys.stderr, flush=True)

def load_settings() -> Settings:
    return Settings(
        coinmarketcap_api_key=env("COINMARKETCAP_API_KEY"),
        coinmarketcap_url="https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest",
        symbol="ETH",
        convert_currency="EUR",
        multiplier=env("ETH_MULTIPLIER"),
        slack_bot_token=env("SLACK_BOT_TOKEN"),
        slack_channel_id=env("SLACK_CHANNEL_ID"),
    )


def fetch_coinmarketcap_quote(settings: Settings) -> dict:
    if not settings.coinmarketcap_api_key:
        raise RuntimeError("Missing required environment variable: COINMARKETCAP_API_KEY")

    log(
        "Fetching CoinMarketCap quote: "
        f"symbol={settings.symbol}, convert={settings.convert_currency}, url={settings.coinmarketcap_url}"
    )
    response = requests.get(
        settings.coinmarketcap_url,
        headers={"X-CMC_PRO_API_KEY": settings.coinmarketcap_api_key},
        params={"symbol": settings.symbol, "convert": settings.convert_currency},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    status = payload.get("status", {})
    if status.get("error_code") not in (None, 0):
        raise RuntimeError(
            "CoinMarketCap returned an error: "
            f"{status.get('error_code')} {status.get('error_message', 'unknown error')}"
        )
    log(f"Fetched CoinMarketCap quote: bytes={len(response.content)}")
    return payload


def extract_price(payload: dict, symbol: str, convert_currency: str) -> float:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("CoinMarketCap response is missing the data object.")

    symbol_data = data.get(symbol)
    if isinstance(symbol_data, list):
        if not symbol_data:
            raise RuntimeError(f"CoinMarketCap response does not contain any entries for {symbol}.")
        symbol_data = symbol_data[0]

    if not isinstance(symbol_data, dict):
        raise RuntimeError(f"CoinMarketCap response does not contain a valid entry for {symbol}.")

    quote = symbol_data.get("quote", {})
    if not isinstance(quote, dict):
        raise RuntimeError(f"CoinMarketCap response for {symbol} has an invalid quote structure.")

    currency_data = quote.get(convert_currency, {})
    if not isinstance(currency_data, dict):
        raise RuntimeError(f"CoinMarketCap response for {symbol} is missing {convert_currency} quote data.")

    price = currency_data.get("price")
    if price is None:
        raise RuntimeError(f"CoinMarketCap response for {symbol} is missing {convert_currency} price data.")

    return float(price)


def format_currency_it(value: float) -> str:
    formatted = f"{value:,.2f}"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} €"


def build_message(symbol: str, price: float, multiplier: float) -> str:
    current_value = price * multiplier
    return f"{symbol} Current value: {format_currency_it(current_value)}"


def send_slack_message(settings: Settings, text: str) -> None:
    missing = [
        name
        for name, value in {
            "SLACK_BOT_TOKEN": settings.slack_bot_token,
            "SLACK_CHANNEL_ID": settings.slack_channel_id,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required Slack environment variables: {', '.join(missing)}")

    log(f"Sending Slack message to channel={settings.slack_channel_id}")
    client = WebClient(token=settings.slack_bot_token, timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        client.chat_postMessage(channel=settings.slack_channel_id, text=text)
    except SlackApiError as exc:
        raise RuntimeError(f"Slack API returned an error: {exc.response.get('error', 'unknown error')}") from exc
    log("Slack message sent successfully.")


def run(dry_run: bool) -> int:
    log(f"Starting ETH value Slack job: dry_run={dry_run}")
    settings = load_settings()
    payload = fetch_coinmarketcap_quote(settings)
    price = extract_price(payload, settings.symbol, settings.convert_currency)
    message = build_message(settings.symbol, price, settings.multiplier)
    log(f"Computed message: {message}")

    if dry_run:
        log("Dry run enabled; printing message and skipping Slack send.")
        print(message)
        return 0

    send_slack_message(settings, message)
    log("Job completed successfully.")
    return 0


def parse_args() -> "argparse.Namespace":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch the quote and print the Slack message instead of sending it.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return run(dry_run=args.dry_run)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
