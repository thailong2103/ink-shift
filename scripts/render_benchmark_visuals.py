import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGE_PATH = REPO_ROOT / "docs" / "vi" / "reports" / "images" / "benchmark_page.png"
REPORT_PATH = REPO_ROOT / "data" / "benchmark_real_report.json"
OUT_DIR = REPO_ROOT / "docs" / "vi" / "reports" / "images"
FONT_PATH = REPO_ROOT / "src" / "extension" / "assets" / "fonts" / "Itim-Regular.ttf"

def render_detection_visualization():
    with open(REPORT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    img = cv2.imread(str(IMAGE_PATH))
    h, w = img.shape[:2]

    # Overlay layer for translucent polygon masks
    overlay = img.copy()

    # Colors for 11 bubbles
    colors = [
        (0, 255, 0),    # Green
        (255, 100, 0),  # Blue
        (0, 200, 255),  # Yellow
        (255, 0, 200),  # Purple
        (0, 255, 255),  # Cyan
        (50, 150, 255), # Orange
        (200, 255, 0),  # Lime
        (0, 128, 255),  # Amber
        (255, 50, 50),  # Blue-violet
        (128, 255, 128),# Mint
        (255, 128, 255) # Pink
    ]

    # Process each block from local or cloud
    blocks = data["variants"]["openai_compat_qwen"]["blocks"]
    
    for idx, block in enumerate(blocks):
        color = colors[idx % len(colors)]
        box = block["box"] # [ymin, xmin, ymax, xmax] in 0..1000
        ymin = int(box[0] * h / 1000)
        xmin = int(box[1] * w / 1000)
        ymax = int(box[2] * h / 1000)
        xmax = int(box[3] * w / 1000)

        # Draw bounding box
        cv2.rectangle(img, (xmin, ymin), (xmax, ymax), color, 2)

        # Draw polygon mask if present
        if "polygon" in block and block["polygon"]:
            pts = []
            bw = xmax - xmin
            bh = ymax - ymin
            for p in block["polygon"]:
                px = int(xmin + p[0] * bw / 100)
                py = int(ymin + p[1] * bh / 100)
                pts.append([px, py])
            if len(pts) >= 3:
                cv2.fillPoly(overlay, [np.array(pts, dtype=np.int32)], color)

        # Label tag
        conf = block.get("confidence", 0.95)
        label = f"#{idx+1} ({conf*100:.0f}%)"
        cv2.rectangle(img, (xmin, max(0, ymin - 20)), (xmin + 85, max(0, ymin)), color, -1)
        cv2.putText(img, label, (xmin + 4, max(14, ymin - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)

    # Blend overlay with 30% opacity
    cv2.addWeighted(overlay, 0.35, img, 0.65, 0, img)

    out_file = OUT_DIR / "04_yolo_segmentation_visualized.png"
    cv2.imwrite(str(out_file), img)
    print(f"Saved detection visual to {out_file}")

def render_translation_overlay_visualization():
    with open(REPORT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Open base image with PIL
    base_img = Image.open(IMAGE_PATH).convert("RGBA")
    w, h = base_img.size

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    blocks = data["variants"]["openai_compat_qwen"]["blocks"]

    for block in blocks:
        box = block["box"]
        ymin = int(box[0] * h / 1000)
        xmin = int(box[1] * w / 1000)
        ymax = int(box[2] * h / 1000)
        xmax = int(box[3] * w / 1000)

        bw = xmax - xmin
        bh = ymax - ymin
        if bw <= 5 or bh <= 5:
            continue

        # Draw clean white bubble background
        draw.ellipse([xmin, ymin, xmax, ymax], fill=(255, 255, 255, 248), outline=(60, 60, 60, 200), width=1)

        # Fit Vietnamese text inside
        text = block.get("translated_text", "")
        if not text:
            continue

        # Simple text wrapping and auto-font sizing
        font_size = max(11, min(18, int(bh / 5)))
        try:
            font = ImageFont.truetype(str(FONT_PATH), font_size)
        except Exception:
            font = ImageFont.load_default()

        # Word wrap
        words = text.split()
        lines = []
        cur_line = []
        for word in words:
            test_line = " ".join(cur_line + [word])
            bbox = font.getbbox(test_line)
            line_w = bbox[2] - bbox[0]
            if line_w > bw * 0.82 and cur_line:
                lines.append(" ".join(cur_line))
                cur_line = [word]
            else:
                cur_line.append(word)
        if cur_line:
            lines.append(" ".join(cur_line))

        # Calculate vertical position to center lines
        line_height = int(font_size * 1.25)
        total_text_h = len(lines) * line_height
        start_y = ymin + (bh - total_text_h) // 2

        for i, line in enumerate(lines):
            bbox = font.getbbox(line)
            lw = bbox[2] - bbox[0]
            start_x = xmin + (bw - lw) // 2
            # Text stroke for high readability
            draw.text((start_x, start_y + i * line_height), line, fill=(20, 20, 20, 255), font=font)

    # Composite onto base image
    final_img = Image.alpha_composite(base_img, overlay).convert("RGB")
    out_file = OUT_DIR / "03_translated_overlay_visualized.png"
    final_img.save(str(out_file), quality=95)
    print(f"Saved translated overlay visual to {out_file}")

if __name__ == "__main__":
    render_detection_visualization()
    render_translation_overlay_visualization()
