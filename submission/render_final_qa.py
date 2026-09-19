from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent / "2026-chongqing-ai-competition"
QA = Path(__file__).resolve().parent / "qa_final"
QA.mkdir(exist_ok=True)


def render(pdf_path: Path):
    target = QA / pdf_path.stem
    target.mkdir(exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    thumbs = []
    for i in range(len(pdf)):
        page = pdf[i]
        image = page.render(scale=1.35).to_pil().convert("RGB")
        png = target / f"page-{i + 1:02d}.png"
        image.save(png)
        thumb = image.copy()
        thumb.thumbnail((230, 325))
        canvas = Image.new("RGB", (250, 355), "white")
        canvas.paste(thumb, ((250 - thumb.width) // 2, 20))
        draw = ImageDraw.Draw(canvas)
        draw.text((10, 5), f"Page {i + 1}", fill="black")
        thumbs.append(canvas)
    cols = 4
    rows = (len(thumbs) + cols - 1) // cols
    contact = Image.new("RGB", (cols * 250, rows * 355), "#dddddd")
    for i, thumb in enumerate(thumbs):
        contact.paste(thumb, ((i % cols) * 250, (i // cols) * 355))
    contact.save(QA / f"{pdf_path.stem}-contact.png")
    return len(pdf)


if __name__ == "__main__":
    for pdf in sorted(ROOT.glob("*完整版.pdf")):
        print(pdf.name, render(pdf))
