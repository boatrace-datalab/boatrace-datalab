"""
ボートレース レース判定ツール
Streamlit版 v1.0
"""

import streamlit as st
import sqlite3
import pandas as pd
import os

# ===== 設定 =====
# DBのパスは環境に合わせて変更してください
DB_PATH = "boatrace_light3.db"
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS judgment_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT,
            venue_name TEXT,
            race_no INTEGER,
            wind_direction TEXT,
            wind_speed REAL,
            wave_height INTEGER,
            wind_type TEXT,
            in_grade TEXT,
            motor_rate REAL,
            is_local INTEGER,
            grade_code TEXT,
            st_timing REAL,
            st_rank INTEGER,
            mode TEXT,
            judgment TEXT,
            score INTEGER,
            pred_mansen REAL,
            in_win_rate REAL,
            adjusted_in REAL,
            actual_rank1st INTEGER,
            actual_mansen INTEGER,
            actual_payout INTEGER,
            is_correct INTEGER,
            memo TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ===== 定数 =====
VENUE_LIST = [
    (1,'桐生'), (2,'戸田'), (3,'江戸川'), (4,'平和島'), (5,'多摩川'),
    (6,'浜名湖'), (7,'蒲郡'), (8,'常滑'), (9,'津'), (10,'三国'),
    (11,'びわこ'), (12,'住之江'), (13,'尼崎'), (14,'鳴門'), (15,'丸亀'),
    (16,'児島'), (17,'宮島'), (18,'徳山'), (19,'下関'), (20,'若松'),
    (21,'芦屋'), (22,'福岡'), (23,'唐津'), (24,'大村'),
]

WIND_DIRECTION_MASTER = {
    1:  {'tail': ['南東'], 'head': ['北西']},
    2:  {'tail': ['北'],   'head': ['南']},
    3:  {'tail': ['南西'], 'head': ['北東']},
    4:  {'tail': ['南','南西'], 'head': ['北','北東']},
    5:  {'tail': ['北'],   'head': ['南']},
    6:  {'tail': ['東','南東'], 'head': ['西','北西']},
    7:  {'tail': ['南東'], 'head': ['北西']},
    8:  {'tail': ['南'],   'head': ['北']},
    9:  {'tail': ['南東'], 'head': ['北西']},
    10: {'tail': ['南東'], 'head': ['北西']},
    11: {'tail': ['北'],   'head': ['南']},
    12: {'tail': ['北'],   'head': ['南']},
    13: {'tail': ['西'],   'head': ['東']},
    14: {'tail': ['南東'], 'head': ['北西']},
    15: {'tail': ['南東'], 'head': ['北西']},
    16: {'tail': ['南東'], 'head': ['北西']},
    17: {'tail': ['南'],   'head': ['北']},
    18: {'tail': ['南東'], 'head': ['北西']},
    19: {'tail': ['南西'], 'head': ['北東']},
    20: {'tail': ['南東'], 'head': ['北西']},
    21: {'tail': ['南東'], 'head': ['北西']},
    22: {'tail': ['北'],   'head': ['南']},
    23: {'tail': ['南西'], 'head': ['北東']},
    24: {'tail': ['南'],   'head': ['北']},
}

ROUGH_VENUES = [2, 3, 4]  # 戸田・江戸川・平和島（3段階判定）

# ===== ヘルパー関数 =====
def get_wind_type(venue_id, wind_direction):
    if wind_direction == '無風':
        return '無風'
    master = WIND_DIRECTION_MASTER.get(venue_id, {})
    if wind_direction in master.get('tail', []):
        return '追い風'
    elif wind_direction in master.get('head', []):
        return '向かい風'
    return '横風'

def get_wave_cat(wave_height):
    if wave_height <= 3:   return '微波'
    elif wave_height <= 6: return '中波'
    return '高波'

def get_judgment(in_win_rate, score, venue_id):
    adjusted = in_win_rate + (score * -1.5)
    if venue_id in ROUGH_VENUES:
        if adjusted >= 50:   return "🟡 普通（様子見）", adjusted
        elif adjusted >= 38: return "🟠 荒れ気味（万舟候補）", adjusted
        else:                return "🔴 万舟狙い（荒れる）", adjusted
    else:
        if adjusted >= 65:   return "🔵 鉄板（イン本命）", adjusted
        elif adjusted >= 55: return "🟢 堅め（イン有利）", adjusted
        elif adjusted >= 45: return "🟡 普通（様子見）", adjusted
        elif adjusted >= 35: return "🟠 荒れ気味（万舟候補）", adjusted
        else:                return "🔴 万舟狙い（荒れる）", adjusted

def judge_race(venue_id, wind_direction, wind_speed, wave_height,
               in_grade, motor_rate, is_local, grade_code,
               in_st_timing=None, in_st_rank=None):

    conn = sqlite3.connect(DB_PATH)
    score = 0
    details = []

    wind_type = get_wind_type(venue_id, wind_direction)
    wave_cat  = get_wave_cat(wave_height)

    try:
        venue_info = pd.read_sql(f"""
            SELECT v.course_width_category, v.rough_tendency, v.score_correction,
                   COALESCE(vic.in_rate_adjust, 0) as in_rate_adjust
            FROM venue v
            LEFT JOIN venue_in_correction vic ON v.venue_id = vic.venue_id
            WHERE v.venue_id = {venue_id}
        """, conn).iloc[0]
        course_width     = venue_info['course_width_category']
        rough_tendency   = venue_info['rough_tendency']
        score_correction = int(venue_info['score_correction'])
        in_rate_adjust   = float(venue_info['in_rate_adjust'])
    except:
        course_width     = '中'
        rough_tendency   = '中'
        score_correction = 0
        in_rate_adjust   = 0.0

    try:
        combo = pd.read_sql(f"""
            SELECT mansen_rate, in_win_rate, avg_payout
            FROM combo_stats
            WHERE course_width = '{course_width}'
            AND wind_type = '{wind_type}'
            AND in_grade = '{in_grade}'
            AND wave_category = '{wave_cat}'
        """, conn)
        if not combo.empty:
            mansen_rate = combo.iloc[0]['mansen_rate']
            in_win_rate = combo.iloc[0]['in_win_rate'] + in_rate_adjust
            avg_payout  = combo.iloc[0]['avg_payout']
        else:
            mansen_rate = 17.0
            in_win_rate = 50.0 + in_rate_adjust
            avg_payout  = 7000.0
    except:
        mansen_rate = 17.0
        in_win_rate = 50.0
        avg_payout  = 7000.0

    conn.close()

    if in_rate_adjust != 0:
        details.append(f"場別イン着率補正：{in_rate_adjust:+.1f}%")

    details.append(f"複合条件：万舟率{mansen_rate}%・イン着率{in_win_rate:.1f}%・平均配当{avg_payout:.0f}円")

    if mansen_rate >= 22:
        score += 4; details.append("→ 複合条件：万舟高（+4）")
    elif mansen_rate >= 19:
        score += 2; details.append("→ 複合条件：万舟やや高（+2）")
    elif mansen_rate >= 17:
        score += 0; details.append("→ 複合条件：普通（±0）")
    elif mansen_rate >= 15:
        score -= 2; details.append("→ 複合条件：やや堅い（-2）")
    else:
        score -= 4; details.append("→ 複合条件：堅い（-4）")

    if motor_rate >= 40:
        score -= 2; details.append(f"→ モーター強({motor_rate:.1f}%、-2）")
    elif motor_rate >= 35:
        score -= 1; details.append(f"→ モーター普通({motor_rate:.1f}%、-1）")
    else:
        score += 1; details.append(f"→ モーター弱({motor_rate:.1f}%、+1）")

    if is_local:
        score -= 1; details.append("→ 地元選手（-1）")

    if grade_code in ['SG', 'G1', 'G2']:
        score += 1; details.append(f"→ グレード{grade_code}（+1）")

    if rough_tendency == '高':
        score += 1; details.append("→ 荒れやすい場（+1）")
    elif rough_tendency == '低':
        score -= 1; details.append("→ 荒れにくい場（-1）")

    if wind_speed >= 7:
        score += 2; details.append(f"→ 強風{wind_speed:.0f}m（+2）")
    elif wind_speed >= 4:
        score += 1; details.append(f"→ 中風{wind_speed:.0f}m（+1）")

    if score_correction != 0:
        score += score_correction
        direction = "堅め補正" if score_correction < 0 else "荒れ補正"
        details.append(f"→ 場別{direction}（{score_correction:+d}）")

    # ST（直前モードのみ）
    if in_st_timing is not None:
        if in_st_timing <= 0.10:
            score -= 3; details.append("→ ST超速（-3）")
        elif in_st_timing <= 0.15:
            score -= 2; details.append("→ ST速（-2）")
        elif in_st_timing <= 0.20:
            details.append("→ ST普通（±0）")
        elif in_st_timing <= 0.30:
            score += 2; details.append("→ ST遅（+2）")
        else:
            score += 3; details.append("→ ST超遅（+3）")

    if in_st_rank is not None:
        if in_st_rank == 1:
            score -= 2; details.append("→ ST相対1位（-2）")
        elif in_st_rank == 2:
            score -= 1; details.append("→ ST相対2位（-1）")
        elif in_st_rank <= 4:
            score += 1; details.append("→ ST相対3-4位（+1）")
        else:
            score += 2; details.append("→ ST相対5-6位（+2）")

    judgment, adjusted = get_judgment(in_win_rate, score, venue_id)

    return {
        'judgment':    judgment,
        'adjusted':    adjusted,
        'score':       score,
        'mansen_rate': mansen_rate,
        'in_win_rate': in_win_rate,
        'avg_payout':  avg_payout,
        'wind_type':   wind_type,
        'details':     details,
    }

# ===== Streamlit UI =====
st.set_page_config(
    page_title="ボートレース判定ツール",
    page_icon="🚤",
    layout="wide"
)

st.title("🚤 ボートレース レース判定ツール")
st.caption("30万件のデータに基づくレース判定ツール")

# タブ
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📋 レース前判定",
    "⚡ レース直前判定",
    "📊 成績ダッシュボード",
    "🔍 出走メンバー診断",
    "🔎 レース条件検索"
])
# ===== タブ1：レース前判定 =====
with tab1:
    st.subheader("📋 レース前判定")
    st.caption("出走表が出た時点で使える判定モード")

    col1, col2 = st.columns(2)

    with col1:
        venue_name_pre = st.selectbox(
            "場名", [v[1] for v in VENUE_LIST], key='venue_pre'
        )
        venue_id_pre = next(v[0] for v in VENUE_LIST if v[1] == venue_name_pre)

        wind_dir_pre = st.selectbox(
            "風向き",
            ['無風','北','北東','東','南東','南','南西','西','北西'],
            key='wind_dir_pre'
        )
        wind_speed_pre = st.slider("風速（m）", 0, 20, 3, key='wind_speed_pre')
        wave_pre = st.slider("波高（cm）", 0, 40, 3, key='wave_pre')

    with col2:
        in_grade_pre = st.selectbox(
            "1コース等級", ['A1','A2','B1','B2'], key='in_grade_pre'
        )
        motor_pre = st.slider(
            "モーター2連率（%）", 0.0, 80.0, 35.0, 0.5, key='motor_pre'
        )
        is_local_pre = st.checkbox("地元選手", key='is_local_pre')
        grade_pre = st.selectbox(
            "レースグレード", ['IC','G3','G2','G1','SG'], key='grade_pre'
        )

    if st.button("判定する", type="primary", key='btn_pre'):
        result = judge_race(
            venue_id      = venue_id_pre,
            wind_direction= wind_dir_pre,
            wind_speed    = wind_speed_pre,
            wave_height   = wave_pre,
            in_grade      = in_grade_pre,
            motor_rate    = motor_pre,
            is_local      = 1 if is_local_pre else 0,
            grade_code    = grade_pre,
        )

        st.divider()
        judgment = result['judgment']

        # 判定結果の色分け
        if '鉄板' in judgment:
            st.success(f"## {judgment}")
        elif '堅め' in judgment:
            st.success(f"## {judgment}")
        elif '普通' in judgment:
            st.info(f"## {judgment}")
        elif '荒れ気味' in judgment:
            st.warning(f"## {judgment}")
        else:
            st.error(f"## {judgment}")

        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("調整イン着率", f"{result['adjusted']:.1f}%")
        col_b.metric("予測万舟率", f"{result['mansen_rate']}%")
        col_c.metric("予測イン着率", f"{result['in_win_rate']:.1f}%")
        col_d.metric("予測平均配当", f"{result['avg_payout']:,.0f}円")

        st.caption(f"風タイプ：{result['wind_type']} / スコア：{result['score']}")

        with st.expander("判定根拠を見る"):
            for d in result['details']:
                st.text(d)

        # 結果記録
        st.divider()
        st.subheader("📝 結果を記録する")
        col_r1, col_r2, col_r3 = st.columns(3)
        with col_r1:
            actual_rank_options = {'未記録': -1, '1コース': 1, '2コース': 2, '3コース': 3, '4コース': 4, '5コース': 5, '6コース': 6}
            actual_rank_label = st.selectbox(
                "実際の1着コース",
                list(actual_rank_options.keys()),
                key='actual_rank_pre'
            )
            actual_rank = (actual_rank_label, actual_rank_options[actual_rank_label])

        with col_r2:
            actual_payout = st.number_input(
                "実際の配当（円）", min_value=0, value=0, key='actual_payout_pre'
            )
        with col_r3:
            memo = st.text_input("メモ", key='memo_pre')

        if st.button("記録する", key='save_pre'):
            if actual_rank[1] == -1:
                st.warning("1着コースを選択してください")
            else:
                actual_mansen = 1 if actual_payout >= 10000 else 0
                if '鉄板' in judgment:
                    is_correct = 1 if actual_rank[1] == 1 and actual_mansen == 0 else 0
                elif '堅め' in judgment:
                    is_correct = 1 if actual_rank[1] in [1,2] and actual_mansen == 0 else 0
                elif '万舟狙い' in judgment or '荒れ気味' in judgment:
                    is_correct = 1 if actual_mansen == 1 else 0
                else:
                    is_correct = -1

                conn = sqlite3.connect(DB_PATH)
                wind_type = get_wind_type(venue_id_pre, wind_dir_pre)
                adjusted  = result['adjusted']
                conn.execute("""
                    INSERT INTO judgment_log (
                        log_date, venue_name, race_no,
                        wind_direction, wind_speed, wave_height, wind_type,
                        in_grade, motor_rate, is_local, grade_code,
                        st_timing, st_rank, mode, judgment, score,
                        pred_mansen, in_win_rate, adjusted_in,
                        actual_rank1st, actual_mansen, actual_payout,
                        is_correct, memo, created_at
                    ) VALUES (date('now'), ?, 0, ?, ?, ?, ?, ?, ?, ?, ?,
                              NULL, NULL, '📋 レース前判定', ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, datetime('now'))
                """, (
                    venue_name_pre, wind_dir_pre, wind_speed_pre,
                    wave_pre, wind_type, in_grade_pre, motor_pre,
                    1 if is_local_pre else 0, grade_pre,
                    judgment, result['score'], result['mansen_rate'],
                    result['in_win_rate'], adjusted,
                    actual_rank[1], actual_mansen, actual_payout,
                    is_correct, memo
                ))
                conn.commit()
                conn.close()

                if is_correct == 1:
                    st.success("✅ 記録しました！的中！")
                elif is_correct == 0:
                    st.error("❌ 記録しました。外れ。")
                else:
                    st.info("－ 記録しました（普通判定は対象外）")

# ===== タブ2：レース直前判定 =====
with tab2:
    st.subheader("⚡ レース直前判定")
    st.caption("展示後のSTタイミングが出てから使う高精度モード")

    col1, col2 = st.columns(2)

    with col1:
        venue_name_live = st.selectbox(
            "場名", [v[1] for v in VENUE_LIST], key='venue_live'
        )
        venue_id_live = next(v[0] for v in VENUE_LIST if v[1] == venue_name_live)

        wind_dir_live   = st.selectbox("風向き", ['無風','北','北東','東','南東','南','南西','西','北西'], key='wind_dir_live')
        wind_speed_live = st.slider("風速（m）", 0, 20, 3, key='wind_speed_live')
        wave_live       = st.slider("波高（cm）", 0, 40, 3, key='wave_live')

    with col2:
        in_grade_live = st.selectbox("1コース等級", ['A1','A2','B1','B2'], key='in_grade_live')
        motor_live    = st.slider("モーター2連率（%）", 0.0, 80.0, 35.0, 0.5, key='motor_live')
        is_local_live = st.checkbox("地元選手", key='is_local_live')
        grade_live    = st.selectbox("レースグレード", ['IC','G3','G2','G1','SG'], key='grade_live')
        st_timing     = st.slider("STタイミング", 0.01, 0.50, 0.15, 0.01, key='st_timing')
        st_rank       = st.slider("ST相対順位", 1, 6, 1, key='st_rank')

    if st.button("判定する", type="primary", key='btn_live'):
        result = judge_race(
            venue_id      = venue_id_live,
            wind_direction= wind_dir_live,
            wind_speed    = wind_speed_live,
            wave_height   = wave_live,
            in_grade      = in_grade_live,
            motor_rate    = motor_live,
            is_local      = 1 if is_local_live else 0,
            grade_code    = grade_live,
            in_st_timing  = st_timing,
            in_st_rank    = st_rank,
        )

        st.divider()
        judgment = result['judgment']

        if '鉄板' in judgment:
            st.success(f"## {judgment}")
        elif '堅め' in judgment:
            st.success(f"## {judgment}")
        elif '普通' in judgment:
            st.info(f"## {judgment}")
        elif '荒れ気味' in judgment:
            st.warning(f"## {judgment}")
        else:
            st.error(f"## {judgment}")

        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("調整イン着率", f"{result['adjusted']:.1f}%")
        col_b.metric("予測万舟率", f"{result['mansen_rate']}%")
        col_c.metric("予測イン着率", f"{result['in_win_rate']:.1f}%")
        col_d.metric("予測平均配当", f"{result['avg_payout']:,.0f}円")

        st.caption(f"風タイプ：{result['wind_type']} / スコア：{result['score']}")

        with st.expander("判定根拠を見る"):
            for d in result['details']:
                st.text(d)

# ===== タブ3：成績ダッシュボード =====
with tab3:
    st.subheader("📊 累計成績ダッシュボード")

    if st.button("成績を更新", key='refresh'):
        st.rerun()

    try:
        conn = sqlite3.connect(DB_PATH)

        total = pd.read_sql("SELECT COUNT(*) as cnt FROM judgment_log WHERE memo != '自動取り込み'", conn).iloc[0]['cnt']

        if total == 0:
            st.info("まだ記録がありません。判定結果を記録してください。")
        else:
            # 全体成績
            df_total = pd.read_sql("""
                SELECT 
                    COUNT(*) as 総判定数,
                    SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) as 的中数,
                    ROUND(SUM(CASE WHEN is_correct=1 THEN 1.0 ELSE 0 END)/
                          NULLIF(SUM(CASE WHEN is_correct>=0 THEN 1 ELSE 0 END),0)*100,1) as 的中率
                FROM judgment_log
                WHERE memo != '自動取り込み'
            """, conn)

            col1, col2, col3 = st.columns(3)
            col1.metric("総判定数", f"{int(df_total.iloc[0]['総判定数'])}件")
            col2.metric("的中数", f"{int(df_total.iloc[0]['的中数'])}件")
            col3.metric("的中率", f"{df_total.iloc[0]['的中率']}%")

            st.divider()

            # 判定別成績
            st.subheader("判定別成績")
            df_j = pd.read_sql("""
                SELECT 
                    judgment as 判定,
                    COUNT(*) as 件数,
                    SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) as 的中,
                    ROUND(SUM(CASE WHEN is_correct=1 THEN 1.0 ELSE 0 END)/
                          NULLIF(SUM(CASE WHEN is_correct>=0 THEN 1 ELSE 0 END),0)*100,1) as 的中率,
                    ROUND(AVG(actual_payout),0) as 平均配当
                FROM judgment_log
                WHERE memo != '自動取り込み'
                GROUP BY judgment
                ORDER BY judgment
            """, conn)
            st.dataframe(df_j, use_container_width=True)

            st.divider()

            # 直近10件
            st.subheader("直近10件の記録")
            df_recent = pd.read_sql("""
                SELECT 
                    log_date as 日付,
                    venue_name as 場名,
                    judgment as 判定,
                    actual_rank1st as 1着,
                    actual_payout as 配当,
                    CASE is_correct
                        WHEN 1 THEN '✅的中'
                        WHEN 0 THEN '❌外れ'
                        ELSE '－'
                    END as 結果,
                    memo as メモ
                FROM judgment_log
                WHERE memo != '自動取り込み'
                ORDER BY created_at DESC
                LIMIT 10
            """, conn)
            st.dataframe(df_recent, use_container_width=True)

        conn.close()

    except Exception as e:
        st.error(f"DBに接続できません。boatrace.dbのパスを確認してください。\n{e}")

# ===== タブ4：選手出目検索 =====
with tab4:
    st.subheader("🔍 出走メンバー買い目診断")
    st.caption("各コースの登録番号を入力すると、注目コースが1着の時の推奨買い目を表示します")

    st.write("**出走選手を入力（登録番号・不明は0のまま）**")
    cols = st.columns(6)
    racer_inputs = {}
    for i, col in enumerate(cols, 1):
        with col:
            val = col.number_input(
                f"{i}コース",
                min_value=0, max_value=9999,
                value=0, step=1,
                key=f"racer_{i}"
            )
            racer_inputs[i] = int(val)

    in_course = st.selectbox(
        "注目コース（何コースが1着になった時の買い目を見る？）",
        [1, 2, 3, 4, 5, 6],
        format_func=lambda x: f"{x}コース"
    )

    if st.button("買い目を診断する", type="primary", key="btn_racer"):
        in_racer = racer_inputs.get(in_course, 0)
        if in_racer == 0:
            st.warning(f"{in_course}コースの登録番号を入力してください")
        else:
            conn = sqlite3.connect(DB_PATH)
            try:
                # 注目コースの選手名取得
                name_df = pd.read_sql(f"""
                    SELECT racer_name FROM racer_place_stats
                    WHERE racer_no = {in_racer} AND course = {in_course}
                    LIMIT 1
                """, conn)
                in_name = name_df.iloc[0]['racer_name'] if not name_df.empty else f"登録{in_racer}"

                st.success(f"### {in_name}（{in_racer}）が{in_course}コース1着の時")

                # 各コースの選手の2着・3着率を取得
                other_courses = [c for c in range(1, 7) if c != in_course and racer_inputs.get(c, 0) > 0]

                if len(other_courses) < 2:
                    df_solo = pd.read_sql(f"""
                        SELECT 
                            rank_2nd as '2着コース',
                            rank_3rd as '3着コース',
                            cnt as '件数',
                            pct as '出現率(%)',
                            avg_pay as '平均配当(円)'
                        FROM racer_course_stats
                        WHERE racer_no = {in_racer}
                        AND course = {in_course}
                        ORDER BY cnt DESC
                        LIMIT 15
                    """, conn)

                    if df_solo.empty:
                        st.warning("データが見つかりませんでした。")
                    else:
                        total = int(df_solo['件数'].sum())
                        st.caption(f"※他コースの登録番号が未入力のため、過去の全出目データを表示しています")
                        st.caption(f"過去1着回数：{total:,}回")
                        st.dataframe(df_solo, use_container_width=True, hide_index=True)
                        st.write("**🎯 推奨買い目TOP3**")
                        for i, row in enumerate(df_solo.head(3).itertuples(), 1):
                            st.info(f"{i}位：{in_course}-{int(row._1)}-{int(row._2)}　出現率{row._5}%・平均配当{int(row._6):,}円")
                else:
                    # 各コースの選手データ取得
                    course_data = {}
                    for c in other_courses:
                        racer_no = racer_inputs[c]
                        df_p = pd.read_sql(f"""
                            SELECT racer_name, place2_rate, place3_rate, total_cnt
                            FROM racer_place_stats
                            WHERE racer_no = {racer_no} AND course = {c}
                            LIMIT 1
                        """, conn)
                        if not df_p.empty:
                            course_data[c] = {
                                'racer_no': racer_no,
                                'name': df_p.iloc[0]['racer_name'],
                                'place2_rate': df_p.iloc[0]['place2_rate'],
                                'place3_rate': df_p.iloc[0]['place3_rate'],
                                'total_cnt': int(df_p.iloc[0]['total_cnt'])
                            }
                        else:
                            course_data[c] = {
                                'racer_no': racer_no,
                                'name': f"登録{racer_no}",
                                'place2_rate': 0,
                                'place3_rate': 0,
                                'total_cnt': 0
                            }
                    # 選手別2着・3着率を表示
                    st.write("**各コースの選手成績**")
                    member_rows = []
                    for c, d in course_data.items():
                        member_rows.append({
                            'コース': f"{c}コース",
                            '選手名': d['name'],
                            '登録番号': d['racer_no'],
                            '2着率': f"{d['place2_rate']}%",
                            '3着率': f"{d['place3_rate']}%",
                        })
                    member_df = pd.DataFrame(member_rows)
                    st.dataframe(member_df, use_container_width=True, hide_index=True)

                    # 2着×3着の組み合わせスコアを計算
                    st.write("**🎯 推奨買い目（2着×3着の出現確率順）**")
                    combos = []
                    for c2 in other_courses:
                        for c3 in other_courses:
                            if c2 == c3:
                                continue
                            d2 = course_data[c2]
                            d3 = course_data[c3]
                            score = d2['place2_rate'] * d3['place3_rate']
                            combos.append({
                                '出目': f"{in_course}-{c2}-{c3}",
                                '2着': f"{c2}({d2['name']})",
                                '3着': f"{c3}({d3['name']})",
                                '2着率': f"{d2['place2_rate']}%",
                                '3着率': f"{d3['place3_rate']}%",
                                'スコア': round(score, 1)
                            })

                    combos = sorted(combos, key=lambda x: x['スコア'], reverse=True)
                    combo_df = pd.DataFrame(combos[:10])
                    st.dataframe(combo_df, use_container_width=True, hide_index=True)

                    # TOP3をハイライト
                    st.write("**🏆 特に注目の買い目**")
                    for i, c in enumerate(combos[:3], 1):
                        st.info(f"{i}位：{c['出目']}　2着率{c['2着率']} × 3着率{c['3着率']}")

            except Exception as e:
                st.error(f"エラー：{e}")
            finally:
                conn.close()
# ===== タブ5：レース条件検索（有料） =====
with tab5:
    st.subheader("🔎 レース条件検索")
    st.caption("場・レース番号・期間を指定して出目を分析します")

    # パスワード認証
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.info("🔒 この機能はサブスクリプション会員限定です")
        pw = st.text_input("パスワードを入力してください", type="password", key="pw_input")
        if st.button("認証する", key="btn_auth"):
            try:
                correct_pw = st.secrets["PASSWORD"]
            except:
                correct_pw = "boat2605"
            if pw == correct_pw:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("パスワードが違います")
        st.markdown("---")
        st.caption("パスワードはnoteサブスクリプション会員向け記事に記載しています")
        st.caption("👉 https://note.com/boatrace_datalab")
    else:
        # 認証済みの場合は検索UIを表示
        st.success("✅ 認証済み")

        col1, col2 = st.columns(2)
        with col1:
            venue_names = [v[1] for v in VENUE_LIST]
            selected_venue = st.selectbox("場名", venue_names, key="search_venue")
            venue_id = [v[0] for v in VENUE_LIST if v[1] == selected_venue][0]

        with col2:
            race_no = st.selectbox("レース番号", list(range(1, 13)),
                                   format_func=lambda x: f"{x}R", key="search_race_no")

        col3, col4 = st.columns(2)
        with col3:
            year_from = st.selectbox("開始年", list(range(2015, 2027)), index=0, key="year_from")
        with col4:
            year_to = st.selectbox("終了年", list(range(2015, 2027)), index=11, key="year_to")

        selected_grades = st.multiselect(
            "レースグレード（複数選択可・未選択で全て対象）",
            ['IC', 'G3', 'G2', 'G1', 'SG'],
            default=[],
            key="search_grade"
        )

        if st.button("検索", type="primary", key="btn_search"):
            conn = sqlite3.connect(DB_PATH)
            try:
                # グレード条件
                if selected_grades:
                    grade_in = ','.join([f"'{g}'" for g in selected_grades])
                    grade_condition = f"AND rc.grade_code IN ({grade_in})"
                else:
                    grade_condition = ""

                # 対象レース数確認
                df_count = pd.read_sql(f"""
                    SELECT 
                        COUNT(*) as 総レース数,
                        ROUND(SUM(CASE WHEN r.rank_1st=1 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) as イン着率,
                        ROUND(SUM(r.is_mansen)*100.0/COUNT(*),1) as 万舟率,
                        ROUND(AVG(r.trifecta_pay),0) as 平均配当
                    FROM result r
                    JOIN race rc ON r.race_id = rc.race_id
                    WHERE rc.venue_id = {venue_id}
                    AND rc.race_no = {race_no}
                    AND CAST(strftime('%Y', rc.race_date) AS INTEGER) BETWEEN {year_from} AND {year_to}
                    {grade_condition}
                """, conn)

                total = int(df_count.iloc[0]['総レース数'])
                if total == 0:
                    st.warning("該当するレースが見つかりませんでした。")
                else:
                    grade_label = '・'.join(selected_grades) if selected_grades else '全グレード'
                    st.write(f"**対象レース数：{total:,}件**（{selected_venue}・{race_no}R・{year_from}〜{year_to}年・{grade_label}）")
                    col_a, col_b, col_c = st.columns(3)
                    col_a.metric("イン着率", f"{df_count.iloc[0]['イン着率']}%")
                    col_b.metric("万舟率", f"{df_count.iloc[0]['万舟率']}%")
                    col_c.metric("平均配当", f"{int(df_count.iloc[0]['平均配当']):,}円")

                    st.divider()

                    # 1号艇等級別内訳
                    st.write("**1号艇等級別内訳**")
                    df_grade = pd.read_sql(f"""
                        SELECT 
                            rc.in_grade as 等級,
                            COUNT(*) as 件数,
                            ROUND(COUNT(*)*100.0/{total},1) as 構成比,
                            ROUND(SUM(CASE WHEN r.rank_1st=1 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) as イン着率,
                            ROUND(SUM(r.is_mansen)*100.0/COUNT(*),1) as 万舟率
                        FROM result r
                        JOIN race rc ON r.race_id = rc.race_id
                        WHERE rc.venue_id = {venue_id}
                        AND rc.race_no = {race_no}
                        AND CAST(strftime('%Y', rc.race_date) AS INTEGER) BETWEEN {year_from} AND {year_to}
                        {grade_condition}
                        GROUP BY rc.in_grade
                        ORDER BY 件数 DESC
                    """, conn)
                    st.dataframe(df_grade, use_container_width=True, hide_index=True)

                    st.divider()

                    # 出目ランキング
                    st.write("**出目ランキングTOP20**")
                    df_combo = pd.read_sql(f"""
                        SELECT 
                            r.rank_1st as '1着',
                            r.rank_2nd as '2着',
                            r.rank_3rd as '3着',
                            COUNT(*) as 件数,
                            ROUND(COUNT(*)*100.0/{total},1) as '出現率(%)',
                            ROUND(AVG(r.trifecta_pay),0) as '平均配当(円)',
                            SUM(r.is_mansen) as 万舟回数
                        FROM result r
                        JOIN race rc ON r.race_id = rc.race_id
                        WHERE rc.venue_id = {venue_id}
                        AND rc.race_no = {race_no}
                        AND CAST(strftime('%Y', rc.race_date) AS INTEGER) BETWEEN {year_from} AND {year_to}
                        {grade_condition}
                        GROUP BY r.rank_1st, r.rank_2nd, r.rank_3rd
                        ORDER BY 件数 DESC
                        LIMIT 20
                    """, conn)
                    st.dataframe(df_combo, use_container_width=True, hide_index=True)

            except Exception as e:
                st.error(f"エラー：{e}")
            finally:
                conn.close()

        if st.button("ログアウト", key="btn_logout"):
            st.session_state.authenticated = False
            st.rerun()
# フッター
st.divider()
st.caption("© 2026 ボートレース判定ツール | データ：2018〜2026年 約31万件")
