"""
write_sheets.py
───────────────
data/processed/notable_races.json を読み込み、
Google スプレッドシートへ書き込む。

シート構成:
  シート名 = 実行日 (例: 2026-05-20)
  ヘッダー + 注目レース一覧

必要な権限:
  サービスアカウントに対してスプレッドシートの「編集者」権限を付与すること。
"""

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

JST    = timezone(timedelta(hours=9))
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ── スプレッドシートのヘッダー定義 ────────────────────────────────────────────
HEADERS = [
    "場コード", "場名", "日付(MMDD)", "レース番号",
    "注目理由", "出場艇数",
    "艇1_選手名", "艇1_登録番号",
    "艇2_選手名", "艇2_登録番号",
    "艇3_選手名", "艇3_登録番号",
    "艇4_選手名", "艇4_登録番号",
    "艇5_選手名", "艇5_登録番号",
    "艇6_選手名", "艇6_登録番号",
]

# ── セルスタイル ───────────────────────────────────────────────────────────────
HEADER_BG_COLOR = {"red": 0.18, "green": 0.31, "blue": 0.53}   # 紺色
HEADER_FG_COLOR = {"red": 1.0,  "green": 1.0,  "blue": 1.0}    # 白
ROW_ALT_COLOR   = {"red": 0.93, "green": 0.96, "blue": 1.0}    # 薄青（偶数行）


def build_service(sa_json_path: str):
    creds = service_account.Credentials.from_service_account_file(
        sa_json_path, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def ensure_sheet(service, spreadsheet_id: str, sheet_name: str) -> int:
    """シートが無ければ作成。sheet_id を返す。"""
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sheet in meta["sheets"]:
        if sheet["properties"]["title"] == sheet_name:
            sid = sheet["properties"]["sheetId"]
            log.info(f"シート '{sheet_name}' 既存 (id={sid})")
            return sid

    # 新規作成
    resp = service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
    ).execute()
    sid = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
    log.info(f"シート '{sheet_name}' 新規作成 (id={sid})")
    return sid


def notable_to_rows(races: list[dict]) -> list[list]:
    """注目レースリスト → スプレッドシート行リスト（ヘッダー含む）"""
    rows = [HEADERS]
    for r in races:
        boats = {b["boat_no"]: b for b in r.get("boats", [])}
        row = [
            r.get("stadium_code", ""),
            r.get("stadium_name", ""),
            r.get("race_date", ""),
            r.get("race_no", ""),
            r.get("reasons", ""),
            len(r.get("boats", [])),
        ]
        for boat_no in range(1, 7):
            b = boats.get(boat_no, {})
            row.append(b.get("racer_name", ""))
            row.append(b.get("racer_id", ""))
        rows.append(row)
    return rows


def write_values(service, spreadsheet_id: str, sheet_name: str, rows: list[list]):
    range_name = f"'{sheet_name}'!A1"
    body = {"values": rows}
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="USER_ENTERED",
        body=body,
    ).execute()
    log.info(f"  値書き込み: {len(rows)} 行")


def apply_formatting(service, spreadsheet_id: str, sheet_id: int, num_rows: int):
    """ヘッダー色・交互行色・列幅自動調整・フィルター設定"""
    num_cols = len(HEADERS)
    requests = [
        # ヘッダー背景色
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                           "startColumnIndex": 0, "endColumnIndex": num_cols},
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": HEADER_BG_COLOR,
                        "textFormat": {"foregroundColor": HEADER_FG_COLOR, "bold": True},
                        "horizontalAlignment": "CENTER",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
            }
        },
        # 偶数データ行を薄青
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": sheet_id,
                                "startRowIndex": 1, "endRowIndex": num_rows,
                                "startColumnIndex": 0, "endColumnIndex": num_cols}],
                    "booleanRule": {
                        "condition": {"type": "CUSTOM_FORMULA",
                                      "values": [{"userEnteredValue": "=ISEVEN(ROW())"}]},
                        "format": {"backgroundColor": ROW_ALT_COLOR},
                    },
                },
                "index": 0,
            }
        },
        # ヘッダー行を固定
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },
        # 列幅を自動調整
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": num_cols,
                }
            }
        },
        # フィルター設定
        {
            "setBasicFilter": {
                "filter": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0, "endRowIndex": num_rows,
                        "startColumnIndex": 0, "endColumnIndex": num_cols,
                    }
                }
            }
        },
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests}
    ).execute()
    log.info("  フォーマット適用完了")


def main():
    parser = argparse.ArgumentParser(description="Google Sheets 書き込み")
    parser.add_argument("--input-dir",       default="data/processed")
    parser.add_argument("--spreadsheet-id",  required=True)
    parser.add_argument("--sa-json",         required=True, help="サービスアカウント JSON パス")
    parser.add_argument("--sheet-name",      default="",    help="シート名（省略=当日日付）")
    args = parser.parse_args()

    # 入力 JSON 読み込み
    json_path = Path(args.input_dir) / "notable_races.json"
    if not json_path.exists():
        log.warning(f"入力ファイルが見つかりません: {json_path}")
        return

    races = json.loads(json_path.read_text(encoding="utf-8"))
    log.info(f"注目レース: {len(races)} 件")

    if not races:
        log.info("書き込み対象がありません。終了。")
        return

    # シート名（デフォルト = 当日）
    sheet_name = args.sheet_name or datetime.now(JST).strftime("%Y-%m-%d")

    # Sheets API
    service = build_service(args.sa_json)

    try:
        sheet_id = ensure_sheet(service, args.spreadsheet_id, sheet_name)
        rows = notable_to_rows(races)
        write_values(service, args.spreadsheet_id, sheet_name, rows)
        apply_formatting(service, args.spreadsheet_id, sheet_id, len(rows))
        log.info(f"Google Sheets 書き込み完了 ✓  シート: {sheet_name}")
    except HttpError as e:
        log.error(f"Sheets API エラー: {e}")
        raise


if __name__ == "__main__":
    main()
