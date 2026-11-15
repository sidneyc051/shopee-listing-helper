# agent_pipeline.py (v1.9 混傳防爆配額版：多商品混傳圖片自動壓縮 768px + 每件商品間隔 8 秒節流冷卻 + 遇每分鐘限流自動退避重試)
import os
import json
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional
from PIL import Image, ImageOps
from google import genai
from google.genai import types

from models import BatchGroupingResult, ImageGroup, ShopeeListingSchema
from chart_generator import generate_size_chart_image

SAFE_STANDARD_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-1.5-flash",
]
SINGLE_ITEM_IMAGE_SIDE = 1024
MULTI_ITEM_IMAGE_SIDE = 768
BATCH_COOLDOWN_SECONDS = 8.0

_client: Optional[genai.Client] = None
_active_model: Optional[str] = None
_discovered_models: Optional[List[str]] = None


def get_client() -> genai.Client:
    """Lazy Initialization：初始化 Gemini Client"""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise EnvironmentError("找不到環境變數 GEMINI_API_KEY，請先確認 Streamlit Secrets 或側邊欄設定。")
        _client = genai.Client(api_key=api_key)
    return _client


def _is_safe_flash_model(name: str) -> bool:
    """嚴格白名單過濾：只允許標準 gemini-x.x-flash / lite 模型，封鎖 nano-banana / image / exp 等非標準模型"""
    lower_n = name.lower()
    blocked_keywords = [
        "image",
        "banana",
        "embedding",
        "imagen",
        "veo",
        "tts",
        "audio",
        "live",
        "thinking",
        "learnlm",
        "aqa",
        "bisheng",
        "robotics",
        "computer-use",
        "deep-research",
    ]
    if any(k in lower_n for k in blocked_keywords):
        return False
    return lower_n.startswith("gemini-") and ("flash" in lower_n or "pro" in lower_n)


def discover_available_models() -> List[str]:
    """向 Google API 動態查詢此 API Key 實際支援的標準 Gemini Flash 模型"""
    global _discovered_models
    if _discovered_models is not None:
        return _discovered_models

    client = get_client()
    found = []
    try:
        for m in client.models.list():
            name = getattr(m, "name", "") or ""
            if name.startswith("models/"):
                name = name.replace("models/", "", 1)
            if _is_safe_flash_model(name):
                found.append(name)

        def model_priority(m_name: str):
            ln = m_name.lower()
            if ln == "gemini-2.5-flash":
                return (0, ln)
            if ln == "gemini-2.0-flash":
                return (1, ln)
            if ln == "gemini-2.5-flash-lite":
                return (2, ln)
            if "flash" in ln and "preview" not in ln and "exp" not in ln:
                return (3, ln)
            if "flash" in ln:
                return (4, ln)
            return (5, ln)

        found.sort(key=model_priority)
        _discovered_models = found
    except Exception:
        _discovered_models = []
    return _discovered_models


def generate_with_fallback(
    contents,
    config: types.GenerateContentConfig,
    preferred_model: Optional[str] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
    stage_label: str = "AI 運算中",
    pct: int = 30,
):
    """依序嘗試標準高配額模型，遇每分鐘流量限制 (429 PerMinute) 自動冷卻重試或切換備援模型"""
    global _active_model
    client = get_client()

    models_to_try = []
    if _active_model and _is_safe_flash_model(_active_model):
        models_to_try.append(_active_model)
    for m in SAFE_STANDARD_MODELS:
        if m not in models_to_try:
            models_to_try.append(m)
    if preferred_model and _is_safe_flash_model(preferred_model) and preferred_model not in models_to_try:
        models_to_try.append(preferred_model)
    for m in discover_available_models():
        if m not in models_to_try:
            models_to_try.append(m)

    error_summary_list = []
    for model_name in models_to_try:
        for attempt in range(2):
            try:
                if progress_cb:
                    progress_cb(f"🤖 {stage_label} (使用模型: `{model_name}`)...", pct)
                resp = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config,
                )
                _active_model = model_name
                return resp
            except Exception as e:
                err_str = str(e)
                short_reason = err_str[:140].replace("\n", " ")

                if any(k in err_str for k in ["404", "NOT_FOUND", "no longer available", "not found", "not supported"]):
                    error_summary_list.append(f"• `{model_name}`: {short_reason}")
                    break
                elif any(k in err_str for k in ["429", "RESOURCE_EXHAUSTED"]):
                    if "PerMinute" in err_str and attempt == 0:
                        if progress_cb:
                            progress_cb(f"⏳ 模型 `{model_name}` 達到每分鐘速率上限，自動冷卻 12 秒後重試...", pct)
                        time.sleep(12.0)
                        continue
                    error_summary_list.append(f"• `{model_name}`: {short_reason}")
                    if progress_cb:
                        progress_cb(f"⚠️ 模型 `{model_name}` 額度受限，切換下一個備援模型...", pct)
                    time.sleep(1.5)
                    break
                else:
                    raise e

    detail_report = "\n".join(error_summary_list[:5])
    raise RuntimeError(
        f"所有標準模型皆暫時無法呼叫！各模型實際回傳原因如下：\n{detail_report}\n\n"
        f"💡 排查建議：\n"
        f"1. 若看到 `limit: 0`，代表該 Google 帳號/專案的免費額度被設為 0，請至 Google AI Studio 確認專案或建立一組新 API Key。\n"
        f"2. 若看到 `PerMinute`，代表單次混傳圖片過多超過每分鐘 Token 上限，請稍候 60 秒再試。"
    )


def load_and_preprocess_image(img_path: str, max_side: int = SINGLE_ITEM_IMAGE_SIDE) -> Image.Image:
    """讀取手機照片，自動校正 EXIF 旋轉方向並依單件/混傳模式縮圖"""
    img = Image.open(img_path)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
    return img


def fast_single_item_research_and_build(
    valid_files: List[str],
    image_dir: str,
    general_note: str = "",
    preferred_model: Optional[str] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
    default_stock: int = 0,
) -> ShopeeListingSchema:
    """單一商品二合一極速通道"""
    t0 = time.time()
    if progress_cb:
        progress_cb(f"🖼️ [1/3] 正在壓縮並讀取 {len(valid_files)} 張商品照片 (上限 1024px)...", 15)

    images: List[Image.Image] = [
        load_and_preprocess_image(os.path.join(image_dir, fname), max_side=SINGLE_ITEM_IMAGE_SIDE)
        for fname in valid_files
    ]

    if progress_cb:
        progress_cb("🌐 [2/3] 正在進行圖片銘牌/版權頁辨識 ＆ Google 全網比價與查規格...", 40)

    search_prompt = f"""
    這 {len(valid_files)} 張照片全部屬於「同一個商品」的不同角度（檔名：{valid_files}）。
    賣家補充備註：{general_note or '無'}

    請先仔細檢視所有照片中的文字細節（品牌/出版社、商品名稱、型號/貨號、書籍 ISBN、BSMI 檢驗字號與批號、原定價、特價貼紙、尺寸標示、適用年齡），接著使用 Google Search 精準查詢台灣市場資訊並簡潔列出：
    1. 視覺提取結果：品牌/出版社、完整品名、型號/貨號、ISBN/條碼、照片上的 BSMI 字號(R/M/T/D開頭)與批號、新舊狀況。
    2. 官方實體規格：長 x 寬 x 高 (cm)、重量 (kg)，是否符合超商取貨限制（最長邊<=45cm，三邊和<=105cm，重量<=5kg）。
    3. 台灣全新與二手價格行情（台幣）：原定價、目前主流電商新品價、以及蝦皮/旋轉/讀冊二手市場實際行情區間（排除配件價），並給出快速出清價、一般行情價、近全新高價。
    4. 若照片未拍到 BSMI 但該商品屬於家電/3C/玩具/童書，請查出其 BSMI 字號。
    """

    search_response = generate_with_fallback(
        contents=[*images, search_prompt],
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
        ),
        preferred_model=preferred_model,
        progress_cb=progress_cb,
        stage_label="[2/3] 視覺辨識 + 全網查價檢索中",
        pct=45,
    )
    research_report = search_response.text
    elapsed_search = round(time.time() - t0, 1)

    if progress_cb:
        progress_cb(f"✍️ [3/3] 查價完成 (耗時 {elapsed_search}s)！正在轉換為蝦皮 60 字標題與結構化欄位...", 80)

    format_prompt = f"""
    請根據以下【視覺辨識與全網查價報告】，輸出符合蝦皮賣家中心規範的 JSON 格式。

    【重要規則】
    1. `group_id` 固定填 `"item_01"`，`image_filenames` 固定填 `{json.dumps(valid_files)}`。
    2. `shopee_title` 蝦皮商品標題必須嚴格控制在 **60 個字元以內**，將品牌/出版社、核心品名、型號、規格放在最前面。
    3. `stock_quantity` 請填入 `{default_stock}`（若為 0 代表先放入蝦皮「已售完」分頁供賣家安全微調）。
    4. 若商品為衣服、鞋子、童鞋等需尺寸表分類，`requires_size_chart` 設為 true 並提供 `size_chart_rows`。

    【視覺辨識與全網查價報告】
    {research_report}
    """

    structured_response = generate_with_fallback(
        contents=format_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ShopeeListingSchema,
            temperature=0.1,
        ),
        preferred_model=preferred_model,
        progress_cb=progress_cb,
        stage_label="[3/3] 產出蝦皮 JSON 結構中",
        pct=85,
    )
    listing = ShopeeListingSchema.model_validate_json(structured_response.text)
    listing.stock_quantity = default_stock
    listing.publish_status = "sold_out_draft" if default_stock == 0 else "active"
    return listing


def step1_group_and_extract(
    image_dir: str,
    user_notes: Dict[str, str],
    target_files: Optional[List[str]] = None,
    force_single_item: bool = False,
    preferred_model: Optional[str] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
) -> BatchGroupingResult:
    """多商品混傳模式的第一階段：圖片壓縮至 768px 節省 Token 並自動智慧分群"""
    all_dir_files = sorted([
        f for f in os.listdir(image_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ])
    valid_files = [f for f in all_dir_files if (not target_files or f in target_files)]

    if not valid_files:
        raise ValueError(f"在 {image_dir} 中找不到任何符合條件的圖片檔案。")

    contents = []
    for fname in valid_files:
        img_path = os.path.join(image_dir, fname)
        img = load_and_preprocess_image(img_path, max_side=MULTI_ITEM_IMAGE_SIDE)
        note = user_notes.get(fname, "無特別備註")
        contents.append(f"【圖片檔名: {fname} | 賣家備註: {note}】")
        contents.append(img)

    prompt = """
    你是一位專業的台灣電商上架視覺分析 Agent。
    請檢視以上所有上傳的照片與檔名，執行以下任務：
    1. 【智慧跨角度合併分群】：賣家拍攝同一個商品時，會連續拍攝正面、背面、側面、內頁或標籤特寫。只要材質、顏色、主題或連號檔名屬於同一件商品的不同視角，請務必合併在同一個 group_id（如 item_01）！只有出現完全不同商品時才建立 item_02、item_03 等。
    2. 銘牌、條碼與版權頁提取：讀取品牌/出版社、型號/貨號/ISBN、BSMI 字號與批號、原定價、特價貼紙、適用年齡。
    """
    contents.append(prompt)

    response = generate_with_fallback(
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=BatchGroupingResult,
            temperature=0.1,
        ),
        preferred_model=preferred_model,
        progress_cb=progress_cb,
        stage_label="多商品視覺分群中 (768px 省流量模式)",
        pct=20,
    )
    result = BatchGroupingResult.model_validate_json(response.text)

    valid_set = set(valid_files)
    for group in result.groups:
        group.image_filenames = [f for f in group.image_filenames if f in valid_set]

    return result


def step2_research_and_build_json(
    group: ImageGroup,
    image_dir: str,
    general_note: str = "",
    preferred_model: Optional[str] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
    default_stock: int = 0,
    base_pct: int = 40,
) -> ShopeeListingSchema:
    """多商品混傳模式的第二階段：針對分群後的單一商品查價（使用 768px 圖片避免超過每分鐘 Token 上限）"""
    images: List[Image.Image] = [
        load_and_preprocess_image(os.path.join(image_dir, fname), max_side=MULTI_ITEM_IMAGE_SIDE)
        for fname in group.image_filenames
    ]

    search_prompt = f"""
    請根據這組商品的照片與第一階段提取結果，使用 Google Search 搜尋台灣市場資料：
    - 品牌/出版社：{group.detected_brand}
    - 型號/ISBN/貨號：{group.detected_model}
    - 照片上的 BSMI：{group.detected_bsmi_from_photo} (批號：{group.detected_bsmi_batch_number})
    - 外觀特徵：{group.visual_features}
    - 賣家補充：{general_note}

    請簡潔列出：
    1. 官方長寬高 (cm) 與重量 (kg)，是否可超商取貨。
    2. 原定價、台灣電商新品價、以及蝦皮/旋轉/讀冊二手市場實際價格區間。
    3. BSMI 檢驗字號與適用年齡。
    """
    search_response = generate_with_fallback(
        contents=[*images, search_prompt],
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
        ),
        preferred_model=preferred_model,
        progress_cb=progress_cb,
        stage_label=f"正在聯網查價 ({group.group_id})",
        pct=base_pct,
    )
    research_report = search_response.text

    format_prompt = f"""
    請整合以下資訊，輸出符合蝦皮賣家中心規範的 JSON 格式。
    1. `shopee_title` 嚴格控制在 60 字元內。
    2. `group_id` 填 `{group.group_id}`，`image_filenames` 填 `{json.dumps(group.image_filenames)}`。
    3. `stock_quantity` 填 `{default_stock}`。

    【第一階段視覺提取】
    {group.model_dump_json(indent=2)}

    【第二階段聯網查價報告】
    {research_report}
    """
    structured_response = generate_with_fallback(
        contents=format_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ShopeeListingSchema,
            temperature=0.1,
        ),
        preferred_model=preferred_model,
        progress_cb=progress_cb,
        stage_label=f"正在產生蝦皮欄位 ({group.group_id})",
        pct=min(95, base_pct + 10),
    )
    listing = ShopeeListingSchema.model_validate_json(structured_response.text)
    listing.stock_quantity = default_stock
    listing.publish_status = "sold_out_draft" if default_stock == 0 else "active"
    return listing


def run_pipeline(
    image_dir: str,
    output_dir: str,
    user_notes: Dict[str, str] = None,
    target_files: Optional[List[str]] = None,
    force_single_item: bool = False,
    preferred_model: Optional[str] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
    default_stock: int = 0,
):
    user_notes = user_notes or {}
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    all_dir_files = sorted([
        f for f in os.listdir(image_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ])
    valid_files = [f for f in all_dir_files if (not target_files or f in target_files)]
    if not valid_files:
        raise ValueError("找不到任何可分析的商品圖片！")

    if force_single_item:
        combined_notes = " / ".join(list({user_notes.get(f, "") for f in valid_files if user_notes.get(f, "")}))
        listing_data = fast_single_item_research_and_build(
            valid_files=valid_files,
            image_dir=image_dir,
            general_note=combined_notes,
            preferred_model=preferred_model,
            progress_cb=progress_cb,
            default_stock=default_stock,
        )
        item_out_dir = Path(output_dir) / "item_01"
        item_out_dir.mkdir(parents=True, exist_ok=True)

        if listing_data.requires_size_chart and listing_data.size_chart_rows:
            if progress_cb:
                progress_cb("📏 正在繪製白底黑字尺寸表圖片...", 92)
            chart_path = str(item_out_dir / "size_chart.png")
            generate_size_chart_image(
                rows=listing_data.size_chart_rows,
                output_path=chart_path,
                title=f"{listing_data.shopee_title[:18]} 尺寸表"
            )

        json_path = item_out_dir / "listing.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(listing_data.model_dump(), f, ensure_ascii=False, indent=2)

        if progress_cb:
            progress_cb("✅ 分析與寫入完成！", 100)
        return

    # 多商品混傳模式：先壓縮至 768px 節省 Token 並智慧分群
    if progress_cb:
        progress_cb(f"🔍 [Step 1] 正在將 {len(valid_files)} 張混傳照片壓縮至 768px 並自動分群...", 15)

    grouping_result = step1_group_and_extract(
        image_dir=image_dir,
        user_notes=user_notes,
        target_files=valid_files,
        force_single_item=False,
        preferred_model=preferred_model,
        progress_cb=progress_cb,
    )

    total_groups = max(1, len(grouping_result.groups))
    if progress_cb:
        progress_cb(f"📦 分群完成！共辨識出 {total_groups} 件商品，開始排隊聯網查價...", 25)

    for idx, group in enumerate(grouping_result.groups):
        # 多件商品之間強制冷卻 8 秒，避免連續觸發免費版每分鐘請求/Token 上限 (429)
        if idx > 0:
            if progress_cb:
                progress_cb(
                    f"⏳ 為避免觸發免費版每分鐘配額上限，自動冷卻 {int(BATCH_COOLDOWN_SECONDS)} 秒後調查第 {idx+1}/{total_groups} 件商品...",
                    30 + int((idx / total_groups) * 60),
                )
            time.sleep(BATCH_COOLDOWN_SECONDS)

        base_pct = 30 + int((idx / total_groups) * 60)
        if progress_cb:
            progress_cb(
                f"🌐 [Step 2] 正在調查第 {idx+1}/{total_groups} 件商品 [{group.group_id}] ({group.detected_brand or ''} {group.detected_model or ''})...",
                base_pct,
            )
        combined_notes = " / ".join(list({user_notes.get(f, "") for f in group.image_filenames if user_notes.get(f, "")}))
        listing_data = step2_research_and_build_json(
            group=group,
            image_dir=image_dir,
            general_note=combined_notes,
            preferred_model=preferred_model,
            progress_cb=progress_cb,
            default_stock=default_stock,
            base_pct=base_pct,
        )

        item_out_dir = Path(output_dir) / group.group_id
        item_out_dir.mkdir(parents=True, exist_ok=True)

        if listing_data.requires_size_chart and listing_data.size_chart_rows:
            chart_path = str(item_out_dir / "size_chart.png")
            generate_size_chart_image(
                rows=listing_data.size_chart_rows,
                output_path=chart_path,
                title=f"{listing_data.shopee_title[:18]} 尺寸表"
            )

        json_path = item_out_dir / "listing.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(listing_data.model_dump(), f, ensure_ascii=False, indent=2)

    if progress_cb:
        progress_cb(f"✅ 全部 {total_groups} 件商品分析完成！", 100)
