#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_zoho_refresh_token.py
==========================
OUTPUT_MODE=api / both を使う場合にだけ必要な、
Zohoの「リフレッシュトークン」を対話形式で発行するウィザードです。

  ※ OUTPUT_MODE=csv（既定）で運用するなら、このスクリプトは不要です。
     実行する必要はありません。

【使い方】ご自身のパソコンで1回だけ実行します（GitHub Actions上では実行しません）
  pip install requests
  python get_zoho_refresh_token.py
"""

from __future__ import annotations

import sys
import urllib.parse

import requests

SCOPE = "ZohoSheet.dataAPI.UPDATE,ZohoSheet.dataAPI.READ"
REDIRECT_URI = "https://localhost"  # Zoho APIコンソールの登録値と完全一致させること

# 公式のマルチDC一覧に準拠（日本は .co.jp ではなく .jp）
DOMAIN_CHOICES = {
    "1": ("グローバル / 米国 (.com)  ※迷ったらこれ", "https://accounts.zoho.com"),
    "2": ("日本 (.jp)", "https://accounts.zoho.jp"),
    "3": ("欧州 (.eu)", "https://accounts.zoho.eu"),
    "4": ("インド (.in)", "https://accounts.zoho.in"),
    "5": ("オーストラリア (.com.au)", "https://accounts.zoho.com.au"),
    "6": ("カナダ (zohocloud.ca)", "https://accounts.zohocloud.ca"),
}


def ask(prompt: str, allow_empty: bool = False) -> str:
    value = input(prompt).strip()
    if not value and not allow_empty:
        print("入力が空です。最初からやり直してください。")
        sys.exit(1)
    return value


def main() -> None:
    print("=" * 72)
    print(" Zoho Sheet API リフレッシュトークン取得ウィザード")
    print("=" * 72)
    print()
    print(" ※ OUTPUT_MODE=csv で運用する場合、この作業は不要です。")
    print()
    print(" 事前に https://api-console.zoho.com/ で「Server-based Applications」を作成し、")
    print(f" Authorized Redirect URIs に「{REDIRECT_URI}」を登録しておいてください。")
    print()

    print("Zohoアカウントのデータセンターを選んでください:")
    for key, (label, _) in DOMAIN_CHOICES.items():
        print(f"  {key}. {label}")
    choice = ask("番号を入力（わからなければ 1）> ", allow_empty=True) or "1"
    _, accounts_domain = DOMAIN_CHOICES.get(choice, DOMAIN_CHOICES["1"])
    print(f"  → {accounts_domain} を使用します")

    client_id = ask("\nClient ID を入力 > ")
    client_secret = ask("Client Secret を入力 > ")

    auth_url = f"{accounts_domain}/oauth/v2/auth?" + urllib.parse.urlencode({
        "scope": SCOPE,
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "access_type": "offline",
        "prompt": "consent",
    })

    print("\n" + "-" * 72)
    print("次のURLをブラウザで開き、Zohoにログインして『承諾』を押してください:")
    print()
    print(auth_url)
    print()
    print("承諾すると https://localhost/?code=... へ移動しようとして")
    print("『このサイトにアクセスできません』のような画面になりますが、正常です。")
    print("そのままアドレスバーのURL全体をコピーしてください。")
    print("-" * 72)

    redirected = ask("\nリダイレクト後のURL全体を貼り付け > ")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(redirected).query)
    codes = query.get("code")
    if not codes:
        print("\nURLに 'code' が含まれていません。貼り付け内容を確認してやり直してください。")
        sys.exit(1)

    print("\nトークンを取得しています...")
    payload = requests.post(
        f"{accounts_domain}/oauth/v2/token",
        params={
            "code": codes[0],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    ).json()

    if "refresh_token" not in payload:
        print("\n取得に失敗しました。Zohoからの応答:")
        print(payload)
        print("\nよくある原因:")
        print("  - 認可コードの期限切れ（数分で失効します。最初からやり直してください）")
        print("  - Redirect URI がAPIコンソールの登録値と一致していない")
        print("  - データセンターの選択間違い（アカウントのDCと合っていない）")
        sys.exit(1)

    print("\n" + "=" * 72)
    print(" 取得成功。以下を GitHub の Secrets / Variables に登録してください。")
    print("=" * 72)
    print("[Secrets]")
    print(f"  ZOHO_CLIENT_ID       = {client_id}")
    print(f"  ZOHO_CLIENT_SECRET   = {client_secret}")
    print(f"  ZOHO_REFRESH_TOKEN   = {payload['refresh_token']}")
    print("[Variables]")
    print(f"  ZOHO_ACCOUNTS_DOMAIN = {accounts_domain}")
    print("  OUTPUT_MODE          = api   （または both）")
    print("=" * 72)
    print("\n※ リフレッシュトークンはパスワードと同等の重要度です。")
    print("   メールやチャットに平文で貼らないでください。")


if __name__ == "__main__":
    main()
