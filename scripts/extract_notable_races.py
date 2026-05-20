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

NOTABLE_CONDITIONS = {"final_race_no": 12, "noted_racers": [], "noted_stadiums": []}

ZEN2HAN = str.maketrans("１２３４５６７８９０", "1234567890")
RACE_RE = re.compile("[\u3000\\s]*([１-９０\\d]+)Ｒ")
STADIUM_RE = re.compile(r"^(\d{2})BBGN")
SEP_RE = re.compile(r"^-{10,}")
BOAT_RE = re.compile(r"^([1-6])\s+(\d{4})(\S+)")

def parse_b_file(path):
    text = path.read_text(encoding="shift_jis", errors="replace")
    races = []
    current_stadium = None
    current_race_no = None
    current_boats = []
    in_data = False

    for line in text.splitlines():
        m = STADIUM_RE.match(line)
        if m:
            current_stadium = m.group(1)
            continue

        m = RACE_RE.search(line)
        if m and current_stadium:
            if current_race_no and current_boats:
                races.append({"stadium_code": current_stadium,
                    "stadium_name": STADIUM_MAP.get(current_stadium, current_stadium),
                    "race_no": current_race_no, "boats": current_boats})
            current_race_no = int(m.group(1).translate(ZEN2HAN))
            current_boats = []
            in_data = False
            continue

        if SEP_RE.match(line):
            in_data = True
            continue

        if in_data and current_stadium:
            m = BOAT_RE.match(line)
            if m:
                current_boats.append({"boat_no": int(m.group(1)),
                    "racer_id": m.group(2), "racer_name": m.group(3), "grade": ""})

    if current_race_no and current_boats:
        races.append({"stadium_code": current_stadium,
            "stadium_name": STADIUM_MAP.get(current_stadium, current_stadium),
            "race_no": current_race_no, "boats": current_boats})
    return races

def is_notable(race):
    reasons = []
    if race["race_no"] == NOTABLE_CONDITIONS["final_race_no"]:
        reasons.append("最終レース（優勝戦）")
    for boat in race["boats"]:
        if boat["racer_id"] in [str(r) for r in NOTABLE_CONDITIONS["noted_racers"]]:
            reasons.append("注目選手: {}({})".format(boat["racer_name"], boat["racer_id"]))
    if race["stadium_code"] in NOTABLE_CONDITIONS["noted_stadiums"]:
        reasons.append("注目場: {}".format(race["stadium_name"]))
    return (len(reasons) > 0), reasons

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--out-dir", default="data/processed")
    args = parser.parse_args()
    raw_root = Path(args.raw_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    b_files = list(raw_root.rglob("*.TXT")) + list(raw_root.rglob("*.txt"))
    log.info("Bファイル候補: {} 個".format(len(b_files)))
    all_races = []
    for f in sorted(b_files):
        races = parse_b_file(f)
        log.info("  解析: {}  レース数: {}".format(f.name, len(races)))
        all_races.extend(races)
    notable = []
    for r in all_races:
        ok, reasons = is_notable(r)
        if ok:
            r["reasons"] = ", ".join(reasons)
            notable.append(r)
    log.info("注目レース: {} 件".format(len(notable)))
    json_path = out_dir / "notable_races.json"
    json_path.write_text(json.dumps(notable, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = out_dir / "notable_races.csv"
    flat = [{"場コード": r["stadium_code"], "場名": r["stadium_name"],
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
