# 日経平均 自動取得パイプライン v2（切替式）

日経平均株価を毎営業日おきに自動取得し、Zoho Sheet へ流し込み続ける無料の仕組みです。
プログラミング経験がなくても、この手順どおりに進めれば動きます。

**この版の特徴：出力方式を環境変数1つで切り替えられます。**

```
                                    ┌── OUTPUT_MODE=csv ──▶ CSVをWeb公開 ──▶ Zoho Sheetが取り込む
[Yahoo Finance] ──▶ [GitHub Actions] ┤
                                    └── OUTPUT_MODE=api ──▶ Zoho Sheet APIへ直接書き込み
```

---

## まず決めること：どちらの方式で始めるか

| | **csv 方式（推奨）** | **api 方式** |
|---|---|---|
| セットアップ時間 | 約15分 | 約45分 |
| Zoho APIの登録 | **不要** | 必要 |
| リフレッシュトークン発行 | **不要** | 必要 |
| GitHub Secrets | **0個** | 4個 |
| リポジトリの公開設定 | **Public必須**（無料プランの場合） | Private可 |
| データの見え方 | CSVが誰でも閲覧可能 | 非公開 |
| Zoho側の更新頻度 | 無料プランは1日1回 | 書き込んだ瞬間 |

**迷ったら `csv` 方式です。** 株価は公開情報なので、Publicリポジトリでも実害はありません。
あとから `api` 方式へ切り替えることもできます（環境変数を1つ変えるだけ）。

> **重要：** GitHub Pages は、無料プランでは **Public リポジトリでのみ**利用できます。
> 公式ドキュメントの記載：「GitHub Pages is available in public repositories with GitHub Free
> ..., and in public and private repositories with GitHub Pro, GitHub Team, ...」
> Privateのまま使いたい場合は `api` 方式を選んでください。

---

# A. csv 方式のセットアップ（約15分）

## 手順1：GitHubにアップロードする

1. GitHub にログイン →右上「+」→「New repository」
   - 名前：`nikkei-auto-pipeline` など
   - **Public を選択**（無料プランでPagesを使うため）
2. このZIPの中身を、フォルダ構成を崩さずアップロード
   （「Add file」→「Upload files」にドラッグ＆ドロップ）
3. 「Actions」タブ →「I understand my workflows, go ahead and enable them」をクリック

## 手順2：GitHub Pages を有効化する

1. 「Settings」→ 左メニュー「Pages」
2. **Source** を `Deploy from a branch` にする
3. **Branch** を `main`、フォルダを **`/docs`** にして「Save」
4. 1〜2分待つと、画面上部に公開URLが表示されます

```
https://<あなたのユーザー名>.github.io/nikkei-auto-pipeline/
```

このURLを開いて動作確認ページが表示されれば成功です。
CSVのURLはその1階層下になります。

```
https://<あなたのユーザー名>.github.io/nikkei-auto-pipeline/stock_data_cleaned.csv
```

> **Pagesの設定が面倒な場合の代替：** 有効化せずに次のURLでも同じCSVを取得できます。
> `https://raw.githubusercontent.com/<ユーザー名>/<リポジトリ名>/main/docs/stock_data_cleaned.csv`

## 手順3：動作確認する

1. 「Actions」タブ →「日経平均 自動取得パイプライン」→「Run workflow」
2. `dry_run` を **true** のまま実行（書き込みをしない安全なテスト）
3. 緑のチェック ✅ になり、ログに次のように出れば成功です

```
最新データ: 2026-08-13 終値=42500.0 出来高=1100
[dry-run] CSV書き出しをスキップします
```

4. もう一度「Run workflow」→ `dry_run` を **false** にして本番実行
5. 手順2の動作確認ページを再読み込みし、直近10営業日の表が出れば完了です

## 手順4：Zoho Sheet につなぐ

1. Zoho Sheet（https://sheet.zoho.com）で新しいワークブックを作成
2. **メニューの「データ」→「データ接続」** を開く
3. 接続元として **URL** を選び、手順2のCSVのURLを貼り付ける
4. 更新頻度を「定期的に更新」→「毎日」に設定して保存

> **`IMPORTDATA` 関数は使えません。** これは Google Sheets の関数で、Zoho Sheet には存在しません。
> Zoho Sheet にあるのは `IMPORTRANGE`（Zoho Sheet同士の連携専用）です。
> 外部URLからの取り込みは、必ず上記の「データ接続」機能を使ってください。
> なお無料プランの更新頻度は1日1回まで（有料プランなら1時間ごと）です。

**シートのヘッダーは手入力しないでください。** データ接続がCSVの1行目
（`Date,Close,Volume`）をそのままヘッダーとして展開します。手入力した内容は
上書きされるか、範囲の衝突エラーになります。

**これでcsv方式は完了です。** 以降は毎営業日16:30(JST)に自動更新されます。

---

# B. api 方式のセットアップ（約45分）

csv方式の手順1まで済ませたうえで（Pagesの有効化は不要、Privateでも可）、以下を追加します。

## 手順B-1：Zoho Sheet を用意する

1. Zoho Sheet で新しいワークブックを作成
2. 1行目に次のヘッダーを入力

   | A | B | C | D |
   |---|---|---|---|
   | Date | Close | Volume | UpdatedAt |

3. URLから **リソースID** を控える
   （`https://sheet.zoho.com/sheet/open/` に続く文字列）

## 手順B-2：Zoho APIコンソールでアプリを登録する

1. https://api-console.zoho.com/ →「ADD CLIENT」→「Server-based Applications」
2. 入力内容
   - Client Name：任意（例 `NikkeiPipeline`）
   - Homepage URL：任意（例 `https://github.com`）
   - **Authorized Redirect URIs：`https://localhost`** ←完全一致が必須
3. 表示された **Client ID** と **Client Secret** を控える

## 手順B-3：リフレッシュトークンを発行する

ご自身のパソコンで**1回だけ**実行します。

```bash
pip install requests
python get_zoho_refresh_token.py
```

画面の指示に従うと、最後に登録すべき値が一覧で表示されます。

> データセンターの選択に注意してください。日本のアカウントは
> **`https://accounts.zoho.jp`** です（`.co.jp` ではありません）。

## 手順B-4：GitHubに登録する

「Settings」→「Secrets and variables」→「Actions」で登録します。

**Secrets タブ**（秘密情報）

| 名前 | 値 |
|---|---|
| `ZOHO_CLIENT_ID` | 手順B-2の値 |
| `ZOHO_CLIENT_SECRET` | 手順B-2の値 |
| `ZOHO_REFRESH_TOKEN` | 手順B-3の値 |
| `ZOHO_RESOURCE_ID` | 手順B-1の値 |

**Variables タブ**（秘密でない設定値）

| 名前 | 値 |
|---|---|
| `OUTPUT_MODE` | `api`（CSVも併用するなら `both`） |
| `ZOHO_WORKSHEET_NAME` | `Sheet1` |
| `ZOHO_ACCOUNTS_DOMAIN` | 手順B-3で表示された値 |

## 手順B-5：動作確認する

csv方式の手順3と同じです。`dry_run=true` で試してから `false` で本番実行し、
Zoho Sheet に1行追加されることを確認してください。

---

## 実行結果の見方

| 表示 | 意味 | やること |
|---|---|---|
| ✅ 緑のチェック | 正常終了、または休場日で正しくスキップ | なし |
| ❌ 赤い× | 何らかの失敗 | 自動でIssueが作られます。下の表を参照 |

失敗すると「Issues」タブにお知らせが作成されます。**すでに未解決のIssueがある場合は
新規作成せずコメントを追記する**ので、連日失敗してもIssueが増殖しません。

メールでも受け取りたい場合は、GitHubの Settings → Notifications で
「Issues」の通知をONにしてください。

---

## トラブル対応マトリクス

| ケース | 検知方法 | 対処 |
|---|---|---|
| 一時的な通信エラー | Pythonの例外処理 | 最大5回、1→2→4→8秒間隔で自動リトライ。それでも失敗したらActionsから Re-run |
| データ構造の変化 | 列の存在チェック・前日比チェック | `sys.exit(1)`で停止。**汚れたデータは書き込まれません**。ログを見て原因を特定 |
| 市場の休場 | 土日・祝日・年末年始(12/31〜1/3)判定 | 自動でスキップ（正常終了）。何もしなくてOK |
| 認証切れ (401) | Zoho APIの応答コード | `get_zoho_refresh_token.py` を再実行しSecretsを更新 |
| レート制限 (429) | Zoho APIの応答コード | cronの実行間隔を広げる |
| Pagesが404 | ブラウザで確認 | リポジトリがPublicか、Pagesのフォルダが `/docs` か確認 |

---

## 自分で確かめる：自己テスト

ネットワーク接続なしで、ロジックが正しいことを確認できます。

```bash
pip install -r requirements.txt
python tests/test_pipeline.py
```

休場判定・年末年始・重複排除・欠損処理・安全弁・モード切替の
**26項目**を検証します。GitHub Actions上でも毎回自動実行されるので、
コードを書き換えて壊した場合はデータ取得の前に気づけます。

---

## よくある質問

**Q. 銘柄を変えたい**
Variables に `TICKER_SYMBOL` を追加します（例：トヨタ自動車 `7203.T`）。コード編集は不要です。

**Q. 実行時刻を変えたい**
`.github/workflows/nikkei-pipeline.yml` の `cron: '30 7 * * 1-5'` を編集します。
cronはUTCなので、**日本時間から9時間引いた値**を指定してください。
現在の設定は UTC 7:30 = JST 16:30（東証の取引終了後）です。

**Q. 取得期間を変えたい**
Variables に `HISTORY_PERIOD` を追加します（例：`1y`、`max`）。

**Q. 「前日比20%超」で止まってしまった**
Variables に `MAX_DAILY_MOVE_PCT` を追加して閾値を調整できます。
この判定は「株価の桁がずれた」「単位が変わった」といったデータ破損を捕まえるためのものです。
実際の暴落・暴騰で止まった場合は、値を広げて Re-run してください。

**Q. csv方式からapi方式に乗り換えたい**
Variables の `OUTPUT_MODE` を `api`（または `both`）に変え、手順B-1〜B-4を行うだけです。
コードの書き換えは不要です。

**Q. Zoho Sheet側で数値がテキスト扱いになる**
表示用の列で `VALUE()` / `DATEVALUE()` / `IFERROR()` を使ってください。
このスクリプトは生データをそのまま渡す設計で、見た目の整形はシート側の役割です。

---

## ファイル構成

```
nikkei-auto-pipeline/
├── fetch_and_push.py                     … 本体（csv / api / both を切替）
├── get_zoho_refresh_token.py             … api方式のときだけ使う鍵発行ウィザード
├── requirements.txt
├── .env.example                          … 設定の見本
├── tests/test_pipeline.py                … 自己テスト（ネット接続不要）
├── docs/
│   ├── index.html                        … GitHub Pages の動作確認ページ
│   └── stock_data_cleaned.csv            … 出力先（初回実行で中身が入ります）
├── .github/workflows/nikkei-pipeline.yml … 自動実行の設定
└── README.md
```

## 安全に関する注意

- `ZOHO_CLIENT_SECRET` と `ZOHO_REFRESH_TOKEN` はパスワードと同等です。
  GitHub Secrets 以外の場所（コード・README・チャット）に書かないでください。
- 実際の値を書いた `.env` を誤ってコミットしないよう注意してください
  （`.env.example` は見本なので安全です）。
- csv方式では株価データが公開されます。株価は公開情報ですが、
  非公開にしたい場合は api 方式を選んでください。
