import cairosvg
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import sys

W, H = 1200, 630
TEXT_X = 735
MAX_W = W - TEXT_X - 50      # text column width
QUOTE_TOP = 255              # where the quote starts
NAME_Y = 410                 # fixed: name never moves
QUOTE_BOTTOM = NAME_Y - 25   # quote must end above this

def font(size, bold=False):
    names = (["Inter-Bold.ttf", "/system/fonts/Roboto-Bold.ttf", "DejaVuSans-Bold.ttf"] if bold
             else ["Inter-Regular.ttf", "/system/fonts/Roboto-Regular.ttf", "DejaVuSans.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            pass
    return ImageFont.load_default()

def wrap(text, f, max_w):
    lines, cur = [], ""
    for word in text.split():
        test = (cur + " " + word).strip()
        if f.getlength(test) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines

def fit_quote(text, max_size=50, min_size=16):
    for size in range(max_size, min_size - 1, -1):
        f = font(size, True)
        lines = wrap(text, f, MAX_W)
        lh = int(size * 1.35)
        widest = max(f.getlength(l) for l in lines)
        if len(lines) * lh <= QUOTE_BOTTOM - QUOTE_TOP and widest <= MAX_W:
            return f, lines, lh
    return f, lines, lh  # smallest size, best effort

def make(img_path, quote, name, handle, out="card.png"):
    card = Image.new("RGB", (W, H), (10, 10, 12))

    # left art: keeps original colors, cover-fit, fades into dark bg
    if img_path.lower().endswith(".svg"):
        png_data = cairosvg.svg2png(url=img_path)
        art = Image.open(BytesIO(png_data)).convert("RGB")
    else:
        art = Image.open(img_path).convert("RGB")
    aw = 700
    s = max(aw / art.width, H / art.height)
    art = art.resize((int(art.width * s), int(art.height * s)))
    art = art.crop((0, 0, aw, H))

    mask = Image.new("L", (aw, H))
    md = ImageDraw.Draw(mask)
    for x in range(aw):
        a = 255 if x < 320 else max(0, int(255 * (1 - (x - 320) / 360)))
        md.line([(x, 0), (x, H)], fill=a)
    card.paste(art, (0, 0), mask)

    d = ImageDraw.Draw(card)
    d.text((TEXT_X, 150), "\u201c", font=font(110, True), fill=(70, 70, 75))

    # quote: auto-shrinks to fit above the name
    f, lines, lh = fit_quote(quote)
    y = QUOTE_TOP
    for line in lines:
        d.text((TEXT_X, y), line, font=f, fill="white")
        y += lh

    # name + handle: fixed position
    d.line([(TEXT_X, NAME_Y + 17), (TEXT_X + 22, NAME_Y + 17)], fill=(90, 90, 95), width=2)
    d.text((TEXT_X + 38, NAME_Y), name, font=font(28, True), fill="white")
    d.text((TEXT_X, NAME_Y + 42), handle, font=font(22), fill=(130, 130, 135))

    card.save(out)

if __name__ == "__main__":
    make(*sys.argv[1:5])
