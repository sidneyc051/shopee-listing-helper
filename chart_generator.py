# chart_generator.py (v1.6 正式唯一版 - 支援繁體中文自動換行與動態列高，已修正引用 models)
import textwrap
from PIL import Image, ImageDraw, ImageFont
from typing import List
from models import SizeChartRow


def _load_cjk_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        [
            "msjhbd.ttc",
            "C:/Windows/Fonts/msjhbd.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        ]
        if bold
        else [
            "msjh.ttc",
            "C:/Windows/Fonts/msjh.ttc",
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
    font_title = _load_cjk_font(26, bold=True)
    font_cell = _load_cjk_font(18, bold=False)

    col_x = [30, 170, 390, 610, 850]
    col_wrap_chars = [7, 11, 11, 12]
    headers = ["尺碼", "規格測量 1", "規格測量 2", "建議年齡 / 範圍"]

    wrapped_rows = []
    row_heights = [56]

    for r in rows:
        cells = [r.size_label, r.measurement_1, r.measurement_2, r.recommended_age_or_height]
        wrapped_cells = []
        max_lines = 1
        for idx, text in enumerate(cells):
            lines = textwrap.wrap(str(text), width=col_wrap_chars[idx]) or [""]
            wrapped_cells.append("\n".join(lines))
            max_lines = max(max_lines, len(lines))
        wrapped_rows.append(wrapped_cells)
        row_heights.append(max(56, max_lines * 26 + 24))

    width = 880
    start_y = 90
    total_table_h = sum(row_heights)
    height = start_y + total_table_h + 40

    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    safe_title = title[:28]
    draw.text((30, 28), safe_title, fill=(30, 30, 30), font=font_title)

    draw.rectangle([col_x[0], start_y, col_x[-1], start_y + row_heights[0]], fill=(240, 242, 245))
    for i, header_text in enumerate(headers):
        draw.text((col_x[i] + 12, start_y + 16), header_text, fill=(0, 0, 0), font=font_cell)

    curr_y = start_y + row_heights[0]
    for row_idx, wrapped_cells in enumerate(wrapped_rows):
        rh = row_heights[row_idx + 1]
        for col_idx, cell_text in enumerate(wrapped_cells):
            draw.multiline_text((col_x[col_idx] + 12, curr_y + 14), cell_text, fill=(50, 50, 50), font=font_cell, spacing=6)
        curr_y += rh

    y_cursor = start_y
    for rh in row_heights:
        draw.line([(col_x[0], y_cursor), (col_x[-1], y_cursor)], fill=(200, 200, 200), width=2)
        y_cursor += rh
    draw.line([(col_x[0], y_cursor), (col_x[-1], y_cursor)], fill=(200, 200, 200), width=2)

    for x in col_x:
        draw.line([(x, start_y), (x, start_y + total_table_h)], fill=(200, 200, 200), width=2)

    img.save(output_path)
    return output_path
