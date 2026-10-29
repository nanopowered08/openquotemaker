"""
OpenQuoteMaker

usage:  python app.py <art.png|svg> "<quote>" "<name>" "<handle>" [out.png]

Quote syntax:
    **bold**   *italic*   ***bold italic***   ~~strikethrough~~   __underline__
    \\n  (or a real newline) = line break      \\* \\~ \\_ \\\\ = literal characters
    pass "-" as the quote to read it from stdin (handy for multi-line quotes)
"""
import re
import sys
from functools import lru_cache
from io import BytesIO

import cairosvg
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
TEXT_X = 735
MAX_W = W - TEXT_X - 50      # text column width
QUOTE_TOP = 230              # where the quote starts
NAME_Y = 470                 # fixed: name never moves
QUOTE_BOTTOM = NAME_Y - 25   # quote must end above this
QUOTE_MARK_Y = QUOTE_TOP - 105

# (bold, italic) -> font files to try, in order. Base text is Medium so that
# **bold** is actually visible against it.
FONT_FILES = {
    (False, False): ["Inter-Medium.ttf", "Inter-Regular.ttf",
                     "/system/fonts/Roboto-Medium.ttf", "/system/fonts/Roboto-Regular.ttf",
                     "DejaVuSans.ttf"],
    (True, False):  ["Inter-Bold.ttf", "/system/fonts/Roboto-Bold.ttf", "DejaVuSans-Bold.ttf"],
    (False, True):  ["Inter-MediumItalic.ttf", "Inter-Italic.ttf",
                     "/system/fonts/Roboto-MediumItalic.ttf", "/system/fonts/Roboto-Italic.ttf",
                     "DejaVuSans-Oblique.ttf"],
    (True, True):   ["Inter-BoldItalic.ttf", "/system/fonts/Roboto-BoldItalic.ttf",
                     "DejaVuSans-BoldOblique.ttf"],
}

# style = (bold, italic, strike, underline)
PLAIN = (False, False, False, False)


@lru_cache(maxsize=None)
def font(size, bold=False, italic=False):
    for n in FONT_FILES[(bold, italic)]:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            pass
    if italic:  # no italic font installed: fall back to upright
        return font(size, bold, False)
    try:
        return ImageFont.load_default(size)
    except TypeError:  # old Pillow
        return ImageFont.load_default()


def pfont(size, st):
    return font(size, st[0], st[1])


# ---------- parsing ----------

MARKERS = [("**", 0), ("~~", 2), ("__", 3), ("*", 1)]  # (marker, style index)


def parse(text):
    """text -> tokens: ("word", [(str, style), ...]) | ("space", style) | ("nl", None)"""
    text = text.replace("\\n", "\n")

    # 1) split into (string, style) segments by toggling on markers
    st = [False] * 4
    segs, buf, i = [], "", 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] in "*~_\\":
            buf += text[i + 1]
            i += 2
            continue
        for m, idx in MARKERS:
            if text.startswith(m, i):
                if buf:
                    segs.append((buf, tuple(st)))
                    buf = ""
                st[idx] = not st[idx]
                i += len(m)
                break
        else:
            buf += text[i]
            i += 1
    if buf:
        segs.append((buf, tuple(st)))

    # 2) split segments into words / spaces / newlines (a word can span styles)
    tokens, word = [], []

    def flush():
        if word:
            tokens.append(("word", word[:]))
            word.clear()

    for seg, s in segs:
        for m in re.finditer(r"\n|[^\S\n]+|\S+", seg):
            t = m.group()
            if t == "\n":
                flush()
                tokens.append(("nl", None))
            elif t.isspace():
                flush()
                tokens.append(("space", s))
            else:
                word.append((t, s))
    flush()
    return tokens


# ---------- layout ----------

def merge(line):
    out = []
    for t, s in line:
        if out and out[-1][1] == s:
            out[-1] = (out[-1][0] + t, s)
        else:
            out.append((t, s))
    return out


def layout(tokens, size):
    """Wrap tokens into lines of styled pieces that fit MAX_W at this font size."""
    def cw(t, s):
        return pfont(size, s).getlength(t)

    lines, w, gap = [[]], 0, None
    for kind, val in tokens:
        if kind == "nl":
            lines.append([])
            w, gap = 0, None
        elif kind == "space":
            gap = val if lines[-1] else None
        else:
            ww = sum(cw(t, s) for t, s in val)
            sw = cw(" ", gap) if gap else 0
            if lines[-1] and w + sw + ww > MAX_W:
                lines.append([])
                w, sw, gap = 0, 0, None
            if ww > MAX_W:  # single word wider than the column: split it by characters
                for t, s in val:
                    for ch in t:
                        c = cw(ch, s)
                        if w + c > MAX_W and lines[-1]:
                            lines.append([])
                            w = 0
                        lines[-1].append((ch, s))
                        w += c
            else:
                if lines[-1] and gap:
                    lines[-1].append((" ", gap))
                    w += sw
                lines[-1].extend(val)
                w += ww
            gap = None
    while lines and not lines[-1]:
        lines.pop()
    return [merge(l) for l in lines]


def line_width(line, size):
    return sum(pfont(size, s).getlength(t) for t, s in line)


def ellipsize_line(line, size):
    line = merge(line)
    st = line[-1][1] if line else PLAIN
    ew = pfont(size, st).getlength("\u2026")
    while line and line_width(line, size) + ew > MAX_W:
        t, s = line[-1]
        t = t[:-1]
        if t:
            line[-1] = (t, s)
        else:
            line.pop()
    if line:
        line[-1] = (line[-1][0].rstrip(), line[-1][1])
    line.append(("\u2026", st))
    return line


def fit_quote(text, max_size=50, min_size=14):
    tokens = parse(text)
    avail = QUOTE_BOTTOM - QUOTE_TOP
    for size in range(max_size, min_size - 1, -1):
        lh = int(size * 1.35)
        lines = layout(tokens, size)
        if len(lines) * lh <= avail:
            return size, lines, lh
    # still too long at the smallest size: cut it off with an ellipsis
    size = min_size
    lh = int(size * 1.35)
    lines = layout(tokens, size)[: max(1, avail // lh)]
    lines[-1] = ellipsize_line(lines[-1], size)
    print("warning: quote too long, truncated", file=sys.stderr)
    return size, lines, lh


def ellipsize(text, f, max_w):
    if f.getlength(text) <= max_w:
        return text
    while text and f.getlength(text + "\u2026") > max_w:
        text = text[:-1]
    return text.rstrip() + "\u2026"


# ---------- drawing ----------

def draw_line(d, x, baseline, pieces, size, fill="white"):
    lw = max(1, size // 16)
    for t, s in pieces:
        f = pfont(size, s)
        d.text((x, baseline), t, font=f, fill=fill, anchor="ls")
        w = f.getlength(t)
        if s[2]:  # strikethrough
            y = baseline - int(size * 0.3)
            d.line([(x, y), (x + w, y)], fill=fill, width=lw)
        if s[3]:  # underline
            y = baseline + int(size * 0.12)
            d.line([(x, y), (x + w, y)], fill=fill, width=lw)
        x += w


def make(img_path, quote, name, handle, out="card.png"):
    if quote == "-":
        quote = sys.stdin.read().strip("\n")

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
    d.text((TEXT_X, QUOTE_MARK_Y), "\u201c", font=font(110, True), fill=(70, 70, 75))

    # quote: auto-shrinks to fit above the name, truncates if it still can't
    size, lines, lh = fit_quote(quote)
    ascent = font(size).getmetrics()[0]
    y = QUOTE_TOP
    for line in lines:
        draw_line(d, TEXT_X, y + ascent, line, size)
        y += lh

    # name + handle: fixed position, clipped to the column
    name_f, handle_f = font(28, True), font(22)
    d.line([(TEXT_X, NAME_Y + 17), (TEXT_X + 22, NAME_Y + 17)], fill=(90, 90, 95), width=2)
    d.text((TEXT_X + 38, NAME_Y), ellipsize(name, name_f, MAX_W - 38), font=name_f, fill="white")
    d.text((TEXT_X, NAME_Y + 42), ellipsize(handle, handle_f, MAX_W), font=handle_f, fill=(130, 130, 135))

    card.save(out)


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)
    make(*sys.argv[1:6])