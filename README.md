# ボートレース Bファイル → Google Sheets 自動パイプライン

## 全体構成

```
GitHub Actions (毎朝 7:00 JST)
  │
  ├─① fetch_b_files.py
  │     www1.mbrace.or.jp から Bファイル(LZH)をダウンロード・解凍
  │
  ├─② extract_notable_races.py
  │     Bファイルを解析して「注目レース」を抽出 → JSON/CSV
  │
  └─③ write_sheets.py
        Google Sheets API でスプレッドシートに書き込み
```

---

## セットアップ手順

### 1. Google Cloud の準備

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成（または選択）
2. **Google Sheets API** を有効化
3. **サービスアカウント**を作成  
   IAM と管理 → サービスアカウント → 作成
4. サービスアカウントの **JSON キーをダウンロード**

### 2. スプレッドシートの準備

1. Google スプレッドシートを新規作成
2. スプレッドシートの URL から **スプレッドシートID** をコピー  
   例: `https://docs.google.com/spreadsheets/d/【ここ】/edit`
3. スプレッドシートをサービスアカウントのメールアドレスに **「編集者」で共有**

### 3. GitHub Secrets の設定

リポジトリの Settings → Secrets and variables → Actions → New repository secret

| Secret 名 | 値 |
|---|---|
| `GCP_SERVICE_ACCOUNT_JSON` | JSON キーファイルの**中身全体**をコピペ |
| `SPREADSHEET_ID` | スプレッドシートID |

### 4. リポジトリへ push

```bash
git add .
git commit -m "feat: ボートレースBファイル自動取得パイプライン"
git push origin main
```

Actions タブから手動実行（workflow_dispatch）でテスト可能。

---

## 注目レース判定のカスタマイズ

`scripts/extract_notable_races.py` の `NOTABLE_CONDITIONS` を編集:

```python
NOTABLE_CONDITIONS = {
    "sg_pg1_grade":   ["SG", "PG1"],   # 対象グレード
    "final_race_no":  12,              # 最終レース番号（優勝戦）
    "noted_racers":   [4444, 3897],    # 注目選手の登録番号
    "noted_stadiums": ["12", "22"],    # 注目場コード (住之江, 福岡 等)
}
```

---

## Bファイルのレイアウトについて

`scripts/extract_notable_races.py` の `_parse_line()` メソッドのスライス位置は、
公式レイアウト表に合わせて調整してください。

公式レイアウト表: https://www.boatrace.jp/owpc/pc/extra/data/layout.html

---

## スケジュール変更

`.github/workflows/boatrace_daily.yml` の cron を編集:

```yaml
- cron: '0 22 * * *'   # UTC 22:00 = JST 翌 07:00
```

[crontab.guru](https://crontab.guru/) で確認できます。

---

## ファイル構成

```
.
├── .github/workflows/
│   └── boatrace_daily.yml      # GitHub Actions ワークフロー
├── scripts/
│   ├── fetch_b_files.py        # Bファイル取得
│   ├── extract_notable_races.py # 注目レース抽出
│   └── write_sheets.py         # Sheets書き込み
├── data/
│   ├── raw/                    # ダウンロード生データ
│   └── processed/              # 抽出済みデータ
├── requirements.txt
└── README.md
```
