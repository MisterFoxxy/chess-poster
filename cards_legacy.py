"""
Генератор картинок для постов (квадрат 1080x1080, фирменный синий + герб школы).

Пост запрашивает картинку полем card: в шапке. Виды:
  card: announce   заголовок, подзаголовок, список пунктов, кнопка, подпись
  card: list       заголовок, подзаголовок, пронумерованные пункты, заметка
  card: puzzle     шахматная доска из позиции FEN + подпись

Поля (все необязательные, кроме title):
  title:     крупный заголовок
  subtitle:  строка под заголовком
  lines:     пункты через вертикальную черту:  первый | второй | третий
  button:    текст на белой кнопке (announce)
  note:      небольшая строка внизу (list, puzzle)
  footer:    подпись внизу (по умолчанию название школы)
  fen:       позиция для puzzle (только расстановка фигур, до первого пробела)
  caption:   строка с ходами под доской (puzzle)

Нужен пакет Pillow:  pip install pillow
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
W = 1080
BLUE = (43, 60, 150)
WHITE = (255, 255, 255)
SKY = (176, 200, 255)
SOFT = (225, 233, 252)
DEFAULT_FOOTER = "Шахматная онлайн школа «Тимур и его команда»"

FONTS_REG = [
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
]
FONTS_BOLD = [
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]
FONTS_SYMBOL = [  # шахматные фигуры
    "C:/Windows/Fonts/seguisym.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]


def _font(candidates, size):
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise RuntimeError("Не найден подходящий шрифт для картинки: " + candidates[0])


def _fit(d, text, candidates, size, max_w, min_size=22):
    while size > min_size and d.textlength(text, font=_font(candidates, size)) > max_w:
        size -= 2
    return _font(candidates, size)


def _wrap(d, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if d.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _center(d, text, y, font, fill):
    d.text(((W - d.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)


def _background():
    img = Image.new("RGB", (W, W), BLUE)
    d = ImageDraw.Draw(img)
    dark = tuple(int(c * 0.72) for c in BLUE)
    for y in range(W):
        t = (y / W) ** 1.3
        d.line([(0, y), (W, y)], fill=tuple(int(BLUE[i] * (1 - t) + dark[i] * t) for i in range(3)))
    return img, d


def _logo_size(height):
    logo = Image.open(BASE / "logo_white.png").convert("RGBA")
    return logo.resize((int(logo.width * height / logo.height), height), Image.LANCZOS)


def _paste_logo(img, height, x=None, y=30):
    logo = _logo_size(height)
    if x is None:
        x = (W - logo.width) // 2
    img.paste(logo, (x, y), logo)
    return y + logo.height


def _title_block(d, text, y, size=68, max_lines=3):
    font = _font(FONTS_BOLD, size)
    lines = _wrap(d, text, font, 940)
    while len(lines) > max_lines and size > 36:
        size -= 4
        font = _font(FONTS_BOLD, size)
        lines = _wrap(d, text, font, 940)
    for line in lines:
        _center(d, line, y, font, WHITE)
        y += int(size * 1.2)
    return y


def _subtitle_block(d, text, y, size=40):
    if not text:
        return y
    font = _font(FONTS_REG, size)
    for line in _wrap(d, text, font, 900):
        _center(d, line, y, font, SKY)
        y += int(size * 1.3)
    return y


def _footer(d, text):
    if text:
        _center(d, text, 985, _fit(d, text, FONTS_REG, 30, 960), SOFT)


def _announce(meta):
    img, d = _background()
    y = _paste_logo(img, 200) + 20
    y = _title_block(d, meta["title"], y)
    y = _subtitle_block(d, meta.get("subtitle", ""), y + 6) + 24
    items = [s.strip() for s in meta.get("lines", "").split("|") if s.strip()]
    bottom = 800 if meta.get("button") else 930
    step = min(70, (bottom - y) // max(len(items), 1)) if items else 0
    sym = _font(FONTS_SYMBOL, 34)
    for item in items:
        font = _fit(d, item, FONTS_REG, 36, 800)
        d.text((140, y + step // 2), "♟", font=sym, fill=SKY, anchor="lm")
        d.text((195, y + step // 2), item, font=font, fill=WHITE, anchor="lm")
        y += step
    if meta.get("button"):
        d.rounded_rectangle([140, 830, 940, 930], radius=50, fill=WHITE)
        d.text((W / 2, 880), meta["button"], font=_fit(d, meta["button"], FONTS_BOLD, 40, 740),
               fill=BLUE, anchor="mm")
    _footer(d, meta.get("footer", DEFAULT_FOOTER))
    return img


def _list(meta):
    img, d = _background()
    y = _paste_logo(img, 190) + 20
    y = _title_block(d, meta["title"], y, size=64, max_lines=2)
    y = _subtitle_block(d, meta.get("subtitle", ""), y + 4, size=36) + 30
    items = [s.strip() for s in meta.get("lines", "").split("|") if s.strip()][:5]
    bottom = 900 if meta.get("note") else 960
    step = min(140, (bottom - y) // max(len(items), 1)) if items else 0
    r = min(50, step // 2 - 6)
    for i, item in enumerate(items, 1):
        cy = y + step // 2
        d.ellipse([140, cy - r, 140 + 2 * r, cy + r], fill=WHITE)
        d.text((140 + r, cy), str(i), font=_font(FONTS_BOLD, int(r * 1.1)), anchor="mm", fill=BLUE)
        d.text((140 + 2 * r + 40, cy), item, font=_fit(d, item, FONTS_BOLD, 46, 1000 - (140 + 2 * r + 40)),
               anchor="lm", fill=WHITE)
        y += step
    if meta.get("note"):
        _center(d, meta["note"], 915, _fit(d, meta["note"], FONTS_REG, 32, 960), SKY)
    _footer(d, meta.get("footer", DEFAULT_FOOTER))
    return img


def _puzzle(meta):
    img, d = _background()
    _paste_logo(img, 125, x=45, y=35)
    _center(d, meta["title"], 50, _fit(d, meta["title"], FONTS_BOLD, 58, 700), WHITE)
    if meta.get("subtitle"):
        _center(d, meta["subtitle"], 125, _fit(d, meta["subtitle"], FONTS_REG, 34, 900), SKY)
    fen = meta.get("fen", "").split()[0]
    sq, ox, oy = 90, (W - 720) // 2, 185
    light, dark = (232, 238, 250), (105, 137, 206)
    for r in range(8):
        for c in range(8):
            d.rectangle([ox + c * sq, oy + r * sq, ox + (c + 1) * sq, oy + (r + 1) * sq],
                        fill=light if (r + c) % 2 == 0 else dark)
    glyph = {"k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}
    fp = _font(FONTS_SYMBOL, 76)
    for r, row in enumerate(fen.split("/")):
        c = 0
        for ch in row:
            if ch.isdigit():
                c += int(ch)
                continue
            white = ch.isupper()
            d.text((ox + c * sq + sq / 2, oy + r * sq + sq / 2), glyph[ch.lower()], font=fp, anchor="mm",
                   fill=WHITE if white else (18, 22, 40), stroke_width=3,
                   stroke_fill=(18, 22, 40) if white else WHITE)
            c += 1
    small = _font(FONTS_REG, 22)
    for i, ch in enumerate("abcdefgh"):
        d.text((ox + i * sq + sq / 2, oy + 8 * sq + 16), ch, font=small, anchor="mm", fill=SOFT)
    for i in range(8):
        d.text((ox - 18, oy + i * sq + sq / 2), str(8 - i), font=small, anchor="mm", fill=SOFT)
    if meta.get("caption"):
        _center(d, meta["caption"], oy + 8 * sq + 50, _fit(d, meta["caption"], FONTS_REG, 34, 960), WHITE)
    if meta.get("note"):
        _center(d, meta["note"], oy + 8 * sq + 108, _fit(d, meta["note"], FONTS_REG, 30, 960), SKY)
    return img


KINDS = {"announce": _announce, "list": _list, "puzzle": _puzzle}


def make_card(meta, out_path):
    """Создаёт картинку по полям поста и сохраняет в out_path. Возвращает путь."""
    kind = meta.get("card", "").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"неизвестный вид картинки card: {kind!r} (есть: {', '.join(KINDS)})")
    if not meta.get("title"):
        raise ValueError("для картинки нужно поле title:")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    KINDS[kind](meta).save(out_path)
    return out_path
