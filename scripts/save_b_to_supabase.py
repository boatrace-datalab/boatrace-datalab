"""
save_b_to_supabase.py
BファイルをパースしてSupabaseのentryテーブルに保存する。

使い方:
  python3 scripts/save_b_to_supabase.py --date 20260523
  python3 scripts/save_b_to_supabase.py  # 当日分
"""

import argparse
import io
import logging
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL   = "https://www1.mbrace.or.jp/od2/B/{ym}/b{ymd}.lzh"
USER_AGENT = "Mozilla/5.0 (compatible; BoatraceAnalyzer/1.0)"
JST        = timezone(timedelta(hours=9))

SEVENZIP_PATHS = [
    "/usr/bin/7z",
    "C:/Program Files/7-Zip/7z.exe",
    "/c/Program Files/7-Zip/7z.exe",
]

SUPABASE_HOST = "aws-1-ap-northeast-1.pooler.supabase.com"
SUPABASE_PORT = 5432
SUPABASE_DB   = "postgres"
SUPABASE_USER = "postgres.xapywturbedupxdcbkfg"
SUPABASE_PASS = os.environ.get("SUPABASE_PASS", "!#rd99R9n/z#+/U")  # 環境変数 or 直接入力

STADIUM_MAP = {str(i).zfill(2): i for i in range(1, 25)}
ZEN2HAN = str.maketrans("１２３４５６７８９０", "1234567890")

def get_pg_conn():
    return psycopg2.connect(
        host=SUPABASE_HOST, port=SUPABASE_PORT,
        database=SUPABASE_DB, user=SUPABASE_USER,
        password=SUPABASE_PASS
    )

def find_7zip():
    for p in SEVENZIP_PATHS:
        if Path(p).exists():
            return p
    try:
        result = subprocess.run(["7z", "--help"], capture_output=True)
        if result.returncode == 0:
            return "7z"
    except FileNotFoundError:
        pass
    return None

def extract_lzh(lzh_bytes):
    try:
        import lhafile
        lhf = lhafile.LhaFile(io.BytesIO(lzh_bytes))
        for name in lhf.namelist():
            return lhf.read(name).decode("shift_jis", errors="replace")
    except ImportError:
        pass

    sevenzip = find_7zip()
    if sevenzip:
        with tempfile.TemporaryDirectory() as tmpdir:
            lzh_path = Path(tmpdir) / "b.lzh"
            lzh_path.write_bytes(lzh_bytes)
            subprocess.run([sevenzip, "e", str(lzh_path), f"-o{tmpdir}", "-y"], capture_output=True)
            for f in list(Path(tmpdir).glob("*.TXT")) + list(Path(tmpdir).glob("*.txt")):
                return f.read_text(encoding="shift_jis", errors="replace")
    return None

def download_lzh(dt):
    ym  = dt.strftime("%Y%m")
    ymd = dt.strftime("%y%m%d")
    url = BASE_URL.format(ym=ym, ymd=ymd)
    log.info(f"ダウンロード: {url}")
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    if r.status_code == 404:
        log.info("  404 (開催なし)")
        return None
    r.raise_for_status()
    return r.content

def parse_b_file(text, race_date_str):
    """
    Bファイルをパースしてentryレコードを返す
    選手行フォーマット:
    艇番(1) 登録番号(4) 選手名(可変) 年齢(2) 支部(2-3) 体重(2) 級別(2)
    全国勝率 全国2率 当地勝率 当地2率 モーターNO モーター2率 ボートNO ボート2率 今節成績... 早見
    """
    lines = text.splitlines()
    entries = []

    current_stadium_code = None
    current_race_no      = None
    current_deadline     = ""
    in_data              = False

    for line in lines:
        # 場コード
        m = re.match(r"^(\d{2})BBGN", line)
        if m:
            current_stadium_code = m.group(1)
            continue

        # レース番号と締切時刻
        m = re.search(r"[\u3000\s]*([１-９０\d]+)Ｒ", line)
        if m and current_stadium_code:
            current_race_no  = int(m.group(1).translate(ZEN2HAN))
            in_data          = False
            # 締切時刻
            t = re.search(r"(\d{1,2}：\d{2})", line)
            current_deadline = t.group(1) if t else ""
            continue

        if re.match(r"^-{10,}", line):
            in_data = True
            continue

        if in_data and current_stadium_code and current_race_no:
            entry = parse_entry_line(line, race_date_str, current_stadium_code,
                                     current_race_no, current_deadline)
            if entry:
                entries.append(entry)

    return entries

def parse_entry_line(line, race_date_str, stadium_code, race_no, deadline):
    """
    選手行をパース
    例: 1 4772石丸海渡32香川56A1 6.40 50.41 7.57 60.00 17 22.22138 39.29 1 6 234 6   10
    """
    # 艇番と登録番号
    m = re.match(r"^([1-6])\s+(\d{4})", line)
    if not m:
        return None

    boat_no  = int(m.group(1))
    racer_no = int(m.group(2))
    rest     = line[m.end():]

    # 選手名（登録番号後から年齢の前まで）
    # 年齢は2桁数字+支部(漢字)+体重(数字)+級別
    m2 = re.search(r"(\d{2})(\S{2,3})(\d{2})(A1|A2|B1|B2)", rest)
    if not m2:
        return None

    racer_name = rest[:m2.start()].strip()
    age        = int(m2.group(1))
    branch     = m2.group(2).strip()
    weight     = float(m2.group(3))
    grade      = m2.group(4)
    after_grade = rest[m2.end():]

    # 数値データ: 全国勝率 全国2率 当地勝率 当地2率 モーターNO モーター2率 ボートNO ボート2率
    nums = re.findall(r"[\d.]+", after_grade)
    try:
        national_win  = float(nums[0]) if len(nums) > 0 else 0.0
        national_2    = float(nums[1]) if len(nums) > 1 else 0.0
        local_win     = float(nums[2]) if len(nums) > 2 else 0.0
        local_2       = float(nums[3]) if len(nums) > 3 else 0.0
        motor_no      = int(nums[4])   if len(nums) > 4 else 0
        motor_2       = float(nums[5]) if len(nums) > 5 else 0.0
        boat_no_eq    = int(nums[6])   if len(nums) > 6 else 0
        boat_2        = float(nums[7]) if len(nums) > 7 else 0.0
    except (ValueError, IndexError):
        return None

    # 今節成績（残りの文字から数字・F・S・Kなどを取得）
    after_boat = after_grade
    # モーター2率以降の位置を特定
    pos = 0
    for _ in range(8):
        m3 = re.search(r"[\d.]+", after_boat[pos:])
        if m3:
            pos += m3.end()
        else:
            break
    session_part = after_boat[pos:].strip()
    # 今節成績: 数字・F・S・K・空白のみ
    session_results = re.sub(r"[^\dFSKfsk\s]", "", session_part).strip()

    # race_id
    venue_id  = STADIUM_MAP.get(stadium_code, 0)
    date_part = race_date_str.replace("-", "")
    race_id   = int(f"{date_part}{venue_id:02d}{race_no:02d}")

    return {
        "race_id":          race_id,
        "boat_no":          boat_no,
        "racer_no":         racer_no,
        "racer_name":       racer_name,
        "age":              age,
        "branch":           branch,
        "weight":           weight,
        "grade":            grade,
        "national_win_rate": national_win,
        "local_win_rate":   local_win,
        "motor_no":         motor_no,
        "boat_no_eq":       boat_no_eq,
        "vote_deadline":    deadline,
        "session_results":  session_results,
    }

def save_to_supabase(pg_conn, entries):
    if not entries:
        return 0
    with pg_conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO entry (
                race_id, boat_no, racer_no, racer_name, age, branch, weight, grade,
                national_win_rate, local_win_rate, motor_no, boat_no_eq,
                vote_deadline, session_results
            ) VALUES %s
            ON CONFLICT (race_id, boat_no) DO UPDATE SET
                racer_no         = EXCLUDED.racer_no,
                racer_name       = EXCLUDED.racer_name,
                session_results  = EXCLUDED.session_results,
                vote_deadline    = EXCLUDED.vote_deadline
        """, [(e["race_id"], e["boat_no"], e["racer_no"], e["racer_name"],
               e["age"], e["branch"], e["weight"], e["grade"],
               e["national_win_rate"], e["local_win_rate"],
               e["motor_no"], e["boat_no_eq"],
               e["vote_deadline"], e["session_results"]) for e in entries])
    pg_conn.commit()
    return len(entries)

def process_date(dt, pg_conn):
    race_date_str = dt.strftime("%Y-%m-%d")
    log.info(f"=== {race_date_str} ===")
    data = download_lzh(dt)
    if not data:
        return 0
    text = extract_lzh(data)
    if not text:
        return 0
    entries = parse_b_file(text, race_date_str)
    log.info(f"  パース: {len(entries)}エントリー")
    saved = save_to_supabase(pg_conn, entries)
    log.info(f"  保存: {saved}件 ✓")
    return saved

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="")
    args = parser.parse_args()

    if not SUPABASE_PASS:
        log.error("SUPABASE_PASSを設定してください（環境変数またはスクリプト内）")
        return

    pg_conn = get_pg_conn()

    if args.date:
        dt = datetime.strptime(args.date, "%Y%m%d").replace(tzinfo=JST)
    else:
        dt = datetime.now(JST)

    process_date(dt, pg_conn)
    pg_conn.close()
    log.info("完了 ✓")

if __name__ == "__main__":
    main()
