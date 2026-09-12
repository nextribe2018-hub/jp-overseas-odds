# 日本関連 海外オッズ相場表

公開URL: https://odds.icurate.net/ （GitHub Pages、カスタムドメイン）。iCurate の HP https://icurate.net/ からリンク。

海外の予測市場（Polymarket / Kalshi / Manifold）に上場している「日本」に関わる賭けを収集し、
掛け率（暗黙の確率）の一覧と時系列変化を 1 枚の HTML で表示するツール。

## 機能

- 日本関連マーケット（政治・経済・地政学・MLB/大谷・NPB・大相撲 など）と、海外で人気のマーケット（米中間選挙・FOMC・ウクライナ停戦・スーパーボウル など、分野ごとに約3件）
- 選択肢ごとの確率・倍率（欧州式オッズ）・24h/7日変化・30日推移・時系列チャート
- 各マーケットの「賭けを見る」（原文サイト）と「日本語訳で見る」（Google翻訳経由）リンク、関連ニュース（Googleニュース日本語・上位3件）
- アーカイブ（検証）：結果が出たマーケットは削除せず、節目のオッズ（1ヶ月前・1週間前・1日前・直前・最終）、オッズを大きく動かした日と前後のニュース（`data/news_log.json` に日々蓄積）、AI の振り返り解説を併記。結果・終了までの価格推移・掲示板の書き込みを `data/archive.json` に保存し、ページ末尾の「アーカイブ」に表示
- AI解説：Claude Opus 5 が各マーケットの解説を毎朝生成（`ai_commentary.py`）。注目の日本関連3件＋海外2件は掲示板へ自動投稿、それ以外は誰かが掲示板を開いた時に投稿される。GitHub Secrets に `ANTHROPIC_API_KEY` が必要
- 掲示板：マーケットごとに1つ。（例：利上げ／据え置き／利下げ）ごとに匿名の意見を並べて比較。Claude Artifact 版では共有DBに保存され全員に共有、GitHub Pages 版は端末内保存のみ

## 構成

| ファイル | 役割 |
|---|---|
| `config/watchlist.json` | 監視対象マーケットの一覧（日本語タイトル・分野・表示する選択肢の絞り込み） |
| `config/names_ja.json` | 選択肢名（選手・チーム・力士・候補者など）の日本語訳辞書 |
| `fetch_odds.py` | 3 サイトの公開 API から現在価格と価格履歴を取得し `data/latest.json` を生成。実行のたびに `data/snapshots.jsonl` へ独自スナップショットを追記 |
| `build_site.py` + `template.html` | `data/latest.json` を埋め込んだ単一ファイル `site/index.html` を生成 |
| `update.sh` | 取得 → 生成をまとめて実行 |
| `make_digest.py` | 毎日のメール本文（HTML）と件名を生成 |
| `ai_commentary.py` | Claude でAI解説を生成し `data/ai_comments.json` に保持、注目マーケットへ自動投稿 |
| `docs/index.html` | 完成した閲覧ページ（GitHub Pages で公開） |
| `.github/workflows/daily.yml` | 毎朝 07:30 JST に取得→生成→コミット→メール送信する GitHub Actions |

## 使い方

```bash
./update.sh
open docs/index.html
```

API キーは不要（すべて公開エンドポイント）。1 回の取得は 2 分前後。

## 監視対象を増やす

`config/watchlist.json` の `items` に追加する。

- Polymarket: `https://gamma-api.polymarket.com/public-search?q=キーワード` で event の `id` を調べる
- Kalshi: `https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=...` で `event_ticker` を調べる
- Manifold: 市場 URL 末尾の slug から `https://api.manifold.markets/v0/slug/<slug>` で `id` を調べる

`keep`（選択肢名のキーワード）と `top`（上位 N 件）で表示する選択肢を絞れる。

## 時系列データ

- Polymarket: CLOB `prices-history`（全期間は日次、直近 1 週間は 1 時間足）
- Kalshi: `candlesticks`（365 日は日次、直近 7 日は 1 時間足）
- Manifold: 約定履歴（`bets`）から確率推移を復元
- これらに加えて、本ツールを実行するたびの価格を `data/snapshots.jsonl` に蓄積し、チャートに合成する

## 注意

表示する確率は各市場の YES 価格。Manifold はプレイマネー市場のため参考値。
本ツールは情報整理を目的とし、賭博への参加を勧めるものではない。

## 毎日メールで受け取る（GitHub Actions）

MacBook を閉じていても GitHub 側で毎朝 07:30 JST に実行され、Gmail の SMTP でメールを送ります。
初回のみ、送信元 Gmail の **アプリパスワード** をリポジトリの Secrets に登録してください。

1. 送信元にする Google アカウントで 2 段階認証を有効にし、<https://myaccount.google.com/apppasswords> で「メール」用のアプリパスワード（16 桁）を発行
2. リポジトリの Settings → Secrets and variables → Actions で登録
   - Secret `MAIL_USERNAME` … 送信元 Gmail アドレス
   - Secret `MAIL_PASSWORD` … 発行した 16 桁のアプリパスワード
   - Variable `MAIL_TO` … 受信したいメールアドレス（複数はカンマ区切り）
3. Actions タブ → `daily-odds` → **Run workflow** で手動実行して届くことを確認

Secrets が未登録の間も、取得・サイト更新・コミットは毎日動き、メール送信だけスキップされます。
配信時刻を変えるには `.github/workflows/daily.yml` の `cron`（UTC 表記）を編集します。

## 公開掲示板にする（Firebase / 無料）

GitHub Pages 版の掲示板を「誰でも匿名で書き込める共有掲示板」にするには、無料の Firebase（Firestore）を 1 つ作り、接続情報を `config/firebase.json` に置くだけです。

1. <https://console.firebase.google.com> → 「プロジェクトを追加」→ 名前を付けて作成（Google アナリティクスは不要）
2. 左メニュー「構築」→「Firestore Database」→「データベースを作成」→ ロケーション `asia-northeast1`（東京）→「本番環境モード」で有効化
3. 「ルール」タブに、このリポジトリの `firestore.rules` の内容を貼り付けて「公開」
4. 歯車 →「プロジェクトの設定」→「マイアプリ」→ ウェブ（`</>`）→ ニックネームを付けて登録 → 表示される `firebaseConfig` の中身を `config/firebase.json` に保存（`config/firebase.json.example` と同じ形）
5. コミットして push。次回の自動更新（または `./update.sh`）でページが Firestore に接続され、画面の掲示板に「公開掲示板」と表示されます

料金: Firebase の Spark プラン（無料枠）は Firestore 1 GiB・1 日あたり読み取り 5 万件／書き込み 2 万件まで無料で、クレジットカード登録も不要。上限に達しても課金されず、その日の書き込みが止まるだけです。
`firebase.json` の apiKey は公開前提の識別子で、書き込み制限は `firestore.rules` 側で行います。
