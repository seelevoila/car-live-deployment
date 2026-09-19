from pathlib import Path
from zipfile import ZipFile
from lxml import etree

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "软件系统详细设计说明书实际项目模板 OCR conv.docx"
OUT = Path(__file__).resolve().parent / "qa_template_media"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    with ZipFile(TEMPLATE) as package:
        rels = etree.fromstring(package.read('word/_rels/document.xml.rels'))
        mapping = {x.get('Id'): 'word/' + x.get('Target') for x in rels}
        document = etree.fromstring(package.read('word/document.xml'))
        media = [mapping[x.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')]
                 for x in document.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}blip')]
        pages = []
        for index, name in enumerate(media, start=1):
            image_path = OUT / f"page-{index:02d}.png"
            image_path.write_bytes(package.read(name))
            image = Image.open(image_path).convert("RGB")
            page = image.copy()
            page.thumbnail((210, 300))
            thumb = Image.new("RGB", (230, 335), "white")
            thumb.paste(page, ((230 - page.width) // 2, 14))
            ImageDraw.Draw(thumb).text((8, 312), f"Page {index}", fill="black")
            pages.append(thumb)
            print(index, name, image.size)

    columns = 5
    rows = (len(pages) + columns - 1) // columns
    contact = Image.new("RGB", (columns * 230, rows * 335), (232, 232, 232))
    for index, page in enumerate(pages):
        contact.paste(page, ((index % columns) * 230, (index // columns) * 335))
    contact.save(OUT / "contact-sheet.png")


if __name__ == "__main__":
    main()
