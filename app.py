import streamlit as st
import pandas as pd
import json
import os
from datetime import date
from io import BytesIO
from openpyxl.utils import column_index_from_string

from calc import (
    calc_repayment_for_one,
    search_route_candidates,
    calc_repayment_from_candidate,
)
from ekispert import search_station

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_input.json")
MONTH_OPTIONS = [1, 3, 6, 12]


def load_input_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_input_cache(entries):
    try:
        data = []
        for e in entries:
            data.append({
                "name": e["name"],
                "from_station": e["from_station"],
                "from_code": e.get("from_code", ""),
                "to_station": e["to_station"],
                "to_code": e.get("to_code", ""),
                "via_stations": e["via_stations"],
                "teiki_months": e["teiki_months"],
                "start_date": e["start_date"].isoformat() if e["start_date"] else None,
                "cancel_date": e["cancel_date"].isoformat() if e["cancel_date"] else None,
                "purchase_price": e["purchase_price"],
            })
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def reset_station_candidates(row_no):
    for station_type in ("from", "to"):
        st.session_state.pop(f"{station_type}_{row_no}_candidates", None)


def search_station_on_change(key_prefix):
    """駅名の入力確定時に候補駅を自動検索する。"""
    input_name = st.session_state.get(f"{key_prefix}_input", "").strip()

    # 駅名を編集したら、以前の候補をいったん破棄する
    st.session_state.pop(f"{key_prefix}_candidates", None)
    st.session_state.pop(f"{key_prefix}_select", None)

    if not input_name:
        return

    try:
        result = search_station(input_name)
        if result["success"]:
            st.session_state[f"{key_prefix}_candidates"] = result["stations"]
        else:
            st.session_state[f"{key_prefix}_candidates"] = []
            st.session_state[f"{key_prefix}_station_error"] = result["message"]
    except Exception as ex:
        st.session_state[f"{key_prefix}_candidates"] = []
        st.session_state[f"{key_prefix}_station_error"] = f"駅検索中にエラーが発生しました：{ex}"


def station_selector(label, key_prefix, cached_name="", cached_code=""):
    """駅名入力、入力確定時の自動候補検索、候補選択を表示する。"""
    if f"{key_prefix}_input" not in st.session_state:
        st.session_state[f"{key_prefix}_input"] = cached_name

    st.text_input(
        label,
        key=f"{key_prefix}_input",
        placeholder="例：北野",
        on_change=search_station_on_change,
        args=(key_prefix,),
    )

    input_name = st.session_state.get(f"{key_prefix}_input", "").strip()
    candidates = st.session_state.get(f"{key_prefix}_candidates", [])
    error_message = st.session_state.pop(f"{key_prefix}_station_error", None)

    if error_message:
        st.warning(error_message)

    if len(candidates) == 1:
        chosen = candidates[0]
        st.caption(f"✓ 選択中：{chosen['label']}")
        return chosen["name"], chosen["code"]

    if len(candidates) > 1:
        selected_idx = st.selectbox(
            "候補駅を選択",
            options=list(range(len(candidates))),
            format_func=lambda idx: candidates[idx]["label"],
            key=f"{key_prefix}_select",
        )
        chosen = candidates[selected_idx]
        return chosen["name"], chosen["code"]

    # キャッシュを復元した直後で、まだ駅名を編集していない場合のみ駅コードを維持する
    if input_name == cached_name and cached_code:
        return cached_name, cached_code

    return input_name, ""



st.set_page_config(
    page_title="定期券払い戻し計算ツール",
    page_icon="🚃",
    layout="wide",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap');

/* ベースフォント */
html, body, [class*="css"], [data-testid] {
    font-family: 'DM Sans', system-ui, sans-serif !important;
    -webkit-font-smoothing: antialiased;
}

/* ページ背景 */
.stApp {
    background-color: #f8fafc !important;
}

/* コンテナ幅・余白 */
.block-container {
    max-width: 1400px !important;
    padding: 0 !important;
}

/* ヘッダーエリア（タイトル部分）*/
h1 {
    font-size: 1.35rem !important;
    font-weight: 800 !important;
    color: #0f172a !important;
    letter-spacing: -0.02em !important;
    line-height: 1.3 !important;
    margin: 0 !important;
    padding: 1rem 1.5rem !important;
    background: #ffffff !important;
    border-bottom: 1px solid #e2e8f0 !important;
}

/* セクション見出し */
h3 {
    font-size: 0.7rem !important;
    font-weight: 700 !important;
    color: #64748b !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    margin: 0 0 0.5rem 0 !important;
    padding: 0 !important;
}

h4 {
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    color: #64748b !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    margin: 0.75rem 0 0.4rem 0 !important;
    padding: 0 !important;
}

/* ラベル */
label, [data-testid="stWidgetLabel"] p {
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    color: #64748b !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
}

/* 入力フィールド共通 */
div[data-testid="stTextInput"],
div[data-testid="stNumberInput"],
div[data-testid="stSelectbox"],
div[data-testid="stDateInput"] {
    margin-bottom: 0.25rem !important;
}

[data-baseweb="input"],
[data-baseweb="select"] > div {
    border-radius: 6px !important;
    border-color: #e2e8f0 !important;
    background: #ffffff !important;
    font-size: 0.875rem !important;
    min-height: 36px !important;
}

[data-baseweb="input"]:focus-within,
[data-baseweb="select"] > div:focus-within {
    border-color: #2563eb !important;
    box-shadow: 0 0 0 2px rgba(37,99,235,0.15) !important;
}

input[type="text"],
input[type="number"] {
    font-family: 'DM Sans', sans-serif !important;
}

/* 数値入力はモノスペース */
input[type="number"] {
    font-family: 'JetBrains Mono', monospace !important;
}

/* ボタン共通 */
.stButton > button {
    height: 36px !important;
    border-radius: 6px !important;
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    font-family: 'DM Sans', sans-serif !important;
    padding: 0 1rem !important;
    border: 1px solid #e2e8f0 !important;
    background: #f1f5f9 !important;
    color: #334155 !important;
    transition: background 0.15s !important;
    line-height: 1 !important;
}

.stButton > button:hover {
    background: #e2e8f0 !important;
}

/* primaryボタン（経路検索）*/
.stButton > button[kind="primary"] {
    background: #2563eb !important;
    color: #ffffff !important;
    border-color: #2563eb !important;
}

.stButton > button[kind="primary"]:hover {
    background: #1d4ed8 !important;
    border-color: #1d4ed8 !important;
}

/* タブ */
[data-testid="stTabs"] {
    background: #ffffff !important;
    border-bottom: 1px solid #e2e8f0 !important;
    padding: 0 1.5rem !important;
    margin-bottom: 0 !important;
}

[data-testid="stTabs"] button {
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    color: #64748b !important;
    border-radius: 0 !important;
    padding: 0.6rem 1rem !important;
}

[data-testid="stTabs"] button[aria-selected="true"] {
    color: #0f172a !important;
    font-weight: 600 !important;
    border-bottom: 2px solid #2563eb !important;
}

/* メインコンテンツ余白 */
[data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stVerticalBlock"] {
    gap: 0.5rem !important;
}

section[data-testid="stSidebar"] + div .block-container {
    padding: 1.25rem 1.5rem 3rem !important;
}

.block-container > div {
    padding: 1.25rem 1.5rem 3rem !important;
}

/* アラート・メッセージ */
div[data-testid="stAlert"] {
    padding: 0.35rem 0.65rem !important;
    margin: 0.1rem 0 !important;
    border-radius: 6px !important;
    font-size: 0.82rem !important;
}

div[data-testid="stAlert"] p {
    font-size: 0.82rem !important;
    line-height: 1.4 !important;
    margin: 0 !important;
}

/* 成功 */
div[data-testid="stAlert"][data-baseweb="notification"][kind="success"] {
    background: #f0fdf4 !important;
    border: 1px solid #86efac !important;
    color: #166534 !important;
}

/* エラー */
div[data-testid="stAlert"][data-baseweb="notification"][kind="error"] {
    background: #fef2f2 !important;
    border: 1px solid #fca5a5 !important;
    color: #991b1b !important;
}

/* 警告 */
div[data-testid="stAlert"][data-baseweb="notification"][kind="warning"] {
    background: #fffbeb !important;
    border: 1px solid #fcd34d !important;
    color: #92400e !important;
}

/* インフォ */
div[data-testid="stAlert"][data-baseweb="notification"][kind="info"] {
    background: #eff6ff !important;
    border: 1px solid #93c5fd !important;
    color: #1e40af !important;
}

/* キャプション */
div[data-testid="stCaptionContainer"] p,
.stCaption {
    font-size: 0.78rem !important;
    color: #94a3b8 !important;
}

/* result-box（払い戻し結果）*/
.result-box {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    overflow: hidden;
    margin-top: 0.25rem;
}

.result-route {
    background: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
    padding: 0.6rem 0.85rem;
    font-size: 0.85rem;
    font-weight: 500;
    color: #1e293b;
    line-height: 1.5;
    word-break: break-word;
}

.result-price-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
    padding: 0.3rem 0.85rem;
    border-bottom: 1px solid #f1f5f9;
    font-size: 0.82rem;
}

.result-price-row span:first-child {
    color: #64748b;
}

.result-price-row span:last-child {
    font-family: 'JetBrains Mono', monospace;
    font-weight: 500;
    color: #334155;
    white-space: nowrap;
}

/* メトリクス（最終払い戻し額）*/
div[data-testid="stMetric"] {
    background: #f0fdf4 !important;
    border: 1px solid #86efac !important;
    border-radius: 0 0 8px 8px !important;
    padding: 0.55rem 0.85rem !important;
    margin: 0 !important;
}

div[data-testid="stMetricLabel"] p {
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    color: #166534 !important;
    text-transform: none !important;
    letter-spacing: normal !important;
}

div[data-testid="stMetricValue"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    color: #15803d !important;
}

/* セパレータ */
hr {
    border-color: #e2e8f0 !important;
    margin: 0.75rem 0 !important;
}

/* スクロールバー非表示 */
::-webkit-scrollbar { width: 0; height: 0; }

/* ツールバー件数ラベル */
.toolbar-count-label {
    color: #475569;
    font-size: 0.85rem;
    font-weight: 600;
    line-height: 36px;
    white-space: nowrap;
}

/* パネルタイトル */
.panel-title {
    font-size: 0.72rem;
    font-weight: 700;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin: 0 0 0.4rem 0;
}

@media (max-width: 800px) {
    h1 { font-size: 1.1rem !important; padding: 0.8rem 1rem !important; }
    .block-container > div { padding: 1rem !important; }
}
</style>""", unsafe_allow_html=True)

st.title("🚃 定期券払い戻し計算ツール")

tab1, tab2 = st.tabs(["📝 手入力モード", "📂 CSV取込モード"])


with tab1:
    st.markdown(
        "### 定期券情報の入力（駅を検索・選択した後、経路候補を選んで払い戻し額を計算します。）"
    )

    input_cache = load_input_cache()

    if "num_rows" not in st.session_state:
        st.session_state["num_rows"] = 1

    # 件数操作を左に集約し、検索・計算ボタンは必要な幅だけにする
    count_area, search_area, calc_area, note_area = st.columns(
        [2.15, 1.15, 1.45, 2.25],
        gap="small",
        vertical_alignment="center",
    )

    with count_area:
        count_label, add_button, remove_button = st.columns(
            [4.6, 0.55, 0.55],
            gap="small",
            vertical_alignment="center",
        )

        with count_label:
            st.markdown(
                "<div class='toolbar-count-label'>払戻し件数を追加</div>",
                unsafe_allow_html=True,
            )

        with add_button:
            if st.button("＋", key="btn_add_row"):
                if st.session_state["num_rows"] < 10:
                    st.session_state["num_rows"] += 1
                    st.rerun()

        with remove_button:
            if st.button("－", key="btn_remove_row"):
                if st.session_state["num_rows"] > 1:
                    removed = st.session_state["num_rows"] - 1
                    reset_station_candidates(removed)
                    st.session_state.pop(f"candidates_{removed}", None)
                    st.session_state["num_rows"] -= 1
                    st.rerun()

    with search_area:
        do_search = st.button(
            "🔍 経路を検索",
            key="btn_search_routes",
            type="primary",
        )

    with calc_area:
        do_calc = st.button(
            "💰 選択経路で計算",
            key="btn_calc_selected",
        )

    with note_area:
        st.markdown(
            "<div class='toolbar-note'>駅名入力後に Enter または入力欄の外をクリックすると、候補駅が表示されます。</div>",
            unsafe_allow_html=True,
        )


    # 検索結果メッセージは入力欄より上に表示
    if st.session_state.get("search_log"):
        for kind, message in st.session_state["search_log"]:
            if kind == "success":
                st.success(message)
            else:
                st.error(message)

    num_rows = st.session_state["num_rows"]

    num_rows = st.session_state["num_rows"]
    entries = []

    for i in range(num_rows):
        cached = input_cache[i] if i < len(input_cache) else {}
        cached_start = date.fromisoformat(cached["start_date"]) if cached.get("start_date") else date.today()
        cached_cancel = date.fromisoformat(cached["cancel_date"]) if cached.get("cancel_date") else date.today()
        cached_months = cached.get("teiki_months", 6)
        months_index = MONTH_OPTIONS.index(cached_months) if cached_months in MONTH_OPTIONS else 2

        st.markdown(f"#### 📄 {i + 1}件目")
        left_col, right_col = st.columns([0.9, 1.1], gap="large")

        with left_col:
            st.markdown("<div class='input-panel'><div class='panel-title'>入力内容</div>", unsafe_allow_html=True)
            top_col1, top_col2 = st.columns([1.15, .85])
            with top_col1:
                name = st.text_input("名前", key=f"name_{i}", value=cached.get("name", ""), placeholder="例：山田太郎")
            with top_col2:
                purchase_price = st.number_input(
                    "定期券購入金額（円）",
                    min_value=0,
                    step=10,
                    key=f"price_{i}",
                    value=int(cached.get("purchase_price", 0) or 0),
                )

            station_col1, station_col2 = st.columns(2)
            with station_col1:
                from_name, from_code = station_selector(
                    "出発駅", f"from_{i}", cached.get("from_station", ""), cached.get("from_code", "")
                )
            with station_col2:
                to_name, to_code = station_selector(
                    "到着駅", f"to_{i}", cached.get("to_station", ""), cached.get("to_code", "")
                )

            via_text = st.text_input(
                "経由駅（任意・複数はカンマ区切り）",
                key=f"via_{i}",
                value=",".join(cached.get("via_stations", [])),
                placeholder="例：代々木,原宿",
            )

            date_col1, date_col2, date_col3 = st.columns(3)
            with date_col1:
                teiki_months = st.selectbox("定期券有効期間", MONTH_OPTIONS, format_func=lambda x: f"{x}ヶ月", index=months_index, key=f"months_{i}")
            with date_col2:
                start_date = st.date_input("有効開始日", key=f"start_{i}", value=cached_start)
            with date_col3:
                cancel_date = st.date_input("払い戻し日", key=f"cancel_{i}", value=cached_cancel)
            st.markdown("</div>", unsafe_allow_html=True)

        via_stations = [v.strip() for v in via_text.split(",") if v.strip()]
        entries.append({
            "name": name,
            "from_station": from_name,
            "from_code": from_code,
            "to_station": to_name,
            "to_code": to_code,
            "via_stations": via_stations,
            "teiki_months": teiki_months,
            "start_date": start_date,
            "cancel_date": cancel_date,
            "purchase_price": purchase_price,
        })

        with right_col:
            st.markdown("<div class='result-panel'><div class='panel-title'>検索結果・払い戻し金額</div>", unsafe_allow_html=True)
            candidates = st.session_state.get(f"candidates_{i}", [])
            if candidates:
                def format_route(idx, route_list=candidates, months=teiki_months):
                    route = route_list[idx]
                    text = f"{route['transport_type']}｜{route['display_route']}"
                    price = route.get("teiki_prices", {}).get(months)
                    if price is not None:
                        text += f"｜{months}ヶ月：{price:,}円"
                    return text

                st.selectbox("経路を選択", list(range(len(candidates))), format_func=format_route, key=f"selected_{i}")
            else:
                st.info("駅を選択後、上部の「経路を検索する」を押してください。")

            manual_results = st.session_state.get("manual_results", [])
            row_result = next((r for r in manual_results if r.get("row") == i), None)
            if row_result:
                if not row_result["success"]:
                    st.error(f"計算できませんでした：{row_result['message']}")
                else:
                    st.markdown("<div class='result-box'>", unsafe_allow_html=True)
                    st.markdown(f"<div class='result-route'>🚃 {row_result['transport_type']}<br>📍 {row_result['display_route']}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='result-price-row'><span>購入金額（API）</span><span>{row_result['pay_price']:,}円</span></div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='result-price-row'><span>使用済み金額</span><span>{row_result['used_price']:,}円</span></div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='result-price-row'><span>払い戻し額（手数料前）</span><span>{row_result['repay_price']:,}円</span></div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='result-price-row'><span>手数料</span><span>{row_result['fee_price']:,}円</span></div>", unsafe_allow_html=True)
                    st.metric("✅ 最終払い戻し額", f"{row_result['refund_after_fee']:,}円")
                    st.markdown("</div>", unsafe_allow_html=True)
                    if row_result.get("discrepancy"):
                        st.warning(row_result["discrepancy"])
            st.markdown("</div>", unsafe_allow_html=True)

        if i < num_rows - 1:
            st.markdown("---")

    save_input_cache(entries)

    if do_search:
        search_log = []
        st.session_state.pop("manual_results", None)
        for i, entry in enumerate(entries):
            if not entry["from_station"] or not entry["to_station"]:
                st.session_state.pop(f"candidates_{i}", None)
                search_log.append(("error", f"{i + 1}件目：出発駅・到着駅を入力してください。"))
                continue

            from_value = entry["from_code"] or entry["from_station"]
            to_value = entry["to_code"] or entry["to_station"]
            with st.spinner(f"{i + 1}件目の経路を検索中..."):
                result = search_route_candidates(from_value, to_value, entry["via_stations"], answer_count=5)

            if result["success"]:
                st.session_state[f"candidates_{i}"] = result["candidates"]
                search_log.append(("success", f"{i + 1}件目：{len(result['candidates'])}件の候補が見つかりました。"))
            else:
                st.session_state[f"candidates_{i}"] = []
                search_log.append(("error", f"{i + 1}件目：{result['message']}"))
        st.session_state["search_log"] = search_log
        st.rerun()

    

    if do_calc:
        target_rows = [i for i in range(num_rows) if st.session_state.get(f"candidates_{i}")]
        if not target_rows:
            st.error("先に「経路を検索する」を押し、経路候補を取得してください。")
        else:
            results = []
            for i, entry in enumerate(entries):
                candidates = st.session_state.get(f"candidates_{i}", [])
                if not candidates:
                    continue
                selected_idx = st.session_state.get(f"selected_{i}", 0)
                selected_idx = min(selected_idx, len(candidates) - 1)
                try:
                    with st.spinner(f"{i + 1}件目を計算中..."):
                        result = calc_repayment_from_candidate(
                            candidates[selected_idx], entry["teiki_months"], entry["start_date"], entry["cancel_date"], entry["purchase_price"]
                        )
                except Exception as ex:
                    result = {"success": False, "message": f"予期しないエラー：{ex}"}

                result.update({
                    "row": i,
                    "name": entry["name"],
                    "from_station": entry["from_station"],
                    "to_station": entry["to_station"],
                    "input_purchase_price": entry["purchase_price"],
                })
                results.append(result)
            st.session_state["manual_results"] = results
            st.rerun()

    manual_results = st.session_state.get("manual_results", [])
    if manual_results:
        st.markdown("---")
        export_rows = []
        for result in manual_results:
            export_rows.append({
                "名前": result["name"], "出発駅": result["from_station"], "到着駅": result["to_station"],
                "結果": "成功" if result["success"] else "エラー", "電車orバス": result.get("transport_type", ""),
                "払い戻し経路": result.get("display_route", ""), "入力した購入金額": result.get("input_purchase_price", ""),
                "API計算の購入金額": result.get("pay_price", ""), "使用済み金額": result.get("used_price", ""),
                "払い戻し金額(手数料前)": result.get("repay_price", ""), "手数料": result.get("fee_price", ""),
                "手数料控除後の払戻額": result.get("refund_after_fee", ""),
                "エラー内容": result.get("message", "") if not result["success"] else "",
                "金額差異の注意": result.get("discrepancy", ""),
            })
        output = BytesIO()
        pd.DataFrame(export_rows).to_excel(output, index=False, engine="openpyxl")
        output.seek(0)
        st.download_button("📥 全件の結果をExcelでダウンロード", output, "定期券払い戻し計算結果_手入力.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_manual_result")


# ===============================================================
# TAB2：CSV取込モード
# ===============================================================
COL_START_DATE = column_index_from_string("K") - 1
COL_FROM = column_index_from_string("O") - 1
COL_TO = column_index_from_string("P") - 1
COL_VIA = column_index_from_string("Q") - 1
COL_MONTHS = column_index_from_string("R") - 1
COL_PRICE = column_index_from_string("S") - 1
COL_CANCEL_DATE = column_index_from_string("V") - 1

OUT_COLS = [
    "電車orバス", "駅すぱあとの払い戻し経路", "払い戻し金額(手数料前)",
    "手数料", "手数料控除後の払戻額",
]

with tab2:
    st.markdown("### CSV/Excelファイルを取り込んで一括計算します")
    st.caption("列位置：K列=定期券開始日 / O列=出発駅 / P列=降車駅 / Q列=経由地 / R列=種別(月数) / S列=定期券代 / V列=解約日")

    uploaded_file = st.file_uploader("CSVまたはExcelファイルを選択", type=["csv", "xlsx"], key="uploader")
    has_header = st.checkbox("先頭行は見出し行なので読み飛ばす", value=True, key="has_header")

    if uploaded_file is not None:
        if uploaded_file.name.endswith(".xlsx"):
            raw_df = pd.read_excel(uploaded_file, header=None, skiprows=1 if has_header else 0)
        else:
            raw_bytes = uploaded_file.getvalue()
            try:
                raw_df = pd.read_csv(BytesIO(raw_bytes), header=None, skiprows=1 if has_header else 0, encoding="utf-8-sig")
            except UnicodeDecodeError:
                raw_df = pd.read_csv(BytesIO(raw_bytes), header=None, skiprows=1 if has_header else 0, encoding="cp932")

        if ("csv_df" not in st.session_state or st.session_state.get("csv_filename") != uploaded_file.name or st.session_state.get("csv_has_header") != has_header):
            work_df = raw_df.copy()
            for col in OUT_COLS:
                work_df[col] = ""
            st.session_state["csv_df"] = work_df
            st.session_state["csv_filename"] = uploaded_file.name
            st.session_state["csv_has_header"] = has_header

        work_df = st.session_state["csv_df"]
        st.markdown("#### 取込内容の確認・修正")
        st.caption("結果が誤っている場合は表を直接編集してから「検索・再検索を実行」を押してください。")

        edited_df = st.data_editor(pd.DataFrame({
            "定期券開始日": work_df[COL_START_DATE], "出発駅": work_df[COL_FROM], "降車駅": work_df[COL_TO],
            "経由地": work_df[COL_VIA], "種別(月数)": work_df[COL_MONTHS], "定期券代": work_df[COL_PRICE],
            "解約日": work_df[COL_CANCEL_DATE], "電車orバス": work_df["電車orバス"],
            "駅すぱあとの払い戻し経路": work_df["駅すぱあとの払い戻し経路"],
            "払い戻し金額(手数料前)": work_df["払い戻し金額(手数料前)"], "手数料": work_df["手数料"],
            "手数料控除後の払戻額": work_df["手数料控除後の払戻額"],
        }), num_rows="fixed", key="editor", use_container_width=True)

        if st.button("🔍 検索・再検索を実行", key="btn_csv_search", type="primary", use_container_width=True):
            progress = st.progress(0)
            for i in range(len(edited_df)):
                row = edited_df.iloc[i]
                try:
                    result = calc_repayment_for_one(str(row["出発駅"]), str(row["降車駅"]), str(row["経由地"]) if pd.notna(row["経由地"]) else "", int(row["種別(月数)"]), str(row["定期券開始日"]), str(row["解約日"]))
                except Exception as ex:
                    result = {"success": False, "message": f"入力値エラー：{ex}"}

                if result["success"]:
                    edited_df.at[i, "電車orバス"] = result["transport_type"]
                    edited_df.at[i, "駅すぱあとの払い戻し経路"] = result["display_route"]
                    edited_df.at[i, "払い戻し金額(手数料前)"] = result["repay_price"]
                    edited_df.at[i, "手数料"] = result["fee_price"]
                    edited_df.at[i, "手数料控除後の払戻額"] = result["refund_after_fee"]
                else:
                    edited_df.at[i, "電車orバス"] = ""
                    edited_df.at[i, "駅すぱあとの払い戻し経路"] = f"エラー：{result['message']}"
                    edited_df.at[i, "払い戻し金額(手数料前)"] = ""
                    edited_df.at[i, "手数料"] = ""
                    edited_df.at[i, "手数料控除後の払戻額"] = ""
                progress.progress((i + 1) / len(edited_df))

            work_df[COL_START_DATE] = edited_df["定期券開始日"]
            work_df[COL_FROM] = edited_df["出発駅"]
            work_df[COL_TO] = edited_df["降車駅"]
            work_df[COL_VIA] = edited_df["経由地"]
            work_df[COL_MONTHS] = edited_df["種別(月数)"]
            work_df[COL_PRICE] = edited_df["定期券代"]
            work_df[COL_CANCEL_DATE] = edited_df["解約日"]
            for col in OUT_COLS:
                work_df[col] = edited_df[col]
            st.session_state["csv_df"] = work_df
            st.success("検索・計算が完了しました。")
            st.rerun()

        st.markdown("---")
        if st.button("💾 Excelを作成", key="btn_csv_save", use_container_width=True):
            output = BytesIO()
            work_df.to_excel(output, index=False, header=False, engine="openpyxl")
            output.seek(0)
            st.download_button("📥 ダウンロード", output, "払い戻し計算結果.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_csv_result")
