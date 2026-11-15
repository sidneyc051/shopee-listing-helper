# chart_generator.py (v1.1 - 加入文字自動換行與動態列高，防止長文字穿出格線)
import textwrap
from PIL import Image, ImageDraw, ImageFont
from typing import List
from models_v1_1 import SizeChartRow


def _load_cjk_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        [
            "msjhbd.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        ]
        if bold
        else [
            "msjh.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except IOError:
            continue
    return ImageFont.load_default()


def generate_size_chart_image(rows: List[SizeChartRow], output_path: str, title: str = "商品尺寸參考表") -> str:
    font_title = _load_cjk_font(28, bold=True)
    font_header = _load_cjk_font(20, bold=True)
    font_cell = _load_cjk_font(18, bold=False)

    col_x = [40, 180, 390, 580, 760]
    headers = ["尺碼", "規格測量 1", "規格測量 2", "建議年齡 / 範圍"]
    max_chars_per_col = [7, 10, 9, 9]

    # 預先計算每一列自動換行後的文字與動態列高
    wrapped_rows = []
    row_heights = [60]  # 表頭高度 60px

    for row in rows:
        raw_cells = [row.size_label, row.measurement_1, row.measurement_2, row.recommended_age_or_height]
        wrapped_cells = []
        max_lines = 1
        for idx, text in enumerate(raw_cells):
            lines = textwrap.wrap(str(text), width=max_chars_per_col[idx]) or [""]
            wrapped_cells.append("\n".join(lines))
            max_lines = max(max_lines, len(lines))
        wrapped_rows.append(wrapped_cells)
        row_heights.append(max(60, 28 * max_lines + 20))

    width = 800
    start_y = 95
    height = start_y + sum(row_heights) + 45

    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # 繪製標題（限制長度避免超出畫布）
    draw.text((40, 30), title[:26], fill=(30, 30, 30), font=font_title)

    # 繪製表頭底色與文字
    draw.rectangle([col_x[0], start_y, col_x[-1], start_y + row_heights[0]], fill=(240, 242, 245))
    for i, header_text in enumerate(headers):
        draw.text((col_x[i] + 12, start_y + 18), header_text, fill=(20, 20, 20), font=font_header)

    # 繪製資料列與水平格線
    curr_y = start_y
    draw.line([(col_x[0], curr_y), (col_x[-1], curr_y)], fill=(200, 200, 200), width=2)
    curr_y += row_heights[0]
    draw.line([(col_x[0], curr_y), (col_x[-1], curr_y)], fill=(200, 200, 200), width=2)

    for r_idx, wrapped_cells in enumerate(wrapped_rows):
        r_h = row_heights[r_idx + 1]
        for c_idx, cell_text in enumerate(wrapped_cells):
            draw.multiline_text((col_x[c_idx] + 12, curr_y + 14), cell_text, fill=(50, 50, 50), font=font_cell, spacing=6)
        curr_y += r_h
        draw.line([(col_x[0], curr_y), (col_x[-1], curr_y)], fill=(200, 200, 200), width=2)

    # 繪製垂直格線
    for x in col_x:
        draw.line([(x, start_y), (x, curr_y)], fill=(200, 200, 200), width=2)

    img.save(output_path)
    return output_path
