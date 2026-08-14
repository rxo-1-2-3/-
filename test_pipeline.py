#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_pipeline.py
=================
セットアップ前でも「ロジックが正しいこと」を自分で確認できる自己テストです。
ネットワーク接続は不要です。

  python tests/test_pipeline.py
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd  # noqa: E402

import fetch_and_push as fp  # noqa: E402

PASS, FAIL = "  [OK]  ", "  [NG]  "
failures = 0


def check(label, condition, detail=""):
    global failures
    if condition:
        print(f"{PASS}{label}")
    else:
        failures += 1
        print(f"{FAIL}{label}  {detail}")


def make_df(rows):
    return pd.DataFrame(rows, columns=["Date", "Close", "Volume"])


print("=== 1. 休場判定 ===")
# 2026年の実カレンダーで検証
check("土曜(2026-08-15)は休場", fp.is_market_closed(date(2026, 8, 15))[0])
check("日曜(2026-08-16)は休場", fp.is_market_closed(date(2026, 8, 16))[0])
check("祝日・山の日(2026-08-11)は休場", fp.is_market_closed(date(2026, 8, 11))[0])
check("平日(2026-08-13)は営業日", not fp.is_market_closed(date(2026, 8, 13))[0])

print()
print("=== 2. 年末年始（v1で壊れていた箇所）===")
check("1/2 は休場と判定される", fp.is_market_closed(date(2026, 1, 2))[0])
check("12/31 は休場と判定される", fp.is_market_closed(date(2027, 12, 31))[0])
for y in (2026, 2029, 2030):
    for d in (16, 24):
        target = date(y, 1, d)
        if target.weekday() >= 5:
            continue
        closed, reason = fp.is_market_closed(target)
        check(f"{y}/1/{d} は通常の取引日として実行される", not closed, f"理由={reason}")

print()
print("=== 3. クレンジング（重複・欠損・型）===")
idx = pd.to_datetime(
    ["2026-08-10", "2026-08-11", "2026-08-11", "2026-08-12"]
).tz_localize("Asia/Tokyo")
hist = pd.DataFrame(
    {"Close": [100.0, 200.0, 201.0, float("nan")], "Volume": [1, 2, 3, 4], "Open": [1, 2, 3, 4]},
    index=idx,
)
hist.index.name = "Date"
cleaned = fp.clean(hist)
check("重複日付が1行に集約される", len(cleaned) == 2, f"実際={len(cleaned)}行")
check("重複は後勝ちで採用される", float(cleaned.iloc[-1]["Close"]) == 201.0)
check("終値が欠損した行は除外される", "2026-08-12" not in list(cleaned["Date"]))
check("日付が YYYY-MM-DD 文字列になる", cleaned.iloc[0]["Date"] == "2026-08-10")
check("出来高が整数型になる", str(cleaned["Volume"].dtype).startswith("int"))

print()
print("=== 4. 安全弁（バリデーション）===")
ok = fp.validate(make_df([["2026-08-12", 42000.0, 100], ["2026-08-13", 42500.0, 120]]))
check("正常データは通過する", ok.close == 42500.0)

try:
    fp.validate(make_df([["2026-08-12", 42000.0, 100], ["2026-08-13", 4250.0, 120]]))
    check("桁ズレ(1/10)を検出して停止する", False, "例外が出なかった")
except fp.DataValidationError:
    check("桁ズレ(1/10)を検出して停止する", True)

try:
    fp.validate(make_df([["2026-08-13", -1.0, 100]]))
    check("負の終値を検出して停止する", False, "例外が出なかった")
except fp.DataValidationError:
    check("負の終値を検出して停止する", True)

os.environ["MAX_DAILY_MOVE_PCT"] = "20"
ok2 = fp.validate(make_df([["2026-08-12", 42000.0, 100], ["2026-08-13", 45000.0, 120]]))
check("通常の値動き(+7%)は通過する", ok2.close == 45000.0)

print()
print("=== 5. 列が変わったときの検出 ===")
broken = pd.DataFrame({"Close": [1.0]}, index=pd.to_datetime(["2026-08-13"]).tz_localize("Asia/Tokyo"))
broken.index.name = "Date"
try:
    fp.clean(broken)
    check("Volume列の消失を検出する", False, "例外が出なかった")
except fp.DataValidationError:
    check("Volume列の消失を検出する", True)

print()
print("=== 6. OUTPUT_MODE の検証 ===")
for mode in ("csv", "api", "both"):
    os.environ["OUTPUT_MODE"] = mode
    check(f"OUTPUT_MODE={mode} は受理される", fp.get_mode() == mode)
os.environ["OUTPUT_MODE"] = "zoho"
try:
    fp.get_mode()
    check("不正なOUTPUT_MODEを弾く", False, "例外が出なかった")
except fp.ConfigError:
    check("不正なOUTPUT_MODEを弾く", True)
os.environ["OUTPUT_MODE"] = "csv"

print()
print("=== 7. csvモードではZoho関連の環境変数を要求しない ===")
for key in list(os.environ):
    if key.startswith("ZOHO_"):
        del os.environ[key]
os.environ["OUTPUT_MODE"] = "csv"
try:
    fp.get_mode()
    check("Zoho未設定でもcsvモードは成立する", True)
except fp.ConfigError as exc:
    check("Zoho未設定でもcsvモードは成立する", False, str(exc))

print()
if failures:
    print(f"### {failures} 件失敗しました ###")
    sys.exit(1)
print("### すべてのテストに合格しました ###")
sys.exit(0)
