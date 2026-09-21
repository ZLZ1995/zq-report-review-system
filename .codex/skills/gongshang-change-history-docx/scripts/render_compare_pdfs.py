from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw


WORK = Path("outputs/gongshang/human_compare")


def render(name):
    pdf = pdfium.PdfDocument(str(WORK / f"{name}.pdf"))
    out_dir = WORK / f"{name}_pages"
    out_dir.mkdir(exist_ok=True)
    paths = []
    for idx, page in enumerate(pdf, start=1):
        img = page.render(scale=0.7).to_pil().convert("RGB")
        path = out_dir / f"page_{idx:02d}.png"
        img.save(path)
        paths.append(path)
    return paths


def contact_sheet(name, paths):
    thumbs = []
    for p in paths:
        img = Image.open(p).convert("RGB")
        img.thumbnail((260, 370))
        canvas = Image.new("RGB", (280, 410), "white")
        canvas.paste(img, ((280 - img.width) // 2, 28))
        draw = ImageDraw.Draw(canvas)
        draw.text((12, 8), p.stem, fill=(0, 0, 0))
        thumbs.append(canvas)
    cols = 3
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 280, rows * 410), (240, 240, 240))
    for i, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((i % cols) * 280, (i // cols) * 410))
    out = WORK / f"{name}_contact.png"
    sheet.save(out)
    print(out)


def main():
    for name in ["base", "human"]:
        paths = render(name)
        contact_sheet(name, paths)
        print(name, "pages", len(paths))


if __name__ == "__main__":
    main()
