"""
fetch_k_files.py
Kファイル（競走成績）を取得してSupabaseに保存する。

使い方:
  python3 scripts/fetch_k_files.py --date 20260523
  python3 scripts/fetch_k_files.py --from 20260509 --to 20260523
  python3 scripts/fetch_k_files.py  # 当日分
"""

import argparse
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

BASE_URL      = "https://www1.mbrace.or.jp/od2/K/{ym}/k{ymd}.lzh"
USER_AGENT    = "Mozilla/5.0 (compatible; BoatraceAnalyzer/1.0)"
JST           = timezone(timedelta(hours=9))
SEVENZIP_PATHS = [
    "/usr/bin/7z",                        # Linux (GitHub Actions)
    "C:/Program Files/7-Zip/7z.exe",      # Windows
    "/c/Program Files/7-Zip/7z.exe",      # Git Bash
]

SUPABASE_HOST = "aws-1-ap-northeast-1.pooler.supabase.com"
SUPABASE_PORT = 5432
SUPABASE_DB   = "postgres"
SUPABASE_USER = "postgres.xapywturbedupxdcbkfg"
SUPABASE_PASS = os.environ.get("SUPABASE_PASS", "")

STADIUM_MAP = {str(i).zfill(2): i for i in range(1, 25)}

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
    # PATHから探す
    try:
        result = subprocess.run(["7z", "--help"], capture_output=True)
        if result.returncode == 0:
            return "7z"
    except FileNotFoundError:
        pass
    return None

def extract_lzh(lzh_bytes):
    """LZHバイト列をテキストに変換"""
    # まずlhafileを試す
    try:
        import lhafile, io
        lhf = lhafile.LhaFile(io.BytesIO(lzh_bytes))
        for name in lhf.namelist():
            return lhf.read(name).decode("shift_jis", errors="replace")
    except ImportError:
        pass

    # 7-Zipを試す
    sevenzip = find_7zip()
    if sevenzip:
        with tempfile.TemporaryDirectory() as tmpdir:
            lzh_path = Path(tmpdir) / "k.lzh"
            lzh_path.write_bytes(lzh_bytes)
            result = subprocess.run(
                [sevenzip, "e", str(lzh_path), f"-o{tmpdir}", "-y"],
                capture_output=True
            )
            for f in Path(tmpdir).glob("*.TXT"):
                return f.read_text(encoding="shift_jis", errors="replace")
            for f in Path(tmpdir).glob("*.txt"):
                return f.read_text(encoding="shift_jis", errors="replace")

    log.error("LZH解凍ツールが見つかりません")
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

def parse_wind_wave(line):
    wind_dir, wind_spd, wave = "", 0.0, 0
    m = re.search(r"風\s+(\S+)\s+([\d.]+)m", line)
    if m:
        wind_dir = m.group(1).strip()
        wind_spd = float(m.group(2))
    m = re.search(r"波\s+([\d.]+)cm", line)
    if m:
        wave = int(float(m.group(1)))
    return wind_dir, wind_spd, wave

def parse_k_file(text, race_date_str):
    lines = text.splitlines()
    races, results, details = [], [], []
    current_venue_code = None
    current_race_no    = None
    wind_dir, wind_spd, wave = "", 0.0, 0
    in_data   = False
    rank_boats = []
    payouts    = {}

    for line in lines:
        m = re.match(r"^(\d{2})KBGN", line)
        if m:
            if current_race_no and rank_boats:
                _save_race(races, results, details, race_date_str, current_venue_code,
                           current_race_no, wind_dir, wind_spd, wave, rank_boats, payouts)
            current_venue_code = m.group(1)
            current_race_no    = None
            rank_boats         = []
            payouts            = {}
            in_data            = False
            continue

        # 払戻金行
        m = re.match(r"\s+(\d+)R\s+\d+-\d+-\d+\s+(\d+)", line)
        if m and current_venue_code and not in_data:
            payouts[int(m.group(1))] = int(m.group(2))
            continue

        # レース番号行
        m = re.match(r"^\s{0,3}(\d+)R\s+\S", line)
        if m and current_venue_code:
            if current_race_no and rank_boats:
                _save_race(races, results, details, race_date_str, current_venue_code,
                           current_race_no, wind_dir, wind_spd, wave, rank_boats, payouts)
            current_race_no = int(m.group(1))
            rank_boats      = []
            in_data         = False
            wind_dir, wind_spd, wave = parse_wind_wave(line)
            continue

        if re.match(r"^-{10,}", line):
            in_data = True
            continue

        if in_data and current_venue_code and current_race_no:
            m = re.match(r"^\s{1,3}(\d{2})\s+(\d)\s+(\d{4})(.*?)(\d+\.\d+)\s+(\d)\s+([-FfLl]?0\.\d+)", line)
            if m:
                finish      = int(m.group(1))
                course      = int(m.group(2))
                racer_no    = int(m.group(3))
                exhibition  = float(m.group(5))
                nyuko       = int(m.group(6))
                st_str      = m.group(7)
                try:
                    if st_str.upper().startswith('F'):
                        st = -float(st_str[1:]) if len(st_str) > 1 else -0.001
                    elif st_str.upper().startswith('L'):
                        st = None
                    else:
                        st = float(st_str)
                except:
                    st = None
                rank_boats.append((finish, course, racer_no, nyuko, st, exhibition))

    if current_race_no and rank_boats:
        _save_race(races, results, details, race_date_str, current_venue_code,
                   current_race_no, wind_dir, wind_spd, wave, rank_boats, payouts)

    return races, results, details

def _save_race(races, results, details, race_date_str, venue_code, race_no,
               wind_dir, wind_spd, wave, rank_boats, payouts):
    venue_id = STADIUM_MAP.get(venue_code)
    if not venue_id:
        return
    date_part = race_date_str.replace("-", "")
    race_id   = int(f"{date_part}{venue_id:02d}{race_no:02d}")

    wind_type = "向かい風" if any(k in wind_dir for k in ["向","北","真北"]) else \
                "追い風"  if any(k in wind_dir for k in ["追","南","真南"]) else "横風"

    races.append({
        "race_id": race_id, "race_date": race_date_str,
        "venue_id": venue_id, "race_no": race_no,
        "grade_code": "", "wind_speed": wind_spd,
        "wave_height": wave, "wind_type": wind_type,
        "in_grade": "", "in_motor_rate": 0.0, "in_is_local": 0,
    })

    sorted_boats = sorted(rank_boats, key=lambda x: x[0])
    rank1 = sorted_boats[0][1] if len(sorted_boats) > 0 else 0
    rank2 = sorted_boats[1][1] if len(sorted_boats) > 1 else 0
    rank3 = sorted_boats[2][1] if len(sorted_boats) > 2 else 0
    pay   = payouts.get(race_no, 0)

    results.append({
        "race_id": race_id, "rank_1st": rank1,
        "rank_2nd": rank2, "rank_3rd": rank3,
        "trifecta_pay": pay, "is_mansen": 1 if pay >= 100000 else 0,
    })

    # result_detail: 選手別着順（全着順）
    # start_detail: 選手別STタイミング
    for finish, course, racer_no, nyuko, st in rank_boats:
        details.append({
            "race_id":  race_id,
            "racer_no": racer_no,
            "course":   nyuko,   # 進入コースを使用
            "finish":   finish,
        })
        if st is not None:
            details.append({
                "type":        "start",
                "race_id":     race_id,
                "racer_no":    racer_no,
                "course":      nyuko,
                "st":          st,
                "exhibition":  exhibition,
            })

def save_to_supabase(pg_conn, races, results, details):
    if not races:
        return 0

    result_details = [d for d in details if "finish" in d]
    start_details  = [d for d in details if d.get("type") == "start"]

    with pg_conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO race (race_id,race_date,venue_id,race_no,grade_code,
                wind_speed,wave_height,wind_type,in_grade,in_motor_rate,in_is_local)
            VALUES %s ON CONFLICT (race_id) DO NOTHING
        """, [(r["race_id"],r["race_date"],r["venue_id"],r["race_no"],r["grade_code"],
               r["wind_speed"],r["wave_height"],r["wind_type"],r["in_grade"],
               r["in_motor_rate"],r["in_is_local"]) for r in races])

        psycopg2.extras.execute_values(cur, """
            INSERT INTO result (race_id,rank_1st,rank_2nd,rank_3rd,trifecta_pay,is_mansen)
            VALUES %s ON CONFLICT DO NOTHING
        """, [(r["race_id"],r["rank_1st"],r["rank_2nd"],r["rank_3rd"],
               r["trifecta_pay"],r["is_mansen"]) for r in results])

        if result_details:
            psycopg2.extras.execute_values(cur, """
                INSERT INTO result_detail (race_id,racer_no,course,finish)
                VALUES %s ON CONFLICT (race_id,racer_no) DO NOTHING
            """, [(d["race_id"],d["racer_no"],d["course"],d["finish"]) for d in result_details])

        if start_details:
            psycopg2.extras.execute_values(cur, """
                INSERT INTO start_detail (race_id,racer_no,course,st_timing,exhibition_time)
                VALUES %s ON CONFLICT (race_id,racer_no) DO NOTHING
            """, [(d["race_id"],d["racer_no"],d["course"],d["st"],d["exhibition"]) for d in start_details])

    pg_conn.commit()
    return len(races)

def process_date(dt, pg_conn):
    race_date_str = dt.strftime("%Y-%m-%d")
    log.info(f"=== {race_date_str} ===")
    data = download_lzh(dt)
    if not data:
        return 0
    text = extract_lzh(data)
    if not text:
        return 0
    races, results, details = parse_k_file(text, race_date_str)
    log.info(f"  パース: {len(races)}レース / {len(details)}選手着順")
    saved = save_to_supabase(pg_conn, races, results, details)
    log.info(f"  保存: {saved}件 ✓")
    return saved

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date",  default="")
    parser.add_argument("--from",  default="", dest="date_from")
    parser.add_argument("--to",    default="", dest="date_to")
    args = parser.parse_args()

    if not SUPABASE_PASS:
        log.error("SUPABASE_PASSを設定してください")
        return

    pg_conn = get_pg_conn()

    if args.date_from and args.date_to:
        dt = datetime.strptime(args.date_from, "%Y%m%d").replace(tzinfo=JST)
        dt_to = datetime.strptime(args.date_to, "%Y%m%d").replace(tzinfo=JST)
        while dt <= dt_to:
            process_date(dt, pg_conn)
            dt += timedelta(days=1)
            time.sleep(1)
    elif args.date:
        dt = datetime.strptime(args.date, "%Y%m%d").replace(tzinfo=JST)
        process_date(dt, pg_conn)
    else:
        process_date(datetime.now(JST), pg_conn)

    pg_conn.close()
    log.info("全完了 ✓")

if __name__ == "__main__":
    main()
