import argparse, csv, json, logging, re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

STADIUM_MAP = {
    "01":"桐生","02":"戸田","03":"江戸川","04":"平和島",
    "05":"多摩川","06":"浜名湖","07":"蒲郡","08":"常滑",
    "09":"津","10":"三国","11":"びわこ","12":"住之江",
    "13":"尼崎","14":"鳴門","15":"丸亀","16":"児島",
    "17":"宮島","18":"徳山","19":"下関","20":"若松",
    "21":"芦屋","22":"福岡","23":"唐津","24":"大村",
}

SG_KEYWORDS = ["ＳＧ","グランプリ","グランドチャンピオン","チャレンジカップ","オールスター","総理大臣杯","笹川賞","全日本選手権","メモリアル","クラシック","ダービー","王座決定戦"]
G1_KEYWORDS = ["周年記念","選手権","レディース","ヴィーナス","オールレディース"]

NOTED_RACERS = ["4320"]  # 峰竜太

ZEN2HAN = str.maketrans("１２３４５６７８９０", "1234567890")
RACE_RE    = re.compile("[\u3000\\s]*([１-９０\\d]+)Ｒ")
STADIUM_RE = re.compile(r"^(\d{2})BBGN")
SEP_RE     = re.compile(r"^-{10,}")
DAY_RE     = re.compile("第[\u3000\\s]*([１-９０\\d]+)日")

def detect_grade(title):
    for kw in SG_KEYWORDS:
        if kw in title:
            return "SG"
    for kw in G1_KEYWORDS:
        if kw in title:
            return "G1"
    return ""

def parse_racer_id(line):
    m = re.match(r"^([1-6])\s+(\d{4})", line)
    if not m:
        return None
    boat_no  = int(m.group(1))
    racer_id = m.group(2)
    rest     = line[m.end():]
    m2 = re.search(r"(\d{2})\S{2}\d{2}", rest)
    if m2:
        racer_name = rest[:m2.start()].strip()
    else:
        racer_name = rest[:6].strip()
    return {"boat_no": boat_no, "racer_id": racer_id, "racer_name": racer_name}

def parse_b_file(path):
    text = path.read_text(encoding="shift_jis", errors="replace")
    races = []
    current_stadium  = None
    current_grade    = ""
    current_day      = 0
    current_race_no  = None
    current_boats    = []
    in_data          = False
    title_parsed     = False

    for line in text.splitlines():
        m = STADIUM_RE.match(line)
        if m:
            if current_race_no and current_boats:
                races.append({"stadium_code": current_stadium,
                    "stadium_name": STADIUM_MAP.get(current_stadium, current_stadium),
                    "grade": current_grade, "day": current_day,
                    "race_no": current_race_no, "boats": current_boats})
            current_stadium = m.group(1)
            current_grade   = ""
            current_day     = 0
            current_race_no = None
            current_boats   = []
            in_data         = False
            title_parsed    = False
            continue

        # タイトル行（場コード後〜最初のレース番号前）でグレードと開催日を取得
        if current_stadium and not title_parsed:
            detected = detect_grade(line)
            if detected:
                current_grade = detected
            m2 = DAY_RE.search(line)
            if m2:
                current_day = int(m2.group(1).translate(ZEN2HAN))
            # gradeとdayの両方が揃ったらtitle_parsedをTrue
            # ただし10行以上経過したら強制的にTrue
            if current_day > 0 and current_grade:
                title_parsed = True
            continue

        m = RACE_RE.search(line)
        if m and current_stadium:
            if current_race_no and current_boats:
                races.append({"stadium_code": current_stadium,
                    "stadium_name": STADIUM_MAP.get(current_stadium, current_stadium),
                    "grade": current_grade, "day": current_day,
                    "race_no": current_race_no, "boats": current_boats})
            current_race_no = int(m.group(1).translate(ZEN2HAN))
            current_boats   = []
            in_data         = False
            continue

        if SEP_RE.match(line):
            in_data = True
            continue

        if in_data and current_stadium:
            boat = parse_racer_id(line)
            if boat:
                current_boats.append(boat)

    if current_race_no and current_boats:
        races.append({"stadium_code": current_stadium,
            "stadium_name": STADIUM_MAP.get(current_stadium, current_stadium),
            "grade": current_grade, "day": current_day,
            "race_no": current_race_no, "boats": current_boats})
    return races

def is_notable(race):
    reasons = []
    grade   = race["grade"]
    day     = race["day"]
    race_no = race["race_no"]

    if grade in ("SG", "G1") and day == 1 and race_no == 12:
        reasons.append("{} 初日12R ドリーム戦".format(grade))
    if grade in ("SG", "G1") and day == 5 and race_no in (10, 11, 12):
        reasons.append("{} 5日目{}R 準優勝戦".format(grade, race_no))
    if grade in ("SG", "G1") and day == 6 and race_no == 12:
        reasons.append("{} 6日目12R 優勝戦".format(grade))

    for boat in race["boats"]:
        if boat["racer_id"] in NOTED_RACERS:
            reasons.append("注目選手: {}({})".format(boat["racer_name"], boat["racer_id"]))

    return (len(reasons) > 0), reasons

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--out-dir", default="data/processed")
    args = parser.parse_args()
    raw_root = Path(args.raw_dir)
    out_dir  = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    b_files = sorted(set(raw_root.rglob("*.TXT")) | set(raw_root.rglob("*.txt")))
    log.info("Bファイル候補: {} 個".format(len(b_files)))

    all_races = []
    for f in b_files:
        races = parse_b_file(f)
        log.info("  解析: {}  レース数: {}".format(f.name, len(races)))
        all_races.extend(races)

    notable = []
    seen = set()
    for r in all_races:
        key = (r["stadium_code"], r["race_no"], r["day"])
        if key in seen:
            continue
        seen.add(key)
        ok, reasons = is_notable(r)
        if ok:
            r["reasons"] = ", ".join(reasons)
            notable.append(r)

    log.info("注目レース: {} 件".format(len(notable)))

    json_path = out_dir / "notable_races.json"
    json_path.write_text(json.dumps(notable, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = out_dir / "notable_races.csv"
    flat = [{"場コード": r["stadium_code"], "場名": r["stadium_name"],
             "グレード": r["grade"], "開催日": r["day"],
             "レース番号": r["race_no"], "注目理由": r["reasons"],
             "出場艇数": len(r["boats"])} for r in notable]
    if flat:
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=flat[0].keys())
            w.writeheader()
            w.writerows(flat)

    log.info("抽出完了 ✓")

if __name__ == "__main__":
    main()
