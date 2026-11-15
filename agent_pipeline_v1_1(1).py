# agent_pipeline_v1_1.py (v1.2 修正版：修復 404 模型代號並強化多圖強效分群)
import os
import json
from pathlib import Path
from typing import Dict, List, Optional
from PIL import Image, ImageOps
from google import genai
from google.genai import types

from models_v1_1 import BatchGroupingResult, ImageGroup, ShopeeListingSchema
from chart_generator_v1_1 import generate_size_chart_image

# 修正為目前最穩定支援的 Flash 模型代號
MODEL_ID = "gemini-2.5-flash"
MAX_IMAGE_SIDE = 1600  # 限制手機高畫素照片最大邊長

_client: Optional[genai.Client] = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError("找不到環境變數 GEMINI_API_KEY，請先設定後再執行。")
        _client = genai.Client(api_key=api_key)
    return _client


def load_and_preprocess_image(img_path: str) -> Image.Image:
    img = Image.open(img_path)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
    return img


def step1_group_and_extract(image_dir: str, user_notes: Dict[str, str]) -> BatchGroupingResult:
    """
    第一階段：強化版多圖強效分群（將同一商品的正面、背面、條碼、說明書強制歸為同一個 group_id）
    """
    client = get_client()
    contents = []
    valid_files = sorted([
        f for f in os.listdir(image_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ])

    if not valid_files:
        raise ValueError(f"在 {image_dir} 中找不到任何圖片檔案。")

    for fname in valid_files:
        img_path = os.path.join(image_dir, fname)
        img = load_and_preprocess_image(img_path)
        note = user_notes.get(fname, "無特別備註")
        contents.append(f"【圖片檔名: {fname} | 賣家備註: {note}】")
        contents.append(img)

    prompt = """
    你是一位極度嚴謹的台灣電商上架視覺分析專家 Agent。
    請檢視以上所有上傳的照片與檔名，執行以下任務：
    1. 【嚴格強效分群】：「同一個商品」的所有不同角度照片（例如正面封面照、背面版權頁照、條碼 ISBN 照、機身貼紙照、外盒照）**絕對必須**歸類在同一個 `group_id`（例如 item_01, item_02）。
       - 絕對不可將同一本書或同一個機器的「正面」與「背面/條碼」拆開變成不同的商品群組！
       - 請透過書名、ISBN、型號、顏色與外觀特徵精準判斷是否為同一件物品。
    2. 銘牌、條碼與版權頁提取：
       - 仔細讀取照片中的品牌或出版社（如 TESCOM、世一文化）。
       - 讀取型號、貨號或書籍 ISBN（如 IPM850、CF10041、ISBN 978-986-429-216-5）。
       - 讀取台灣 BSMI 檢驗字號與批號。
       - 讀取照片上印製的原定價、特價貼紙與適用年齡。
    3. 結合賣家備註，詳細記錄外觀特徵與新舊狀況。
    """
    contents.append(prompt)

    response = client.models.generate_content(
        model=MODEL_ID,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=BatchGroupingResult,
            temperature=0.0,  # 設為 0 以確保分群判定絕對穩定
        ),
    )
    result = BatchGroupingResult.model_validate_json(response.text)

    valid_set = set(valid_files)
    for group in result.groups:
        group.image_filenames = [f for f in group.image_filenames if f in valid_set]

    return result


def step2_research_and_build_json(
    group: ImageGroup,
    image_dir: str,
    general_note: str = ""
) -> ShopeeListingSchema:
    client = get_client()
    images: List[Image.Image] = [
        load_and_preprocess_image(os.path.join(image_dir, fname))
        for fname in group.image_filenames
    ]

    search_prompt = f"""
    請根據這組商品的照片與第一階段視覺提取結果，使用 Google Search 搜尋台灣市場資料：
    - 品牌/出版社：{group.detected_brand}
    - 型號/ISBN/貨號：{group.detected_model}
    - 外觀與特徵：{group.visual_features}
    - 賣家補充說明：{general_note}

    請聯網查詢並詳細列出以下台灣市場真實數據：
    1. 官方實體規格：長、寬、高/厚度 (cm)、重量 (kg)、頁數或材質，並驗證是否可超商取貨。
    2. 全新與二手價格行情（台幣）：原定價、主流電商新品價、二手拍賣行情價區間。
    3. BSMI 檢驗字號與適用年齡。
    """
    search_response = client.models.generate_content(
        model=MODEL_ID,
        contents=[*images, search_prompt],
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
        ),
    )
    research_report = search_response.text

    format_prompt = f"""
    請將以下資訊整合，輸出為符合蝦皮賣家中心規範的 JSON 格式：
    1. `shopee_title` 蝦皮商品標題必須嚴格控制在 **60 個字元以內**。
    2. `group_id` 請填寫 `{group.group_id}`，`image_filenames` 請原封不動填入 `{json.dumps(group.image_filenames)}`。
    3. 若照片已拍到 BSMI 字號與批號，請務必填入。

    【第一階段視覺提取資訊】
    {group.model_dump_json(indent=2)}

    【第二階段聯網調查報告】
    {research_report}
    """
    structured_response = client.models.generate_content(
        model=MODEL_ID,
        contents=format_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ShopeeListingSchema,
            temperature=0.1,
        ),
    )
    return ShopeeListingSchema.model_validate_json(structured_response.text)


def run_pipeline(image_dir: str, output_dir: str, user_notes: Dict[str, str] = None):
    user_notes = user_notes or {}
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print("🔍 [Step 1] 正在分析照片並進行多商品自動分群與銘牌/版權頁辨識...")
    grouping_result = step1_group_and_extract(image_dir, user_notes)
    print(f"✅ 分群完成，共辨識出 {len(grouping_result.groups)} 件獨立商品。")

    for group in grouping_result.groups:
        print(f"\n🌐 [Step 2] 正在聯網調查商品 [{group.group_id}] ({group.detected_brand} {group.detected_model})...")
        combined_notes = " / ".join([user_notes.get(f, "") for f in group.image_filenames if f in user_notes])
        listing_data = step2_research_and_build_json(group, image_dir, combined_notes)

        item_out_dir = Path(output_dir) / group.group_id
        item_out_dir.mkdir(parents=True, exist_ok=True)

        if listing_data.requires_size_chart and listing_data.size_chart_rows:
            chart_path = str(item_out_dir / "size_chart.png")
            generate_size_chart_image(
                rows=listing_data.size_chart_rows,
                output_path=chart_path,
                title=f"{listing_data.shopee_title[:18]} 尺寸表"
            )
            print(f"📏 已自動生成尺寸表圖片：{chart_path}")

        json_path = item_out_dir / "listing.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(listing_data.model_dump(), f, ensure_ascii=False, indent=2)
        print(f"💾 已輸出蝦皮上架結構化資料（標題長度 {len(listing_data.shopee_title)} 字元）：{json_path}")
