"""
Движок рисования карточек: холст с плавными краями (рисуем в 2 раза крупнее и уменьшаем),
шрифты Inter из папки fonts/, шахматная доска, стрелки, фигуры, тени, логотип.
"""
import math
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

BASE = Path(__file__).resolve().parent
W = 1080
S = 2  # во сколько раз рисуем крупнее, чтобы края были гладкими

BLUE = (43, 60, 150)
NAVY = (20, 30, 86)
ROYAL = (61, 86, 201)
SKY = (176, 200, 255)
ICE = (236, 242, 255)
WHITE = (255, 255, 255)
GOLD = (255, 196, 64)
GOLD_D = (224, 150, 24)
INK = (18, 24, 56)
GREEN = (46, 190, 130)
RED = (235, 87, 87)

FONT_FILES = {
    "black": ["InterDisplay-Black.otf"],
    "xbold": ["InterDisplay-ExtraBold.otf"],
    "bold": ["Inter-Bold.otf"],
    "semi": ["Inter-SemiBold.otf"],
    "med": ["Inter-Medium.otf"],
    "reg": ["Inter-Regular.otf"],
    "ital": ["InterDisplay-Italic.otf"],
    "pieces": ["DejaVuSans.ttf"],
}
FONT_DIRS = [
    BASE / "fonts",
    Path("/usr/share/fonts/opentype/inter"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("C:/Windows/Fonts"),
]
FALLBACK = ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "arialbd.ttf", "arial.ttf"]


@lru_cache(maxsize=None)
def _font_path(key):
    for name in FONT_FILES[key] + FALLBACK:
        for d in FONT_DIRS:
            if (d / name).exists():
                return str(d / name)
    raise RuntimeError("Не найден шрифт для картинок: положите файлы шрифтов в папку fonts/")


@lru_cache(maxsize=None)
def font(key, size):
    return ImageFont.truetype(_font_path(key), int(round(size * S)))


def mix(c0, c1, t):
    return tuple(int(round(c0[i] * (1 - t) + c1[i] * t)) for i in range(3))


class Cv:
    """Холст 1080x1080. Все координаты и размеры задаются в единицах 1080x1080."""

    def __init__(self, fill=BLUE):
        self.im = Image.new("RGB", (W * S, W * S), fill)
        self.d = ImageDraw.Draw(self.im, "RGBA")

    # ---- примитивы
    def _b(self, x0, y0, x1, y1):
        return [x0 * S, y0 * S, x1 * S, y1 * S]

    def rect(self, x0, y0, x1, y1, fill=None, r=0, outline=None, w=1):
        if r:
            self.d.rounded_rectangle(self._b(x0, y0, x1, y1), radius=r * S, fill=fill,
                                     outline=outline, width=int(w * S))
        else:
            self.d.rectangle(self._b(x0, y0, x1, y1), fill=fill, outline=outline, width=int(w * S))

    def ellipse(self, cx, cy, r, fill=None, outline=None, w=1):
        self.d.ellipse(self._b(cx - r, cy - r, cx + r, cy + r), fill=fill, outline=outline, width=int(w * S))

    def poly(self, pts, fill=None, outline=None):
        self.d.polygon([(x * S, y * S) for x, y in pts], fill=fill, outline=outline)

    def line(self, pts, fill, w):
        self.d.line([(x * S, y * S) for x, y in pts], fill=fill, width=int(w * S), joint="curve")

    # ---- фон
    def gradient(self, c0, c1, y0=0, y1=W, angle=False):
        """Вертикальный градиент; angle=True: по диагонали."""
        g = Image.new("RGB", (1, 256))
        for i in range(256):
            g.putpixel((0, i), mix(c0, c1, i / 255))
        if angle:
            g = g.resize((W * S, W * S))
            g = g.rotate(-45, expand=False)
            g = g.resize((W * S, W * S))
            self.im.paste(g, (0, 0))
        else:
            g = g.resize((W * S, int((y1 - y0) * S)))
            self.im.paste(g, (0, int(y0 * S)))
        self.d = ImageDraw.Draw(self.im, "RGBA")

    def layer(self):
        return Image.new("RGBA", (W * S, W * S), (0, 0, 0, 0))

    def commit(self, layer):
        self.im = Image.alpha_composite(self.im.convert("RGBA"), layer).convert("RGB")
        self.d = ImageDraw.Draw(self.im, "RGBA")

    def glow(self, cx, cy, rad, color, alpha=0.5):
        """Мягкое пятно света."""
        lay = self.layer()
        ImageDraw.Draw(lay).ellipse(self._b(cx - rad, cy - rad, cx + rad, cy + rad),
                                    fill=color + (int(255 * alpha),))
        lay = lay.filter(ImageFilter.GaussianBlur(rad * S * 0.45))
        self.commit(lay)

    def shadow(self, x0, y0, x1, y1, r=0, blur=18, dy=10, alpha=80, color=(0, 0, 0)):
        lay = self.layer()
        ImageDraw.Draw(lay).rounded_rectangle(self._b(x0, y0 + dy, x1, y1 + dy), radius=r * S,
                                              fill=color + (alpha,))
        self.commit(lay.filter(ImageFilter.GaussianBlur(blur * S)))

    def shadow_mask(self, mask, blur=18, dy=10, alpha=80):
        lay = self.layer()
        sh = Image.new("RGBA", lay.size, (0, 0, 0, alpha))
        lay.paste(sh, (0, int(dy * S)), mask)
        self.commit(lay.filter(ImageFilter.GaussianBlur(blur * S)))

    # ---- текст
    def width(self, s, key, size, spacing=0):
        f = font(key, size)
        if not spacing:
            return self.d.textlength(s, font=f) / S
        return sum(self.d.textlength(ch, font=f) / S for ch in s) + spacing * (len(s) - 1)

    def text(self, x, y, s, key, size, fill, anchor="la", spacing=0, stroke=0, stroke_fill=None):
        f = font(key, size)
        if spacing:
            total = self.width(s, key, size, spacing)
            h = anchor[0]
            cx = x - total / 2 if h == "m" else (x - total if h == "r" else x)
            for ch in s:
                self.d.text((cx * S, y * S), ch, font=f, fill=fill, anchor="l" + anchor[1])
                cx += self.d.textlength(ch, font=f) / S + spacing
            return
        self.d.text((x * S, y * S), s, font=f, fill=fill, anchor=anchor,
                    stroke_width=int(stroke * S), stroke_fill=stroke_fill)

    def wrap(self, s, key, size, max_w):
        lines = []
        for para in str(s).split("\n"):
            cur = ""
            for word in para.split():
                trial = (cur + " " + word).strip()
                if self.width(trial, key, size) <= max_w or not cur:
                    cur = trial
                else:
                    lines.append(cur)
                    cur = word
            lines.append(cur)
        return lines

    def fit(self, s, key, size, max_w, min_size=18):
        while size > min_size and self.width(s, key, size) > max_w:
            size -= 2
        return size

    def paragraph(self, x, y, s, key, size, fill, max_w, line_h=1.25, anchor="l", max_lines=None, min_size=20):
        """Абзац с переносами. Если не помещается в max_lines, шрифт уменьшается. Возвращает y после абзаца."""
        lines = self.wrap(s, key, size, max_w)
        while size > min_size and ((max_lines and len(lines) > max_lines)
                                   or any(self.width(ln, key, size) > max_w for ln in lines)):
            size -= 2
            lines = self.wrap(s, key, size, max_w)
        for line in lines:
            self.text(x, y, line, key, size, fill, anchor=anchor + "a")
            y += size * line_h
        return y

    # ---- картинки
    def paste(self, img, x, y, h=None, w=None, alpha=1.0, rot=0):
        if h:
            img = img.resize((int(img.width * h * S / img.height), int(h * S)), Image.LANCZOS)
        elif w:
            img = img.resize((int(w * S), int(img.height * w * S / img.width)), Image.LANCZOS)
        if rot:
            img = img.rotate(rot, expand=True, resample=Image.BICUBIC)
        if alpha < 1:
            a = img.getchannel("A").point(lambda v: int(v * alpha))
            img.putalpha(a)
        lay = self.layer()
        lay.paste(img, (int(x * S), int(y * S)), img)
        self.commit(lay)

    def logo(self, x, y, h, tint=WHITE, alpha=1.0, center=False):
        lg = logo_image(tint)
        wd = lg.width * h / lg.height
        self.paste(lg, x - wd / 2 if center else x, y, h=h, alpha=alpha)
        return wd

    def save(self, path):
        out = self.im.resize((W, W), Image.LANCZOS)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        out.save(path)


@lru_cache(maxsize=None)
def _logo_base():
    return Image.open(BASE / "logo_white.png").convert("RGBA")


def logo_image(tint=WHITE):
    base = _logo_base().copy()
    if tint != WHITE:
        solid = Image.new("RGBA", base.size, tint + (255,))
        solid.putalpha(base.getchannel("A"))
        return solid
    return base


# ---------- общие украшения ----------

def pill(cv, x, y, text, bg, fg, size=26, pad=22, h=52, key="bold", spacing=3, icon=None):
    """Плашка-рубрика со скруглением. Возвращает x правого края."""
    tw = cv.width(text, key, size, spacing)
    iw = 34 if icon else 0
    cv.rect(x, y, x + tw + pad * 2 + iw, y + h, fill=bg, r=h / 2)
    if icon:
        cv.text(x + pad + 8, y + h / 2, icon, "pieces", size + 4, fg, anchor="lm")
    cv.text(x + pad + iw, y + h / 2 + 1, text, key, size, fg, anchor="lm", spacing=spacing)
    return x + tw + pad * 2 + iw


def footer(cv, text, color, y=1040, size=22, spacing=2):
    if text:
        cv.text(W / 2, y, text.upper(), "semi", size, color, anchor="mm", spacing=spacing)


def checker_strip(cv, x0, y0, cols, rows, sq, c1, c2, alpha=255):
    lay = cv.layer()
    dd = ImageDraw.Draw(lay)
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2:
                dd.rectangle(cv._b(x0 + c * sq, y0 + r * sq, x0 + (c + 1) * sq, y0 + (r + 1) * sq),
                             fill=c1 + (alpha,))
            else:
                dd.rectangle(cv._b(x0 + c * sq, y0 + r * sq, x0 + (c + 1) * sq, y0 + (r + 1) * sq),
                             fill=c2 + (alpha,))
    cv.commit(lay)


def diagonal_checks(cv, color, alpha=18, size=90):
    """Едва заметный шахматный узор по всему фону."""
    lay = cv.layer()
    dd = ImageDraw.Draw(lay)
    n = W // size + 1
    for r in range(n):
        for c in range(n):
            if (r + c) % 2:
                dd.rectangle(cv._b(c * size, r * size, (c + 1) * size, (r + 1) * size), fill=color + (alpha,))
    cv.commit(lay)


def confetti(cv, seed, colors, n=46, avoid=None, alpha=200):
    rnd = random.Random(seed)
    lay = cv.layer()
    dd = ImageDraw.Draw(lay)
    for _ in range(n):
        x, y = rnd.uniform(20, W - 20), rnd.uniform(20, W - 20)
        zones = avoid if (avoid and isinstance(avoid[0], (tuple, list))) else ([avoid] if avoid else [])
        if any(z[0] < x < z[2] and z[1] < y < z[3] for z in zones):
            continue
        col = rnd.choice(colors) + (alpha,)
        s = rnd.uniform(8, 20)
        shape = rnd.choice(["sq", "circle", "bar"])
        if shape == "circle":
            dd.ellipse(cv._b(x - s / 2, y - s / 2, x + s / 2, y + s / 2), fill=col)
        elif shape == "sq":
            dd.rectangle(cv._b(x - s / 2, y - s / 2, x + s / 2, y + s / 2), fill=col)
        else:
            dd.rectangle(cv._b(x - s, y - 3, x + s, y + 3), fill=col)
    cv.commit(lay)


def big_piece(cv, ch, cx, cy, size, color, alpha=0.1):
    lay = cv.layer()
    dd = ImageDraw.Draw(lay)
    dd.text((cx * S, cy * S), ch, font=font("pieces", size), fill=color + (int(255 * alpha),), anchor="mm")
    cv.commit(lay)


GLYPH = {"k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}


def piece(cv, kind, cx, cy, size, white=True, outline=None):
    """Одна фигура (kind: k q r b n p). Белая: белая заливка, тёмный контур; чёрная: наоборот."""
    ch = GLYPH[kind.lower()]
    if white:
        fill, edge = WHITE, outline or INK
    else:
        fill, edge = INK, outline or WHITE
    cv.d.text((cx * S, cy * S), ch, font=font("pieces", size), fill=fill, anchor="mm",
              stroke_width=int(max(2, size * 0.035) * S), stroke_fill=edge)


# ---------- шахматная доска ----------

BOARD_COLORS = {
    "blue": ((232, 238, 250), (105, 137, 206)),
    "wood": ((240, 217, 181), (181, 136, 99)),
    "green": ((238, 238, 210), (118, 150, 86)),
    "slate": ((222, 227, 230), (125, 148, 163)),
}


def sq_center(f, r, x0, y0, sq, flip=False):
    col, row = (7 - f, r - 1) if flip else (f, 8 - r)
    return x0 + col * sq + sq / 2, y0 + row * sq + sq / 2


def parse_sq(name):
    return ord(name[0]) - 97, int(name[1])


def parse_fen_board(fen):
    rows = fen.split()[0].split("/")
    out = {}
    for ri, row in enumerate(rows):
        f = 0
        for ch in row:
            if ch.isdigit():
                f += int(ch)
            else:
                out[(f, 8 - ri)] = ch
                f += 1
    return out


def draw_board(cv, fen, x0, y0, sq, colors="blue", flip=False, marks=(), arrows=(), coords=True, frame=None):
    light, dark = BOARD_COLORS[colors]
    size = sq * 8
    if frame:
        cv.shadow(x0 - 14, y0 - 14, x0 + size + 14, y0 + size + 14, r=10, blur=22, dy=14, alpha=110)
        cv.rect(x0 - 14, y0 - 14, x0 + size + 14, y0 + size + 14, fill=frame, r=10)
    for r in range(8):
        for c in range(8):
            cv.rect(x0 + c * sq, y0 + r * sq, x0 + (c + 1) * sq, y0 + (r + 1) * sq,
                    fill=light if (r + c) % 2 == 0 else dark)
    # подсветка клеток
    lay = cv.layer()
    dd = ImageDraw.Draw(lay)
    for name, rgba in marks:
        f, r = parse_sq(name)
        cx, cy = sq_center(f, r, x0, y0, sq, flip)
        dd.rectangle(cv._b(cx - sq / 2, cy - sq / 2, cx + sq / 2, cy + sq / 2), fill=rgba)
    cv.commit(lay)
    # координаты
    if coords:
        for i in range(8):
            f = 7 - i if flip else i
            cx, cy = sq_center(f, 1 if not flip else 8, x0, y0, sq, flip)
            dark_sq = ((f + (1 if not flip else 8)) % 2) == 1
            cv.text(cx + sq / 2 - 5, cy + sq / 2 - 4, "abcdefgh"[f], "bold", sq * 0.19,
                    light if dark_sq else dark, anchor="rd")
            rr = i + 1
            cx, cy = sq_center(0 if not flip else 7, rr, x0, y0, sq, flip)
            dark_sq = ((0 if not flip else 7) + rr) % 2 == 1
            cv.text(cx - sq / 2 + 5, cy - sq / 2 + 3, str(rr), "bold", sq * 0.19,
                    light if dark_sq else dark, anchor="la")
    # фигуры
    for (f, r), ch in parse_fen_board(fen).items():
        cx, cy = sq_center(f, r, x0, y0, sq, flip)
        piece(cv, ch, cx, cy + sq * 0.02, sq * 0.86, white=ch.isupper())
    # стрелки
    for a, b, rgba in arrows:
        fa, ra = parse_sq(a)
        fb, rb = parse_sq(b)
        ax, ay = sq_center(fa, ra, x0, y0, sq, flip)
        bx, by = sq_center(fb, rb, x0, y0, sq, flip)
        ang = math.atan2(by - ay, bx - ax)
        ux, uy = math.cos(ang), math.sin(ang)
        px, py = -uy, ux
        head_l, head_w, shaft_w = sq * 0.5, sq * 0.56, sq * 0.2
        sx, sy = ax + ux * sq * 0.18, ay + uy * sq * 0.18
        ex, ey = bx - ux * sq * 0.1, by - uy * sq * 0.1
        tx, ty = ex - ux * head_l, ey - uy * head_l
        pts = [
            (sx + px * shaft_w / 2, sy + py * shaft_w / 2), (tx + px * shaft_w / 2, ty + py * shaft_w / 2),
            (tx + px * head_w / 2, ty + py * head_w / 2), (ex, ey),
            (tx - px * head_w / 2, ty - py * head_w / 2), (tx - px * shaft_w / 2, ty - py * shaft_w / 2),
            (sx - px * shaft_w / 2, sy - py * shaft_w / 2),
        ]
        lay = cv.layer()
        ImageDraw.Draw(lay).polygon([(px_ * S, py_ * S) for px_, py_ in pts], fill=rgba)
        cv.commit(lay)
    return size
