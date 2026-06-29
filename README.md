# 日本語教育 資金・政策ウォッチ

Semiosis株式会社の `Nihongo Catch!` 販促と運用資金確保に使うため、日本語教育に関する公募・補助金・プロポーザル、在留資格・入管関連ニュースを毎朝収集し、SQLiteとMarkdownレポートへ蓄積する小さな監視プログラムです。

## できること

- Google News RSS検索と公式ページ巡回から候補記事を収集
- 「公募・補助金・プロポーザル」「ニュース（日本語教育）」「ニュース（外国人・ビザ）」「その他」に自動分類
- `Nihongo Catch!` の営業・提案に使えそうな切り口をレポートに追記
- 取得済みURLをSQLiteで重複排除
- 締切日とページ反映日を表示
- 締切後30日以内は「終了直後」として残し、締切後31日以降は通常表示から外して「終了案件」フィルターで確認
- 締切後180日を超えた案件はHTML/Markdownから外し、SQLite/CSVの履歴として保持
- グループで閲覧しやすいHTMLページとCSVを生成
- 毎朝実行できる `launchd` 設定を生成

## 動作環境

Python 3.9 以上（標準ライブラリのみ。外部依存なし）。CIは Python 3.12 で実行します。

## 初回実行

```bash
cd /Users/usausagi/Documents/Playground/日本語資金
python3 -m nihongo_funding_watch run
```

出力先:

- データベース: `data/nihongo_funding_watch.sqlite3`
- 日次レポート: `data/reports/YYYY-MM-DD.md`
- HTML: `public/index.html`
- CSV: `public/items.csv`

HTMLとCSVまでまとめて更新する通常運用コマンド:

```bash
./scripts/run_daily.sh
```

## 毎朝8時に自動実行する

```bash
cd /Users/usausagi/Documents/Playground/日本語資金
./scripts/install_launchd.sh
```

ログは `logs/launchd.out.log` と `logs/launchd.err.log` に出ます。

## グループメンバーで閲覧する

`public/` 以下に、ブラウザで開けるHTMLとCSVが生成されます。

共有フォルダに自動コピーしたい場合:

```bash
cp config/local.env.example config/local.env
```

`config/local.env` の `NIHONGO_WATCH_PUBLIC_DIR` に、Google Drive、iCloud Drive、Dropbox、社内共有フォルダなどのパスを入れてください。以後 `scripts/run_daily.sh` と毎朝実行は、そのフォルダへ `public/` の中身を同期します。

## 設定を変える

`config/default_sources.json` で検索語、公式ページ、キーワードの重みを編集できます。

自治体ページを重点的に追う場合は、最初から全自治体サイトを巡回するのではなく、次の順番で増やすのがおすすめです。

1. `google_news_queries` に都道府県名、政令市名、`外国人材`、`多文化共生`、`日本語教育`、`補助金`、`委託事業`、`プロポーザル` を組み合わせた検索語を足す。
2. 検索でよく出る自治体・外郭団体だけを `page_sources` に追加する。
3. 一覧ページのHTML構造が安定しているものは、文化庁・文科省と同じように専用パーサ化する。

優先度は、東京都、神奈川県、大阪府、愛知県、福岡県、兵庫県、埼玉県、千葉県のように、外国人材・留学生・多文化共生施策が多い自治体から上げると効率的です。

現在は、東京都、神奈川、大阪、愛知、福岡、岐阜について、自治体・外郭団体ページ向けのパーサで巡回しています。自治体パーサはPDFやExcelなどの添付ファイルを候補化せず、補助金、助成、奨励金、委託、受託事業者、プロポーザル、公募などの実務シグナルがあるページやリンクだけを残します。

## 便利なコマンド

```bash
# 直近14日分を対象に収集
python3 -m nihongo_funding_watch run --since-days 14

# Markdownレポートだけ再生成
python3 -m nihongo_funding_watch report

# HTMLページだけ再生成
python3 -m nihongo_funding_watch site

# CSVに書き出し
python3 -m nihongo_funding_watch export-csv data/export.csv

# タイトル正規化ベースの重複チェック
python3 -m nihongo_funding_watch check-duplicates

# テスト
python3 -m unittest discover -s tests
```
