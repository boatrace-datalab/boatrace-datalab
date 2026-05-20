"""
fetch_b_files.py
────────────────
ボートレース公式 www1.mbrace.or.jp から
Bファイル（番組表）を日付・全場分ダウンロードして data/raw/ に保存する。

URL仕様（mbrace）:
  https://www1.mbrace.or.jp/od2/B/YYYYMM/bYYMMDD.lzh
  ※ 開催がない場合は 404 が返る
"""

import argparse
import io
import logging
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ── 定数 ──────────────────────────────────────────────────────────────────────
BASE_URL   = "https://www1.mbrace.or.jp/od2/B/{ym}/b{ymd}.lzh"
USER_AGENT = "Mozilla/5.0 (compatible; BoatraceAnalyzer/1.0)"
JST        = timezone(timedelta(hours=9))
RETRY      = 3
RETRY_WAIT = 5  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ── ユーティリティ ─────────────────────────────────────────────────────────────
def jst_today() -> datetime:
    return datetime.now(JST)


def parse_date(date_str: str) -> datetime:
    if not date_str:
        return jst_today()
    return datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=JST)


def build_url(dt: datetime) -> str:
    ym  = dt.strftime("%Y%m")   # 202505
    ymd = dt.strftime("%y%m%d") # 250520  ← 2桁年
    return BASE_URL.format(ym=ym, ymd=ymd)


# ── ダウンロード ───────────────────────────────────────────────────────────────
def download_lzh(url: str) -> bytes | None:
    """LZHファイルをバイト列で返す。404 は None、それ以外は例外。"""
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(1, RETRY + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 404:
                log.info(f"  404 (開催なし): {url}")
                return None
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            log.warning(f"  試行 {attempt}/{RETRY} 失敗: {e}")
            if attempt < RETRY:
                time.sleep(RETRY_WAIT)
    raise RuntimeError(f"ダウンロード失敗: {url}")


# ── LZH 解凍（lhaz / python-lhafile を使う） ──────────────────────────────────
def extract_lzh(data: bytes, out_dir: Path) -> list[Path]:
    """
    lhafile ライブラリで LZH を解凍。
    ライブラリが無い場合は lhaz コマンドにフォールバック。
    解凍したファイルのパスリストを返す。
    """
    saved_paths: list[Path] = []
    try:
        import lhafile  # type: ignore
        lhf = lhafile.LhaFile(io.BytesIO(data))
        for name in lhf.namelist():
            content = lhf.read(name)
            dest = out_dir / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            saved_paths.append(dest)
            log.info(f"  解凍: {dest} ({len(content):,} bytes)")
    except ImportError:
        # lhafile が無ければ tmp に保存して lhaz で解凍
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile(suffix=".lzh", delete=False) as f:
            f.write(data)
            tmp_path = Path(f.name)
        result = subprocess.run(
            ["lhaz", "x", str(tmp_path), str(out_dir)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"lhaz 解凍失敗:\n{result.stderr}")
        tmp_path.unlink()
        saved_paths = list(out_dir.glob("*"))
    return saved_paths


# ── メイン ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Bファイル取得")
    parser.add_argument("--date",    default="",          help="対象日 YYYYMMDD（省略=当日）")
    parser.add_argument("--out-dir", default="data/raw",  help="保存先ディレクトリ")
    args = parser.parse_args()

    target_dt = parse_date(args.date)
    out_dir   = Path(args.out_dir) / target_dt.strftime("%Y%m%d")
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"対象日: {target_dt.strftime('%Y-%m-%d')}  保存先: {out_dir}")

    url = build_url(target_dt)
    log.info(f"ダウンロード: {url}")

    raw = download_lzh(url)
    if raw is None:
        log.warning("この日の番組表ファイルは存在しません。")
        return

    # LZH をそのまま保存（バックアップ）
    lzh_path = out_dir / f"b{target_dt.strftime('%y%m%d')}.lzh"
    lzh_path.write_bytes(raw)
    log.info(f"LZH 保存: {lzh_path} ({len(raw):,} bytes)")

    # 解凍
    extracted = extract_lzh(raw, out_dir)
    log.info(f"解凍ファイル数: {len(extracted)}")
    log.info("Bファイル取得完了 ✓")


if __name__ == "__main__":
    main()
