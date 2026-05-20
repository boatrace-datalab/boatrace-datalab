"""
extract_notable_races.py
─────────────────────────
Bファイル（番組表テキスト）を解析し、
「注目レース」を抽出して JSON/CSV で出力する。

Bファイルのレイアウト（mbrace 公式仕様より）
  - 固定長テキスト、Shift-JIS エンコード
  - 1レコード = 1行（改行区切り）
  - 主なフィールド:
      [0:2]   場コード (01=桐生 〜 24=びわこ)
      [2:4]   開催日 (MMDD)
      [4:6]   レース番号 (01〜12)
      [6:8]   艇番
      [8:12]  登録番号
      [12:17] 選手名（カナ 5文字）
      ...
  ※ 実際のレイアウトはレイアウト表 (layout.html) に従って調整してください。
"""

import argparse
import csv
import json
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── 場コード対応表 ─────────────────────────────────────────────────────────────
STADIUM_MAP: dict[str, str] = {
    "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島",
    "05": "多摩川", "06": "浜名湖", "07": "蒲郡", "08": "常滑",
    "09": "津",    "10": "三国", "11": "びわこ", "12": "住之江",
    "13": "尼崎",  "14": "鳴門", "15": "丸亀",   "16": "児島",
    "17": "宮島",  "18": "徳山", "19": "下関",   "20": "若松",
    "21": "芦屋",  "22": "福岡", "23": "唐津",   "24": "大村",
}

# ── 注目判定ロジック（カスタマイズしてください）────────────────────────────────
NOTABLE_CONDITIONS = {
    "sg_pg1_grade": ["SG", "PG1"],   # グレード
    "final_race_no": 12,             # 最終レース（優勝戦）
    "noted_racers": [],              # 注目選手登録番号リスト（例: [4444, 3897]）
    "noted_stadiums": [],            # 注目場コードリスト（例: ["12", "22"]）
}


# ── Bファイルパーサー ────────────────────────────────────────────────────────────
class BFileParser:
    ENCODING = "shift_jis"

    def __init__(self, path: Path):
        self.path = path
        self.records: list[dict] = []

    def parse(self) -> list[dict]:
        text = self.path.read_text(encoding=self.ENCODING, errors="replace")
        lines = text.splitlines()
        log.info(f"  解析: {self.path.name}  行数: {len(lines)}")

        for lineno, line in enumerate(lines, 1):
            rec = self._parse_line(line)
            if rec:
                self.records.append(rec)
        log.info(f"  有効レコード: {len(self.records)} 件")
        return self.records

    def _parse_line(self, line: str) -> dict | None:
        """
        1行を辞書に変換。
        ※ 実際のBファイルのフォーマットに合わせてスライス位置を修正してください。
        """
        line = line.rstrip("\r\n")
        if len(line) < 20:
            return None

        try:
            stadium_code = line[0:2].strip()
            race_date    = line[2:6].strip()   # MMDD
            race_no      = int(line[6:8].strip())
            boat_no      = int(line[8:9].strip()) if line[8:9].strip() else 0
            racer_id     = line[9:13].strip()
            racer_name   = line[13:18].strip()
            grade        = line[18:20].strip() if len(line) > 20 else ""
        except (ValueError, IndexError):
            return None

        return {
            "stadium_code": stadium_code,
            "stadium_name": STADIUM_MAP.get(stadium_code, f"場{stadium_code}"),
            "race_date":    race_date,
            "race_no":      race_no,
            "boat_no":      boat_no,
            "racer_id":     racer_id,
            "racer_name":   racer_name,
            "grade":        grade,
        }


# ── 注目レース判定 ───────────────────────────────────────────────────────────────
def is_notable(race_key: dict, boats: list[dict]) -> tuple[bool, list[str]]:
    """
    race_key: {stadium_code, stadium_name, race_date, race_no}
    boats:    その race の艇リスト
    -> (True/False, 理由リスト)
    """
    reasons = []

    # SG / PG1 グレード
    for boat in boats:
        if boat["grade"] in NOTABLE_CONDITIONS["sg_pg1_grade"]:
            reasons.append(f"グレード: {boat['grade']}")
            break

    # 最終レース（優勝戦）
    if race_key["race_no"] == NOTABLE_CONDITIONS["final_race_no"]:
        reasons.append("最終レース（優勝戦）")

    # 注目選手
    for boat in boats:
        if boat["racer_id"] in [str(r) for r in NOTABLE_CONDITIONS["noted_racers"]]:
            reasons.append(f"注目選手: {boat['racer_name']}({boat['racer_id']})")

    # 注目場
    if race_key["stadium_code"] in NOTABLE_CONDITIONS["noted_stadiums"]:
        reasons.append(f"注目場: {race_key['stadium_name']}")

    return (len(reasons) > 0), reasons


# ── メイン ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="注目レース抽出")
    parser.add_argument("--raw-dir",  default="data/raw",       help="Bファイルがある日付ディレクトリの親")
    parser.add_argument("--out-dir",  default="data/processed", help="出力先")
    args = parser.parse_args()

    raw_root = Path(args.raw_dir)
    out_dir  = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_notable: list[dict] = []

    # raw_dir 配下の全 Bファイル（.txt / 拡張子なし）を処理
    b_files = list(raw_root.rglob("b??????")) + list(raw_root.rglob("B??????"))   # b250520 形式
    b_files += list(raw_root.rglob("*.txt")) + list(raw_root.rglob("*.TXT"))
    b_files = [f for f in b_files if f.is_file()]
    log.info(f"Bファイル候補: {len(b_files)} 個")

    for b_file in sorted(b_files):
        records = BFileParser(b_file).parse()
        if not records:
            continue

        # レースキー（場×レース番号）でグループ化
        race_groups: dict[tuple, list[dict]] = {}
        for r in records:
            key = (r["stadium_code"], r["stadium_name"], r["race_date"], r["race_no"])
            race_groups.setdefault(key, []).append(r)

        for (sc, sn, rd, rno), boats in sorted(race_groups.items()):
            race_key = {
                "stadium_code": sc,
                "stadium_name": sn,
                "race_date":    rd,
                "race_no":      rno,
            }
            notable, reasons = is_notable(race_key, boats)
            if notable:
                all_notable.append({
                    **race_key,
                    "reasons": ", ".join(reasons),
                    "boats": boats,
                })

    log.info(f"注目レース: {len(all_notable)} 件")

    # JSON 出力
    json_path = out_dir / "notable_races.json"
    json_path.write_text(
        json.dumps(all_notable, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    log.info(f"JSON 出力: {json_path}")

    # CSV 出力（Sheets 確認用）
    csv_path = out_dir / "notable_races.csv"
    flat_rows = []
    for r in all_notable:
        flat_rows.append({
            "場コード":     r["stadium_code"],
            "場名":         r["stadium_name"],
            "日付":         r["race_date"],
            "レース番号":   r["race_no"],
            "注目理由":     r["reasons"],
            "出場艇数":     len(r["boats"]),
        })
    if flat_rows:
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=flat_rows[0].keys())
            writer.writeheader()
            writer.writerows(flat_rows)
    log.info(f"CSV 出力: {csv_path}")
    log.info("抽出完了 ✓")


if __name__ == "__main__":
    main()
