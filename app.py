# app.py (v1.6 升級版：顯示照片容量與 200MB 進度條 + 即時階段進度顯示與極速查價 + 預設庫存=0 先上架至「已售完」安全暫存區)
import os
import time
import json
import importlib
from pathlib import Path
from typing import Dict, List
import streamlit as st
import streamlit.components.v1 as components

import models
import chart_generator
import agent_pipeline

importlib.reload(models)
importlib.reload(chart_generator)
importlib.reload(agent_pipeline)

INPUT_DIR = Path("./input_photos")
OUTPUT_DIR = Path("./output_listings")
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_LIMIT_MB = 200.0

st.set_page_config(
    page_title="蝦皮 AI 快速上架助手 v1.6",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def format_size_mb(size_bytes: int) -> str:
    mb = size_bytes / (1024 * 1024)
    if mb < 0.1:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{mb:.2f} MB"


def render_ios_copy_card(data: dict, selected_price: int, stock_qty: int):
    """渲染專為 iPhone Safari 設計的單手拇指大顆一鍵複製面板（含庫存數量 0『已售完』安全暫存模式提示）"""
    dims = data.get("dimensions", {})
    cat_str = " > ".join(data.get("suggested_category_path", []))
    stock_label_note = "已售完暫存區" if stock_qty == 0 else "正式開賣"

    fields = [
        {"id": "cp_title", "label": "1️⃣ 複製【商品名稱】(60字內)", "value": data.get("shopee_title", ""), "primary": True},
        {"id": "cp_desc", "label": "2️⃣ 複製【商品描述】(完整排版文案)", "value": data.get("shopee_description", ""), "primary": True},
        {"id": "cp_price", "label": f"3️⃣ 複製【售價】(${selected_price})", "value": str(selected_price), "primary": False},
        {"id": "cp_stock", "label": f"4️⃣ 複製【商品數量】({stock_qty} ➔ {stock_label_note})", "value": str(stock_qty), "primary": False},
        {"id": "cp_weight", "label": f"5️⃣ 複製【重量】({dims.get('weight_kg', 0.5)} kg)", "value": str(dims.get("weight_kg", 0.5)), "primary": False},
        {"id": "cp_isbn", "label": f"6️⃣ 複製【國際條碼 GTIN/ISBN】({data.get('isbn_or_barcode') or '無'})", "value": str(data.get("isbn_or_barcode") or ""), "primary": False},
        {"id": "cp_bsmi", "label": f"7️⃣ 複製【BSMI 字號】({data.get('bsmi_number') or '無'})", "value": str(data.get("bsmi_number") or ""), "primary": False},
        {"id": "cp_batch", "label": f"8️⃣ 複製【BSMI 批號】({data.get('bsmi_batch_number') or '無'})", "value": str(data.get("bsmi_batch_number") or ""), "primary": False},
    ]

    fields_json = json.dumps(fields, ensure_ascii=False)

    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
      <style>
        body {{
          font-family: -apple-system, BlinkMacSystemFont, "PingFang TC", "Microsoft JhengHei", sans-serif;
          margin: 0;
          padding: 4px;
          background: transparent;
        }}
        .ios-panel {{
          background: #ffffff;
          border: 2px solid #ee4d2d;
          border-radius: 16px;
          padding: 14px;
          box-shadow: 0 6px 18px rgba(238, 77, 45, 0.12);
        }}
        .panel-header {{
          font-size: 16px;
          font-weight: 700;
          color: #ee4d2d;
          margin-bottom: 6px;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }}
        .cat-badge {{
          background: #fff7ed;
          border: 1px solid #fed7aa;
          color: #9a3412;
          border-radius: 10px;
          padding: 8px 10px;
          font-size: 13px;
          margin-bottom: 12px;
          line-height: 1.5;
        }}
        .draft-tip {{
          background: #f0fdf4;
          border: 1px solid #bbf7d0;
          color: #166534;
          border-radius: 8px;
          padding: 6px 10px;
          font-size: 12px;
          margin-bottom: 10px;
        }}
        .btn-grid {{
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 10px;
        }}
        .copy-btn {{
          appearance: none;
          -webkit-tap-highlight-color: transparent;
          border: 1.5px solid #cbd5e1;
          background: #f8fafc;
          color: #1e293b;
          border-radius: 12px;
          padding: 14px 12px;
          font-size: 13.5px;
          font-weight: 600;
          text-align: left;
          cursor: pointer;
          transition: all 0.15s ease;
          display: flex;
          align-items: center;
          justify-content: space-between;
          box-shadow: 0 2px 4px rgba(0,0,0,0.04);
        }}
        .copy-btn.full-width {{
          grid-column: span 2;
          background: #fff1f0;
          border-color: #ffa39e;
          color: #cf1322;
          font-size: 15px;
          padding: 16px 14px;
        }}
        .copy-btn:active {{
          transform: scale(0.97);
        }}
        .copy-btn.copied {{
          background: #16a34a !important;
          border-color: #15803d !important;
          color: #ffffff !important;
        }}
        .shopee-launch {{
          margin-top: 12px;
          display: block;
          text-align: center;
          background: #ee4d2d;
          color: #ffffff;
          text-decoration: none;
          font-weight: 700;
          font-size: 15px;
          padding: 14px;
          border-radius: 12px;
        }}
      </style>
    </head>
    <body>
      <div class="ios-panel">
        <div class="panel-header">
          <span>📱 iPhone 單手極速複製面板</span>
          <span style="font-size:12px;color:#64748b;font-weight:normal;">點一下即複製</span>
        </div>
        <div class="cat-badge">
          📂 <b>建議分類：</b>{cat_str or "請手動選擇"}<br/>
          📦 <b>保存狀況：</b>{data.get("condition", "二手")} ｜ <b>品牌：</b>{data.get("brand") or "無"} ｜ <b>尺寸：</b>{dims.get("length_cm", 0)}x{dims.get("width_cm", 0)}x{dims.get("height_cm", 0)} cm
        </div>
        <div class="draft-tip">
          🛡️ <b>安全上架提示：</b>在蝦皮 App 把「商品數量」填為 <b>{stock_qty}</b> 並按「上架」，商品就會先躺在你的<b>【已售完】</b>清單中，不會被買家誤買，等你微調確認後再把庫存改為 1 即可！
        </div>
        <div class="btn-grid" id="btnContainer"></div>
        <a class="shopee-launch" href="shopee://" target="_blank">
          🚀 點此切換打開「蝦皮 App」直接貼上
        </a>
      </div>

      <script>
        const fields = {fields_json};
        const container = document.getElementById("btnContainer");

        function fallbackCopyText(text) {{
          const ta = document.createElement("textarea");
          ta.value = text;
          ta.style.position = "fixed";
          ta.style.opacity = "0";
          document.body.appendChild(ta);
          ta.focus();
          ta.select();
          document.execCommand("copy");
          document.body.removeChild(ta);
        }}

        async function copyToClipboard(text, btnEl, originalLabel) {{
          try {{
            if (navigator.clipboard && window.isSecureContext) {{
              await navigator.clipboard.writeText(text);
            }} else {{
              fallbackCopyText(text);
            }}
          }} catch (e) {{
            fallbackCopyText(text);
          }}
          btnEl.classList.add("copied");
          btnEl.innerHTML = "<span>✅ 已複製到 iPhone 剪貼簿！</span><span>📋</span>";
          setTimeout(() => {{
            btnEl.classList.remove("copied");
            btnEl.innerHTML = `<span>${{originalLabel}}</span><span>📋</span>`;
          }}, 1400);
        }}

        fields.forEach(item => {{
          const btn = document.createElement("button");
          btn.className = "copy-btn" + (item.primary ? " full-width" : "");
          btn.innerHTML = `<span>${{item.label}}</span><span>📋</span>`;
          btn.onclick = () => copyToClipboard(item.value || "", btn, item.label);
          container.appendChild(btn);
        }});
      </script>
    </body>
    </html>
    """
    components.html(html_code, height=520, scrolling=False)


def resolve_api_key() -> str:
    """依序從環境變數或 Streamlit Cloud Secrets 讀取 GEMINI_API_KEY"""
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        if "GEMINI_API_KEY" in st.secrets:
            sec_key = str(st.secrets["GEMINI_API_KEY"]).strip()
            if sec_key:
                os.environ["GEMINI_API_KEY"] = sec_key
                return sec_key
    except Exception:
        pass
    return ""


st.title("🛍️ 蝦皮 AI 智慧上架小工具 v1.6")
st.caption("iPhone 容量監控 ＋ 二合一極速查價進度條 ＋ 支援先存蝦皮【已售完 (數量=0)】安全微調模式")

saved_api_key = resolve_api_key()

with st.sidebar:
    st.header("⚙️ 系統設定")
    api_key_input = st.text_input(
        "Gemini API Key",
        value=saved_api_key,
        type="password",
        help="若已在 Streamlit Secrets 設定 GEMINI_API_KEY 會自動載入"
    )
    if api_key_input:
        os.environ["GEMINI_API_KEY"] = api_key_input

    selected_model = st.selectbox(
        "AI 模型版本 (自動鎖定最快 Flash 模型)",
        options=["gemini-3.8-flash", "gemini-3.0-flash", "gemini-2.5-flash"],
        index=0,
    )

tab_upload, tab_review = st.tabs(["📸 1. iPhone 拍照上傳與容量檢測", "📱 2. 單手複製與【已售完】暫存上架"])

# ==================== Tab 1: 上傳照片、容量顯示與觸發 Agent ====================
with tab_upload:
    st.subheader("步驟 1：選擇上傳模式與商品照片")

    col_m1, col_m2 = st.columns(2)
    with col_m1:
        grouping_mode = st.radio(
            "📦 這次上傳的照片屬於幾件商品？",
            options=[
                "⚡ 同一個商品的多張不同角度照片（二合一極速通道，約 12~25 秒完成！）",
                "🔀 多件不同商品的照片混傳（先分群再逐一查價）"
            ],
            index=0,
        )
        force_single_item = "同一個商品" in grouping_mode

    with col_m2:
        stock_mode = st.radio(
            "🛡️ 後續上架蝦皮的預設庫存模式：",
            options=[
                "🔒 先上架到【已售完】暫存區（預設商品數量 = 0，微調確認後再改為 1）",
                "🟢 直接正式開賣（預設商品數量 = 1）"
            ],
            index=0,
        )
        default_stock_qty = 0 if "已售完" in stock_mode else 1

    only_analyze_new = st.checkbox(
        "✨ 只分析我這次剛選取上傳的照片（自動忽略資料夾內之前的舊照片）",
        value=True
    )

    uploaded_files = st.file_uploader(
        "點擊選取相簿照片或直接拍攝（單次上限 200MB）",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
    )

    user_notes: Dict[str, str] = {}
    newly_uploaded_names: List[str] = []
    uploaded_total_bytes = 0

    if uploaded_files:
        for ufile in uploaded_files:
            uploaded_total_bytes += ufile.size

        uploaded_mb = uploaded_total_bytes / (1024 * 1024)
        usage_ratio = min(1.0, uploaded_mb / MAX_UPLOAD_LIMIT_MB)
        remain_mb = max(0.0, MAX_UPLOAD_LIMIT_MB - uploaded_mb)

        if uploaded_mb > MAX_UPLOAD_LIMIT_MB:
            st.error(
                f"⚠️ **容量超標警告**：本次選取 {len(uploaded_files)} 張照片共 **{uploaded_mb:.2f} MB**，"
                f"已超過 **200 MB** 上限！請減少單次上傳張數。"
            )
        else:
            st.success(
                f"📊 **上傳容量檢測正常**：本次選取 **{len(uploaded_files)}** 張照片 ｜ "
                f"目前總計佔用 **{format_size_mb(uploaded_total_bytes)}** / 200 MB 上限 "
                f"（僅佔 **{usage_ratio * 100:.1f}%**，尚餘 **{remain_mb:.1f} MB** 可用，✅ 未超過 200MB！）"
            )
        st.progress(usage_ratio)

        global_note = st.text_input(
            "📝 整體商品備註（選填，例如：九成新、功能正常、附原盒、適合腳長18cm內）",
            placeholder="打在這裡的備註會直接套用到這次上傳的商品..."
        )

        cols = st.columns(min(4, len(uploaded_files)))
        for idx, ufile in enumerate(uploaded_files):
            save_path = INPUT_DIR / ufile.name
            with open(save_path, "wb") as f:
                f.write(ufile.getbuffer())
            newly_uploaded_names.append(ufile.name)
            if global_note.strip():
                user_notes[ufile.name] = global_note.strip()

            col = cols[idx % len(cols)]
            with col:
                st.image(ufile, caption=f"{ufile.name} ({format_size_mb(ufile.size)})", use_container_width=True)

    existing_files_paths = sorted([
        p for p in INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
    ])
    existing_photos = [p.name for p in existing_files_paths]
    folder_total_bytes = sum(p.stat().st_size for p in existing_files_paths)

    col_info, col_clear = st.columns([3, 1])
    with col_info:
        if only_analyze_new and newly_uploaded_names:
            st.info(
                f"🎯 本次將分析剛上傳的 **{len(newly_uploaded_names)}** 張照片 "
                f"（原始容量共 **{format_size_mb(uploaded_total_bytes)}**，AI 分析前會自動壓縮至 ~0.3MB 極速傳送）"
            )
        else:
            st.write(
                f"📂 目前雲端 `input_photos` 資料夾共有 **{len(existing_photos)}** 張照片 "
                f"（總容量：**{format_size_mb(folder_total_bytes)}** / 200 MB）：{', '.join(existing_photos)}"
            )
    with col_clear:
        if st.button("🗑️ 清空資料夾舊照片", use_container_width=True):
            for f in INPUT_DIR.glob("*"):
                if f.is_file():
                    f.unlink()
            st.success("已清空舊照片！")
            st.rerun()

    if st.button("🚀 啟動 AI 極速分析、聯網查價與產生蝦皮欄位", type="primary", use_container_width=True):
        target_list = newly_uploaded_names if (only_analyze_new and newly_uploaded_names) else existing_photos

        if not os.environ.get("GEMINI_API_KEY"):
            st.error("找不到 GEMINI_API_KEY！請於左側邊欄輸入，或在 Streamlit Secrets 設定 GEMINI_API_KEY。")
        elif not target_list:
            st.warning("請先選取上傳至少一張商品照片！")
        else:
            progress_bar = st.progress(0, text="⏳ 準備啟動 AI 極速管線...")
            status_box = st.status("🚀 正在執行 AI 視覺辨識與全網比價...", expanded=True)
            start_ts = time.time()

            def update_ui_progress(msg: str, pct: int):
                elapsed = round(time.time() - start_ts, 1)
                progress_bar.progress(min(100, max(0, int(pct))), text=f"[{elapsed}s] {msg}")
                status_box.write(f"⏱️ `{elapsed}s` ｜ {msg}")

            try:
                importlib.reload(agent_pipeline)
                agent_pipeline.run_pipeline(
                    image_dir=str(INPUT_DIR),
                    output_dir=str(OUTPUT_DIR),
                    user_notes=user_notes,
                    target_files=target_list,
                    force_single_item=force_single_item,
                    preferred_model=selected_model,
                    progress_cb=update_ui_progress,
                    default_stock=default_stock_qty,
                )
                total_sec = round(time.time() - start_ts, 1)
                status_box.update(label=f"🎉 分析完成！（總耗時 {total_sec} 秒）", state="complete", expanded=False)
                st.success(f"✅ 已完成分析（耗時 {total_sec} 秒）！請點選上方「📱 2. 單手複製與【已售完】暫存上架」分頁。")
            except Exception as e:
                status_box.update(label="❌ 執行過程發生錯誤", state="error", expanded=True)
                st.error(f"執行過程發生錯誤：{e}")

# ==================== Tab 2: iPhone 單手極速複製與審核 ====================
with tab_review:
    item_dirs = sorted([d for d in OUTPUT_DIR.iterdir() if d.is_dir()])

    if not item_dirs:
        st.info("目前 `output_listings` 尚無已分析的商品資料，請先於第一分頁上傳照片並啟動分析。")
    else:
        selected_group = st.selectbox(
            "選擇要上架的商品編號",
            options=[d.name for d in item_dirs],
            format_func=lambda x: f"📦 待上架商品：{x}"
        )

        item_dir = OUTPUT_DIR / selected_group
        json_path = item_dir / "listing.json"
        chart_path = item_dir / "size_chart.png"

        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            pricing = data.get("pricing", {})
            p_quick = pricing.get("suggested_quick_sale_price", 100)
            p_std = pricing.get("suggested_standard_price", 150)
            p_high = pricing.get("suggested_high_price", 200)

            col_p, col_s = st.columns([1.4, 1])
            with col_p:
                st.markdown("#### 💰 步驟 1：點選要賣的價格檔位")
                st.caption(
                    f"📊 原定價：${pricing.get('original_list_price_twd') or '無'} ｜ "
                    f"新品市價：${pricing.get('new_market_price_twd') or '無'} ｜ "
                    f"二手行情：${pricing.get('used_price_min_twd') or '?'}~${pricing.get('used_price_max_twd') or '?'}"
                )
                price_tier = st.radio(
                    "定價檔位選擇",
                    options=[
                        f"🔥 快速出清 (${p_quick})",
                        f"✅ 一般行情 (${p_std})",
                        f"💎 近全新 (${p_high})",
                        "🛠️ 自訂"
                    ],
                    index=1,
                    horizontal=True,
                    label_visibility="collapsed"
                )
                if "快速出清" in price_tier:
                    selected_price = p_quick
                elif "一般行情" in price_tier:
                    selected_price = p_std
                elif "近全新" in price_tier:
                    selected_price = p_high
                else:
                    selected_price = st.number_input("輸入自訂售價 (NT$)", min_value=1, value=int(p_std))

            with col_s:
                st.markdown("#### 🛡️ 上架暫存狀態（商品數量）")
                saved_stock = int(data.get("stock_quantity", 0))
                stock_choice = st.radio(
                    "選擇上架時的商品數量",
                    options=[
                        "🔒 先放【已售完】區 (數量 = 0，安全微調)",
                        "🟢 正式開賣 (數量 = 1)"
                    ],
                    index=0 if saved_stock == 0 else 1,
                    label_visibility="collapsed"
                )
                selected_stock = 0 if "已售完" in stock_choice else 1

            data["selected_listing_price_twd"] = int(selected_price)
            data["stock_quantity"] = selected_stock

            st.markdown("#### 📱 步驟 2：iPhone 單手點選複製（點完直接切去蝦皮 App 貼上）")
            render_ios_copy_card(data, int(selected_price), selected_stock)

            if chart_path.exists():
                st.markdown("#### 📏 步驟 3：長按圖片儲存尺寸表（供蝦皮服飾/鞋類上傳）")
                st.image(str(chart_path), caption="iPhone 可直接長按上方圖片選擇「加入照片」", use_container_width=True)

            with st.expander("🖼️ 檢視此商品包含的所有角度照片"):
                img_files = data.get("image_filenames", [])
                if img_files:
                    g_cols = st.columns(min(4, len(img_files)))
                    for i, fname in enumerate(img_files):
                        img_p = INPUT_DIR / fname
                        if img_p.exists():
                            g_cols[i % len(g_cols)].image(str(img_p), caption=fname, use_container_width=True)

            with st.expander("✏️ 需要微調文字或欄位內容？（點此展開編輯）"):
                current_title = data.get("shopee_title", "")
                new_title = st.text_input(
                    f"商品名稱（目前 {len(current_title)} / 60 字元）",
                    value=current_title,
                    max_chars=60
                )
                new_desc = st.text_area(
                    "商品描述（上限 3000 字元）",
                    value=data.get("shopee_description", ""),
                    height=220
                )
                c1, c2 = st.columns(2)
                with c1:
                    new_cond = st.selectbox(
                        "保存狀況",
                        options=["二手", "全新"],
                        index=0 if data.get("condition") == "二手" else 1
                    )
                    new_brand = st.text_input("品牌 / 出版社", value=data.get("brand", ""))
                    new_isbn = st.text_input("國際條碼 (GTIN / ISBN)", value=data.get("isbn_or_barcode") or "")
                with c2:
                    new_bsmi = st.text_input("BSMI 檢驗字號", value=data.get("bsmi_number") or "")
                    new_batch = st.text_input("BSMI 批號", value=data.get("bsmi_batch_number") or "")
                    dims = data.get("dimensions", {})
                    new_weight = st.number_input(
                        "包裹重量 (kg)",
                        min_value=0.01,
                        max_value=30.0,
                        value=float(dims.get("weight_kg", 0.5)),
                        step=0.05
                    )

                if st.button("💾 儲存修改並更新上方複製按鈕", type="primary", use_container_width=True):
                    data["shopee_title"] = new_title[:60]
                    data["shopee_description"] = new_desc
                    data["condition"] = new_cond
                    data["brand"] = new_brand
                    data["bsmi_number"] = new_bsmi or None
                    data["bsmi_batch_number"] = new_batch or None
                    data["isbn_or_barcode"] = new_isbn or None
                    data["dimensions"]["weight_kg"] = new_weight
                    data["pricing"]["suggested_standard_price"] = int(selected_price)
                    data["stock_quantity"] = selected_stock

                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    st.success("✅ 已更新！上方單手複製按鈕已同步為最新內容。")
                    st.rerun()
