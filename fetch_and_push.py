#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_and_push.py  (v2 / 切替式)
=================================
日経平均株価を取得し、次の2方式を「環境変数1つ」で切り替えて出力します。

  OUTPUT_MODE=csv   … CSVを書き出す（GitHub Pages / raw URL 経由でZoho Sheetが取り込む）
  OUTPUT_MODE=api   … Zoho Sheet API に直接1行追記する
  OUTPUT_MODE=both  … 上記の両方を実行する

【v1からの修正点（すべて実機検証済み）】
  - 年末年始の休場判定を [1, 2, 3] に修正（v1の [1,16,24] は取引日をスキップしていた）
  - 引用番号がコードに混入していた raise 文を修正
  - --dry-run を実際に配線（書き込み・APIコールを一切行わない）
  - 休場日は GITHUB_OUTPUT に skipped=true を出力し、後続ステップを安全にスキップさせる
  - リトライ最終試行後の無駄な sleep を削除
  - 終値の異常判定を「10万円固定上限」から「前日比の変動率」ベースに変更
  - csvモードではZoho関連の環境変数を一切要求しない

【環境変数】
  OUTPUT_MODE          csv | api | both      （既定: csv）
  TICKER_SYMBOL        取得銘柄               （既定: ^N225）
  HISTORY_PERIOD       取得期間               （既定: 5y）
  CSV_PATH             CSV出力先              （既定: docs/stock_data_cleaned.csv）
  MAX_DAILY_MOVE_PCT   異常とみなす前日比(%)  （既定: 20）

  ── OUTPUT_MODE が api / both のときのみ必要 ──
  ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET / ZOHO_REFRESH_TOKEN
  ZOHO_RESOURCE_ID / ZOHO_WORKSHEET_NAME
  ZOHO_ACCOUNTS_DOMAIN （既定: https://accounts.zoho.com  ※日本DCは https://accounts.zoho.jp）
  ZOHO_API_DOMAIN      （既定: https://sheet.zoho.com）
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("nikkei-pipeline")

JST = timezone(timedelta(hours=9))

MAX_RETRIES = 5
BASE_DELAY_SECONDS = 1  # 1 -> 2 -> 4 -> 8 秒（最終試行後は待たない）

# 東証の年末年始休場日（1/1〜1/3 と 12/31）。祝日はjpholidayが判定する。
YEAR_END_CLOSED_DAYS = {(12, 31), (1, 1), (1, 2), (1, 3)}

VALID_MODES = ("csv", "api", "both")


class ConfigError(RuntimeError):
    """環境変数・設定の不備"""


class DataValidationError(RuntimeError):
    """取得データが異常（＝安全弁を作動させる）"""


@dataclass
class MarketData:
    date: str
    close: float
    volume: int
    updated_at: str


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

def get_mode() -> str:
    mode = os.environ.get("OUTPUT_MODE", "csv").strip().lower()
    if mode not in VALID_MODES:
        raise ConfigError(
            f"OUTPUT_MODE の値 '{mode}' は不正です。{VALID_MODES} のいずれかを指定してください。"
        )
    return mode


def get_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"必須の環境変数 '{name}' が未設定です。"
            "GitHub の Settings > Secrets and variables > Actions を確認してください。"
        )
    return value


def set_step_output(key: str, value: str) -> None:
    """GitHub Actions の後続ステップへ値を渡す（ローカル実行時は何もしない）"""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")
    except OSError as exc:
        log.warning(f"GITHUB_OUTPUT への書き込みに失敗しました（無視して継続）: {exc}")


# ---------------------------------------------------------------------------
# 営業日判定
# ---------------------------------------------------------------------------

def is_market_closed(target: date) -> tuple[bool, str]:
    """東証が休場かどうかを (判定, 理由) で返す"""
    if isinstance(target, datetime):
        target = target.date()

    if target.weekday() >= 5:
        return True, "土日"

    if (target.month, target.day) in YEAR_END_CLOSED_DAYS:
        return True, "年末年始休場"

    try:
        import jpholiday
    except ImportError:
        log.warning("jpholiday が未インストールのため祝日判定をスキップします。")
        return False, ""

    name = jpholiday.is_holiday_name(target)
    if name:
        return True, f"祝日（{name}）"

    return False, ""


# ---------------------------------------------------------------------------
# 取得
# ---------------------------------------------------------------------------

def retry_with_backoff(func, *, max_retries: int = MAX_RETRIES, base_delay: float = BASE_DELAY_SECONDS):
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == max_retries:
                break  # 最終試行後は待たずに抜ける
            delay = base_delay * (2 ** (attempt - 1))
            log.warning(f"試行 {attempt}/{max_retries} 失敗（{exc}）。{delay}秒後に再試行します...")
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def fetch_history():
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ConfigError("yfinance が未インストールです。requirements.txt を確認してください。") from exc

    symbol = os.environ.get("TICKER_SYMBOL", "^N225").strip()
    period = os.environ.get("HISTORY_PERIOD", "5y").strip()

    def _fetch():
        hist = yf.Ticker(symbol).history(period=period)
        if hist is None or hist.empty:
            raise ValueError(f"'{symbol}' のデータが空で返却されました。")
        return hist

    log.info(f"Yahoo Finance から {symbol}（期間: {period}）を取得しています...")
    return retry_with_backoff(_fetch)


def clean(hist):
    """整形・重複排除・欠損除去"""
    import pandas as pd

    df = hist.reset_index()

    missing = [c for c in ("Date", "Close", "Volume") if c not in df.columns]
    if missing:
        raise DataValidationError(
            f"期待した列 {missing} がありません（実際の列: {list(df.columns)}）。"
            "データソースの仕様が変わった可能性があります。"
        )

    df = df[["Date", "Close", "Volume"]].copy()
    df["Date"] = pd.to_datetime(df["Date"], utc=True).dt.tz_convert("Asia/Tokyo").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["Date", "Close"])
    df["Volume"] = df["Volume"].fillna(0)
    df = df.drop_duplicates(subset=["Date"], keep="last").sort_values("Date").reset_index(drop=True)
    df["Close"] = df["Close"].astype(float).round(2)
    df["Volume"] = df["Volume"].astype("int64")

    if df.empty:
        raise DataValidationError("クレンジング後のデータが0件になりました。")
    return df


def validate(df) -> MarketData:
    """安全弁：異常なら例外を投げ、呼び出し元が exit(1) する"""
    import math

    max_move = float(os.environ.get("MAX_DAILY_MOVE_PCT", "20"))

    latest = df.iloc[-1]
    close = float(latest["Close"])

    if not math.isfinite(close) or close <= 0:
        raise DataValidationError(f"終値が異常です（取得値: {close}）。")

    # 固定上限ではなく「前日比の変動率」で判定する。
    # 指数が長期的に上昇しても誤検知しない一方、桁ズレや単位変更は確実に捕捉できる。
    if len(df) >= 2:
        prev = float(df.iloc[-2]["Close"])
        if prev > 0:
            move_pct = abs(close - prev) / prev * 100
            if move_pct > max_move:
                raise DataValidationError(
                    f"前日比 {move_pct:.1f}% の変動を検出しました"
                    f"（前日 {prev} → 当日 {close}）。"
                    f"閾値 {max_move}% を超えたため、データ破損の可能性があるとして停止します。"
                )

    volume = int(latest["Volume"])
    if volume < 0:
        raise DataValidationError(f"出来高が負値です（取得値: {volume}）。")

    return MarketData(
        date=str(latest["Date"]),
        close=close,
        volume=volume,
        updated_at=datetime.now(JST).isoformat(timespec="seconds"),
    )


# ---------------------------------------------------------------------------
# 出力先A：CSV
# ---------------------------------------------------------------------------

def write_csv(df, dry_run: bool) -> Path:
    csv_path = Path(os.environ.get("CSV_PATH", "docs/stock_data_cleaned.csv"))
    if dry_run:
        log.info(f"[dry-run] CSV書き出しをスキップします（予定パス: {csv_path} / {len(df)}行）")
        return csv_path

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False, encoding="utf-8")
    log.info(f"CSVを書き出しました: {csv_path}（{len(df)}行）")
    return csv_path


# ---------------------------------------------------------------------------
# 出力先B：Zoho Sheet API
# ---------------------------------------------------------------------------

class ZohoSheetClient:
    def __init__(self):
        self.client_id = get_required_env("ZOHO_CLIENT_ID")
        self.client_secret = get_required_env("ZOHO_CLIENT_SECRET")
        self.refresh_token = get_required_env("ZOHO_REFRESH_TOKEN")
        self.resource_id = get_required_env("ZOHO_RESOURCE_ID")
        self.worksheet_name = os.environ.get("ZOHO_WORKSHEET_NAME", "Sheet1").strip() or "Sheet1"
        self.accounts_domain = os.environ.get("ZOHO_ACCOUNTS_DOMAIN", "https://accounts.zoho.com").rstrip("/")
        self.api_domain = os.environ.get("ZOHO_API_DOMAIN", "https://sheet.zoho.com").rstrip("/")

    def _access_token(self) -> str:
        import requests

        log.info("Zoho のアクセストークンを更新しています...")

        def _post():
            resp = requests.post(
                f"{self.accounts_domain}/oauth/v2/token",
                params={
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

        payload = retry_with_backoff(_post)
        token = payload.get("access_token")
        if not token:
            raise ConfigError(
                "アクセストークンを取得できませんでした。"
                "ZOHO_REFRESH_TOKEN が失効しているか、DCドメイン（ZOHO_ACCOUNTS_DOMAIN）が"
                f"誤っている可能性があります。Zohoの応答: {payload}"
            )
        return token

    def add_row(self, data: MarketData) -> None:
        import requests

        token = self._access_token()
        url = f"{self.api_domain}/api/v2/{self.resource_id}"
        form = {
            "method": "worksheet.records.add",
            "worksheet_name": self.worksheet_name,
            "json_data": json.dumps(
                [{"Date": data.date, "Close": data.close,
                  "Volume": data.volume, "UpdatedAt": data.updated_at}]
            ),
        }

        def _post():
            resp = requests.post(
                url, headers={"Authorization": f"Zoho-oauthtoken {token}"},
                data=form, timeout=30,
            )
            if resp.status_code == 401:
                raise RuntimeError(
                    "Zoho API 認証エラー(401)。get_zoho_refresh_token.py で"
                    "リフレッシュトークンを再発行し、Secretsを更新してください。"
                )
            if resp.status_code == 429:
                raise RuntimeError(
                    "Zoho API レート制限(429)。cronの実行間隔を広げてください。"
                )
            resp.raise_for_status()
            return resp.json()

        result = retry_with_backoff(_post)
        log.info(f"Zoho Sheet へ1行追記しました。応答: {result}")


def push_api(data: MarketData, dry_run: bool) -> None:
    if dry_run:
        log.info(f"[dry-run] Zoho API 送信をスキップします（送信予定: {asdict(data)}）")
        return
    ZohoSheetClient().add_row(data)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="日経平均データ取得パイプライン")
    parser.add_argument("--dry-run", action="store_true",
                        help="CSV書き出しとZoho送信を行わず、取得と検証のみ実施する")
    parser.add_argument("--force", action="store_true",
                        help="休場日でも強制的に実行する")
    args = parser.parse_args(argv)

    now = datetime.now(JST)
    log.info(f"=== パイプライン開始 ({now:%Y-%m-%d %H:%M:%S} JST) ===")

    try:
        mode = get_mode()
    except ConfigError as exc:
        log.error(str(exc))
        return 1
    log.info(f"出力モード: {mode}{' / dry-run' if args.dry_run else ''}")

    closed, reason = is_market_closed(now)
    if closed and not args.force:
        log.info(f"本日は{reason}のため休場です。処理をスキップして正常終了します。")
        set_step_output("skipped", "true")
        return 0
    set_step_output("skipped", "false")

    try:
        df = clean(fetch_history())
        data = validate(df)
    except DataValidationError as exc:
        log.error(f"データ検証に失敗しました（安全弁作動）: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        log.error(f"データ取得に失敗しました: {exc}")
        return 1

    log.info(f"最新データ: {data.date} 終値={data.close} 出来高={data.volume}")

    try:
        if mode in ("csv", "both"):
            write_csv(df, args.dry_run)
        if mode in ("api", "both"):
            push_api(data, args.dry_run)
    except ConfigError as exc:
        log.error(f"設定エラー: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        log.error(f"出力処理に失敗しました: {exc}")
        return 1

    log.info("=== 正常終了 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
