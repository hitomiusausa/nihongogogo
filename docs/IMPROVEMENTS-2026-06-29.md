# コード改善メモ（2026-06-29）

コードレビューで見つかった問題点を、重要度順に12項目すべて改善した記録。
テストは 11 → 28 に増え、Python 3.10 / 3.12 の両方で全て pass。`site` コマンドの実行も確認済み。

## 改善した内容

### 要対応（挙動・運用に効く）

1. **CIでDBを永続化**
   `.gitignore` から `data/*.sqlite3` を除外し、`daily-update.yml` でDBもコミットするように変更。
   これまでは日次実行のたびにDBが空からやり直しになり、日をまたいだ重複排除・スコアマージ・履歴蓄積が永続化されていなかった。あわせてCIのPythonを `3.x` → `3.12` に固定。
   - `.gitignore`, `.github/workflows/daily-update.yml`

2. **取得エラーをCLIで表示**
   `run` コマンドが `errors=N` を出力し、各エラーメッセージを stderr に表示するように。
   これまでは `run_collection` がエラーを集めていたのに画面に出ず、ソースが壊れても気づけなかった。
   - `nihongo_funding_watch/cli.py`

3. **SQLite接続を確実にクローズ**
   `contextlib.closing` で全接続を包み、接続リークを解消。
   `with sqlite3.connect() as db:` は commit はするが close はしないため、特にアイテム1件ごとに接続を開いていた upsert で接続が溜まっていた。
   - `nihongo_funding_watch/storage.py`

### 中くらい

4. **Python最低バージョンを明記＋互換化**
   `datetime.UTC`（3.11+ 専用）を `timezone.utc`（3.9+）に置換し、3.9以上で動くように。README と requirements.txt に動作環境を明記。
   - `fetchers.py`, `pipeline.py`, `storage.py`, `README.md`, `requirements.txt`

5. **デッドコード削除**
   どこからも呼ばれていなかった `enrich_from_detail_page` と `should_fetch_detail` を削除。
   - `nihongo_funding_watch/pipeline.py`

6. **config内の正規表現を検証**
   `load_config` で `exclude_title_patterns` / `generic_link_title_patterns` / `allow_url_patterns` を事前に `re.compile`。不正なパターンは `ValueError` で起動時に分かるように（メッセージにどの設定の何が悪いか含む）。
   - `nihongo_funding_watch/config.py`

7. **SSL検証フォールバックを安全化**
   証明書エラー時の無検証フォールバック時に警告ログを出力。`allow_insecure_fallback` 引数で挙動を制御可能に。
   - `nihongo_funding_watch/fetchers.py`

### パフォーマンス・保守性

8. **パフォーマンス改善**
   - 正規表現を config ロード時に1度だけコンパイルして再利用（ループ内の都度コンパイルを廃止）
   - 収集結果を**1トランザクションで一括 upsert**（`upsert_scored_items`）。アイテムごとに接続を開かない
   - `config.py`, `fetchers.py`, `pipeline.py`, `storage.py`

9. **マイグレーションをバージョンgate**
   `PRAGMA user_version` で、フルテーブルスキャンを伴うデータ移行（`migrate_legacy_categories` 等）を初回のみ実行。これまではCLI起動のたびに毎回走っていた。
   - `nihongo_funding_watch/storage.py`（`SCHEMA_VERSION = 1`）

10. **元号マップの重複を解消**
    `fetchers.parse_japanese_date` 内のインライン辞書を `deadlines.ERA_START_YEARS` に一本化。
    - `nihongo_funding_watch/fetchers.py`

11. **hrefスキームをallowlist化**
    `safe_url()` を追加し、カード見出しリンクで `http(s)` 以外のスキーム（`javascript:` 等）を `#` に無害化（防御的XSS対策）。HTMLエスケープ自体は元々徹底されていた。
    - `nihongo_funding_watch/site.py`

12. **テストを追加**
    config / pipeline / summarize / site / storage の主要関数にテストを追加（11 → 28 件）。
    - `tests/test_config.py`, `test_pipeline.py`, `test_summarize.py`, `test_site.py`, `test_storage_batch.py`

## 検証結果

- `python3 -m unittest discover -s tests` → 28 tests OK（Python 3.10）
- `uv run --python 3.12 python -m unittest discover -s tests` → 28 tests OK
- `python -m nihongo_funding_watch site` → HTML・画像・レポートの生成を確認

## 変更ファイル

コード10ファイル（`.github/workflows/daily-update.yml`, `.gitignore`, `README.md`,
`requirements.txt`, `cli.py`, `config.py`, `fetchers.py`, `pipeline.py`, `site.py`,
`storage.py`）＋ 新規テスト5ファイル。
