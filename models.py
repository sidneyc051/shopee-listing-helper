# models_v1_1.py (v1.6 升級版：新增 stock_quantity 與 publish_status 支援先存「已售完 (庫存=0)」安全審核模式)
import re
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

class ImageGroup(BaseModel):
    group_id: str = Field(description="商品分群編號，例如 item_01")
    image_filenames: List[str] = Field(description="屬於此商品的圖片檔名清單")
    detected_brand: Optional[str] = Field(default=None, description="從外觀或標籤辨識出的品牌或出版社（如 TESCOM、世一文化）")
    detected_model: Optional[str] = Field(default=None, description="從機身銘牌、外盒或書背辨識出的型號、貨號或 ISBN（如 IPM850、CF10041、978-986-429-216-5）")
    detected_bsmi_from_photo: Optional[str] = Field(default=None, description="照片標籤上直接拍到的 BSMI 檢驗字號（如 M63042、R31310）")
    detected_bsmi_batch_number: Optional[str] = Field(default=None, description="照片標籤上拍到的 BSMI 批號（如 1705005）")
    visual_features: str = Field(description="外觀特徵、顏色、配件、定價貼紙、適用年齡標示與新舊狀況觀察")

class BatchGroupingResult(BaseModel):
    groups: List[ImageGroup]

class DimensionsAndLogistics(BaseModel):
    length_cm: float = Field(description="預估或官方商品長度(公分)")
    width_cm: float = Field(description="預估或官方商品寬度(公分)")
    height_cm: float = Field(description="預估或官方商品高度/厚度(公分)")
    weight_kg: float = Field(description="預估或官方商品含包裝重量(公斤)")
    can_ship_convenience_store: bool = Field(
        description="是否符合超商取貨限制（最長邊小於等於45cm，三邊總和小於等於105cm，重量小於等於5kg）"
    )

class PricingAnalysis(BaseModel):
    original_list_price_twd: Optional[int] = Field(default=None, description="商品標籤或書背印製的原定價(台幣)，例如 720")
    new_market_price_twd: Optional[int] = Field(default=None, description="全新品目前電商或特價貼紙售價(台幣)，例如 399")
    used_price_min_twd: Optional[int] = Field(default=None, description="二手市場最低行情價(台幣)")
    used_price_max_twd: Optional[int] = Field(default=None, description="二手市場最高行情價(台幣)")
    suggested_quick_sale_price: int = Field(description="建議快速出清價（低於二手均價約15%）")
    suggested_standard_price: int = Field(description="建議一般行情售價")
    suggested_high_price: int = Field(description="建議近全新高價")
    pricing_reference_summary: str = Field(description="比價來源與行情簡述")

class SizeChartRow(BaseModel):
    size_label: str = Field(description="尺碼標示，例如 M號、中童、或單一尺寸")
    measurement_1: str = Field(description="關鍵尺寸1，例如 適合腳長 18cm 以內 或 衣長 45cm")
    measurement_2: str = Field(description="關鍵尺寸2，例如 鞋內長 19cm 或 胸寬 38cm")
    recommended_age_or_height: str = Field(description="適用年齡或身高範圍，例如 3-5歲 / 100-110cm")

class ShopeeListingSchema(BaseModel):
    group_id: str
    image_filenames: List[str]
    shopee_title: str = Field(
        max_length=60,
        description="蝦皮 SEO 商品標題（嚴格限制 60 字元以內，含品牌/出版社、商品名稱、型號/系列、核心特色與規格）"
    )
    shopee_description: str = Field(description="完整蝦皮商品描述，含商品特色、實品狀況、詳細規格與寄送須知")
    suggested_category_path: List[str] = Field(description="建議蝦皮分類路徑，例如 ['書籍及雜誌期刊', '兒童圖書與教育', '兒童繪本與故事書']")
    condition: str = Field(description="全新 或 二手")
    brand: str = Field(description="品牌或出版社名稱，無品牌則填 自有品牌 或 無")
    model_number: Optional[str] = Field(default=None, description="商品型號或貨號（如 CF10041、IPM850）")
    isbn_or_barcode: Optional[str] = Field(default=None, description="書籍 ISBN 或商品國際條碼 EAN（如 9789864292165）")
    applicable_age_range: Optional[str] = Field(default=None, description="適用年齡範圍（如 3歲以上，婦幼、玩具、童書、童裝童鞋必填）")
    requires_bsmi: bool = Field(description="此分類在蝦皮是否需要或建議填寫 BSMI 檢驗字號（家電、3C、玩具、操作童書）")
    bsmi_number: Optional[str] = Field(default=None, description="查到的 BSMI 字號（R/M/T/D開頭），若無須填寫則為 null")
    bsmi_batch_number: Optional[str] = Field(default=None, description="BSMI 檢驗批號（如 1705005），玩具或操作童書常見")
    requires_size_chart: bool = Field(description="此分類是否屬於服飾、鞋類等需要上傳尺寸表圖片的商品")
    size_chart_rows: Optional[List[SizeChartRow]] = Field(default=None, description="若需要尺寸表，提供繪製表格用的列資料")
    dimensions: DimensionsAndLogistics
    pricing: PricingAnalysis
    stock_quantity: int = Field(
        default=0,
        description="商品數量（預設填 0，讓商品上架後自動進入『已售完』分頁安全暫存，待賣家微調確認後再改為 1 正式開賣）"
    )
    publish_status: str = Field(
        default="sold_out_draft",
        description="上架模式：sold_out_draft (數量0進入已售完區) / unlisted (儲存並下架) / active (數量1直接開賣)"
    )

    @field_validator("shopee_title")
    @classmethod
    def enforce_shopee_title_limit(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 60:
            return v[:60]
        return v

    @field_validator("bsmi_number")
    @classmethod
    def normalize_bsmi(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        v_clean = v.strip().upper()
        match = re.search(r"[RMTD]\d{5}", v_clean)
        return match.group(0) if match else v_clean
