"""
Генератор картинок для постов (1080x1080, фирменный синий + герб школы).

Пост запрашивает картинку полем card: в шапке. Каждый вид оформлен по-своему:

  card: puzzle     задача на доске (fen, side, goal, caption, note)
  card: answer     ответ на задачу: стрелка хода, подсветка мата (fen, move, san, title)
  card: tips       крупная цифра + карточки с советами (title, lines, note)
  card: steps      набор в школу: лесенка из фигур (title, subtitle, lines, button, steps)
  card: ticket     пробное занятие «билетом» (title, headline, subtitle, lines, button, stub)
  card: fact       шахматный факт / цитата (title=текст факта, note=пояснение, piece)
  card: term       термин дня (title=слово, subtitle=ударение, definition, example)
  card: quiz       вопрос с двумя вариантами (title, a, b, note)
  card: announce   (старый вид) заголовок, пункты, кнопка
  card: list       (старый вид) пронумерованный список

Общие необязательные поля: theme (вариант цветов), footer (подпись внизу), tag (рубрика сверху).
Если theme не указана, берётся по названию поста, так что соседние посты выглядят по-разному.

Подробности по полям каждого вида: README, раздел «Автоматические картинки».
"""
import hashlib
import re
from pathlib import Path

from PIL import Image, ImageDraw

from cards_engine import (BLUE, BOARD_COLORS, GOLD, GOLD_D, GREEN, ICE, INK, NAVY, RED, ROYAL, S, SKY,
                          W, WHITE, Cv, big_piece, checker_strip, confetti, diagonal_checks, draw_board,
                          font, footer, mix, parse_fen_board, parse_sq, piece, pill, sq_center)

DEFAULT_FOOTER = "Шахматная онлайн школа «Тимур и его команда»"
CREAM = (250, 244, 230)


def _pick(meta, names, key=None):
    """Тема из поля theme или по названию поста."""
    t = meta.get("theme", "").strip().lower()
    if t in names:
        return t
    seed = hashlib.md5((key or meta.get("title", "") + meta.get("when", "")).encode("utf-8")).hexdigest()
    return names[int(seed, 16) % len(names)]


def _items(meta, limit=8):
    return [s.strip() for s in meta.get("lines", "").split("|") if s.strip()][:limit]


def _foot(meta):
    return meta.get("footer", DEFAULT_FOOTER)


# =====================================================================
#  ЗАДАЧА и ОТВЕТ
# =====================================================================

PUZZLE_THEMES = {
    # фон, плашка шапки, цвет заголовка, подзаголовка, доска, рамка, плашка цели, логотип
    "ice": dict(bg=ICE, band=BLUE, title=WHITE, sub=SKY, board="blue", frame=BLUE, goal=GOLD, goal_t=INK,
                text=BLUE, logo=WHITE),
    "night": dict(bg=None, band=None, title=WHITE, sub=SKY, board="green", frame=(14, 22, 66), goal=GOLD,
                  goal_t=INK, text=WHITE, logo=WHITE),
    "wood": dict(bg=CREAM, band=(112, 58, 28), title=WHITE, sub=(240, 215, 180), board="wood",
                 frame=(112, 58, 28), goal=BLUE, goal_t=WHITE, text=(112, 58, 28), logo=WHITE),
}


def _puzzle_base(meta, th, header, sub):
    cv = Cv(th["bg"] or BLUE)
    if th["bg"] is None:
        cv.gradient(NAVY, BLUE, angle=False)
        cv.glow(900, 160, 380, ROYAL, 0.55)
        diagonal_checks(cv, WHITE, 10, 90)
    else:
        cv.rect(0, 0, W, 190, fill=th["band"])
        checker_strip(cv, 0, 0, 12, 2, 95, mix(th["band"], WHITE, 0.07), th["band"], 255)
    cv.text(60, 74, header, "black", cv.fit(header, "black", 74, 700), th["title"], anchor="lm")
    cv.text(62, 134, sub, "med", cv.fit(sub, "med", 32, 700), th["sub"], anchor="lm")
    cv.logo(930, 24, 140, tint=th["logo"])
    return cv


def _puzzle(meta):
    th = PUZZLE_THEMES[_pick(meta, list(PUZZLE_THEMES))]
    fen = meta.get("fen", "")
    side = meta.get("side") or (fen.split()[1] if len(fen.split()) > 1 else "w")
    side_ru = "белых" if side == "w" else "чёрных"
    goal = meta.get("goal", "Мат в 1 ход")
    title = meta.get("title", "Задача дня")
    sub = meta.get("subtitle") or f"{'Белые' if side == 'w' else 'Чёрные'} начинают и ставят мат"
    cv = _puzzle_base(meta, th, title.upper(), sub)
    sq = 80
    bx, by = (W - sq * 8) / 2, 216
    flip = meta.get("flip", "").lower() in ("yes", "да", "1", "true")
    draw_board(cv, fen, bx, by, sq, th["board"], flip=flip, frame=th["frame"])
    y = by + sq * 8 + 58
    # плашка цели + чей ход
    right = bx + sq * 8 + 6
    label = f"Ход {side_ru}"
    lw = cv.width(label, "bold", 32) + 74
    avail = (right - (bx - 6)) - lw - 18
    gsz = cv.fit(goal.upper(), "black", 34, avail - 56, 20)
    gw = cv.width(goal.upper(), "black", gsz, 2) + 56
    cv.rect(bx - 6, y - 30, bx - 6 + gw, y + 30, fill=th["goal"], r=30)
    cv.text(bx - 6 + gw / 2, y + 1, goal.upper(), "black", gsz, th["goal_t"], anchor="mm", spacing=2)
    cv.rect(right - lw, y - 30, right, y + 30, fill=WHITE if side == "w" else INK, r=30,
            outline=th["frame"] if side == "w" else WHITE, w=3)
    cv.ellipse(right - lw + 34, y, 14, fill=WHITE if side == "w" else INK, outline=INK if side == "w" else WHITE, w=3)
    cv.text(right - lw + 58, y + 1, label, "bold", 32, INK if side == "w" else WHITE, anchor="lm")
    # ходы партии / подпись
    cap = meta.get("caption", "")
    if cap:
        cv.text(W / 2, y + 58, cap, "semi", cv.fit(cap, "semi", 32, 940), th["text"], anchor="mm")
    note = meta.get("note", "Ответ пишите в комментариях")
    cv.text(W / 2, y + (104 if cap else 62), note, "med", cv.fit(note, "med", 30, 940), mix(th["text"], th["bg"] or BLUE, 0.35),
            anchor="mm")
    return cv


def _answer(meta):
    th = PUZZLE_THEMES[_pick(meta, list(PUZZLE_THEMES))]
    fen = meta.get("fen", "")
    mv = meta.get("move", "")  # например e2e4 или h5f7
    title = meta.get("title", "Ответ на задачу")
    sub = meta.get("subtitle", "Вчерашняя задача")
    cv = _puzzle_base(meta, th, title.upper(), sub)
    sq = 80
    bx, by = (W - sq * 8) / 2, 216
    marks, arrows = [], []
    if len(mv) >= 4:
        a, b = mv[:2], mv[2:4]
        marks += [(a, (255, 214, 64, 110)), (b, (60, 200, 130, 140))]
        arrows.append((a, b, (46, 190, 130, 225)))
    for t in meta.get("targets", "").split():  # атакованные фигуры (вилка): подсвечиваем оранжевым
        if len(t) == 2:
            marks.append((t, (255, 140, 50, 150)))
    # король чёрных/белых, получивший мат: ищем короля стороны, которая НЕ ходит
    board = parse_fen_board(fen)
    side = (fen.split()[1] if len(fen.split()) > 1 else "w")
    victim = "k" if side == "w" else "K"
    if meta.get("mate", "yes") != "no":
        for (f, r), ch in board.items():
            if ch == victim:
                marks.append(("abcdefgh"[f] + str(r), (235, 87, 87, 150)))
    draw_board(cv, fen, bx, by, sq, th["board"], flip=meta.get("flip", "") in ("yes", "да"), marks=marks,
               arrows=arrows, frame=th["frame"])
    y = by + sq * 8 + 62
    san = meta.get("san", "")
    res = meta.get("result", "МАТ!")
    text = f"{san}   {res}".strip()
    tw = cv.width(text, "black", 44, 1) + 80
    cv.rect(W / 2 - tw / 2, y - 38, W / 2 + tw / 2, y + 38, fill=GREEN, r=38)
    cv.text(W / 2, y + 2, text, "black", 44, WHITE, anchor="mm", spacing=1)
    note = meta.get("note", "Удалось решить? Пишите в комментариях")
    cv.text(W / 2, y + 74, note, "med", cv.fit(note, "med", 30, 940), mix(th["text"], th["bg"] or BLUE, 0.35),
            anchor="mm")
    return cv


# =====================================================================
#  СОВЕТЫ (крупная цифра + карточки)
# =====================================================================

TIPS_THEMES = {
    "royal": dict(top=BLUE, bot=NAVY, num=GOLD, label=WHITE, card=WHITE, card_t=INK, card_d=(70, 80, 130),
                  badge=BLUE, badge_t=WHITE, pat=WHITE, logo=WHITE, note_bg=(255, 255, 255, 30), note_t=WHITE,
                  accent=GOLD),
    "paper": dict(top=ICE, bot=(214, 226, 252), num=BLUE, label=INK, card=WHITE, card_t=INK, card_d=(88, 96, 140),
                  badge=BLUE, badge_t=WHITE, pat=BLUE, logo=BLUE, note_bg=BLUE + (255,), note_t=WHITE,
                  accent=GOLD),
    "gold": dict(top=(255, 213, 102), bot=(255, 180, 40), num=NAVY, label=INK, card=WHITE, card_t=INK,
                 card_d=(90, 90, 110), badge=NAVY, badge_t=WHITE, pat=WHITE, logo=NAVY, note_bg=NAVY + (255,),
                 note_t=WHITE, accent=NAVY),
}
TIP_ICONS = ["♟", "♞", "♜", "♝", "♛", "♚"]


def _tips(meta):
    th = TIPS_THEMES[_pick(meta, list(TIPS_THEMES))]
    cv = Cv(th["top"])
    cv.gradient(th["top"], th["bot"])
    diagonal_checks(cv, th["pat"], 14 if th["pat"] == WHITE else 10, 90)
    title = meta.get("title", "Советы тренера")
    items = _items(meta, 5)
    m = re.match(r"^\s*(\d+)\s+(.*)$", title)
    cv.logo(52, 34, 112, tint=th["logo"])
    tag = meta.get("tag", "СОВЕТ ТРЕНЕРА")
    pill(cv, 190, 70, tag, th["accent"] if th["accent"] != th["top"] else WHITE, INK if th["accent"] == GOLD else WHITE,
         size=24, h=48)
    # левая колонка: цифра
    low = 868 if meta.get("note") else 940   # подпись должна закончиться выше нижней плашки

    def left_label(text, size, max_lines):
        # подбираем размер так, чтобы подпись помещалась в колонку по ширине и по высоте
        while True:
            lines = cv.wrap(text, "black", size, 270)
            ok = all(cv.width(ln, "black", size) <= 270 for ln in lines) and len(lines) <= max_lines
            if ok or size <= 26:
                break
            size -= 2
        y0 = min(640, low - len(lines) * size * 1.12)
        cv.paragraph(70, y0, text, "black", size, th["label"], 270, line_h=1.12, min_size=size)

    if m:
        num, label = m.group(1), m.group(2)
        cv.text(70, 250, num, "black", 380, th["num"], anchor="la")
        left_label(label, 56, 4)
    else:
        big_piece(cv, "♞", 200, 430, 380, th["num"], 1.0)
        left_label(title, 54, 5)
    # правая колонка: карточки
    x0, x1 = 380, 1020
    top, bottom = 232, 880 if meta.get("note") else 960
    n = max(len(items), 1)
    gap = 22
    h = min(190, (bottom - top - gap * (n - 1)) / n)
    y = top
    for i, raw in enumerate(items):
        head, _, detail = raw.partition("::")
        cv.shadow(x0, y, x1, y + h, r=26, blur=14, dy=8, alpha=70)
        cv.rect(x0, y, x1, y + h, fill=th["card"], r=26)
        r = min(54, h / 2 - 14)
        cx, cy = x0 + 22 + r, y + h / 2
        cv.ellipse(cx, cy, r, fill=th["badge"])
        cv.text(cx, cy + r * 0.04, TIP_ICONS[i % len(TIP_ICONS)], "pieces", r * 1.15, th["badge_t"], anchor="mm")
        tx = cx + r + 24
        mw = x1 - tx - 20
        if detail.strip() and h >= 128:
            sz = cv.fit(head.strip(), "xbold", 38, mw, 26)
            cv.text(tx, y + h * 0.33, head.strip(), "xbold", sz, th["card_t"], anchor="lm")
            cv.paragraph(tx, y + h * 0.33 + 24, detail.strip(), "med", 25, th["card_d"], mw, line_h=1.22, max_lines=3,
                         min_size=20)
        else:
            lines = cv.wrap(head.strip(), "xbold", 38, mw)
            sz = 38 if len(lines) <= 2 else 30
            lines = cv.wrap(head.strip(), "xbold", sz, mw)[:3]
            ty = cy - (len(lines) - 1) * sz * 0.62
            for ln in lines:
                cv.text(tx, ty, ln, "xbold", sz, th["card_t"], anchor="lm")
                ty += sz * 1.24
        y += h + gap
    if meta.get("note"):
        nh = 96
        ny = 905
        lay = cv.layer()
        ImageDraw.Draw(lay).rounded_rectangle(cv._b(60, ny, 1020, ny + nh), radius=nh / 2 * S, fill=th["note_bg"])
        cv.commit(lay)
        cv.paragraph(W / 2, ny + nh / 2 - 18, meta["note"], "semi", 30, th["note_t"], 860, anchor="m",
                     line_h=1.2, max_lines=2, min_size=22)
    footer(cv, _foot(meta), mix(th["label"], th["top"], 0.25), y=1042, size=19)
    return cv


# =====================================================================
#  НАБОР: лесенка из фигур
# =====================================================================

def _steps(meta):
    cv = Cv(BLUE)
    cv.gradient(ROYAL if meta.get("theme") == "bright" else BLUE, NAVY)
    cv.glow(930, 330, 420, ROYAL, 0.6)
    diagonal_checks(cv, WHITE, 8, 90)
    cv.logo(52, 36, 120)
    pill(cv, 200, 76, meta.get("tag", "НАБОР ОТКРЫТ").upper(), GOLD, INK, size=24, h=48)
    title = meta.get("title", "Открыт набор в онлайн-школу шахмат")
    y = cv.paragraph(60, 205, title, "black", 76, WHITE, 640, line_h=1.06, max_lines=3, min_size=48)
    sub = meta.get("subtitle", "")
    if sub:
        y = cv.paragraph(62, y + 10, sub, "med", 32, SKY, 600, line_h=1.25, max_lines=2)
    y += 22
    for it in _items(meta, 4):
        cv.ellipse(84, y + 20, 22, fill=GOLD)
        cv.line([(73, y + 20), (81, y + 29), (96, y + 11)], INK, 5)
        y = cv.paragraph(124, y, it, "semi", 33, WHITE, 470, line_h=1.2, max_lines=2, min_size=26) + 12
    # лесенка
    labels = [s.strip() for s in meta.get("steps", "Основы|Тактика|Дебюты|Турниры|Победы").split("|")][:5]
    glyphs = ["p", "n", "b", "r", "q"]
    n = len(labels)
    x_start, x_end, base_y = 520, 1040, 1000
    sw = (x_end - x_start) / n
    for i, lab in enumerate(labels):
        x0 = x_start + i * sw
        top = base_y - (110 + i * 88)
        cv.shadow(x0, top, x0 + sw, base_y, r=0, blur=14, dy=6, alpha=70)
        cv.rect(x0, top, x0 + sw + 1, base_y, fill=mix(WHITE, SKY, 0.15 + 0.1 * i))
        cv.rect(x0, top, x0 + sw + 1, top + 14, fill=WHITE)
        cv.rect(x0 + sw - 6, top + 14, x0 + sw + 1, base_y, fill=mix(SKY, BLUE, 0.35))
        cv.text(x0 + sw / 2, top + 54, lab, "bold", cv.fit(lab, "bold", 22, sw - 14, 15), BLUE, anchor="mm")
        cv.text(x0 + sw / 2, top + 98, str(i + 1), "black", 34, mix(BLUE, SKY, 0.35), anchor="mm")
        size = 96 + i * 18
        piece(cv, glyphs[i % 5], x0 + sw / 2, top - size * 0.4, size, white=True, outline=NAVY)
    # звезда над верхней фигурой
    sx, sy = x_end - sw / 2, base_y - (110 + (n - 1) * 88) - 96 - (n - 1) * 18 - 70
    cv.glow(sx, sy, 120, GOLD, 0.45)
    cv.text(sx - 6, sy, "★", "pieces", 112, GOLD, anchor="mm")
    # кнопка
    btn = meta.get("button", "Первое занятие — бесплатно")
    bw = min(440, cv.width(btn, "black", 32) + 70)
    cv.shadow(60, 880, 60 + bw, 968, r=44, blur=12, dy=8, alpha=90)
    cv.rect(60, 880, 60 + bw, 968, fill=GOLD, r=44)
    cv.text(60 + bw / 2, 925, btn, "black", cv.fit(btn, "black", 32, bw - 40), INK, anchor="mm")
    url = meta.get("url", "")
    if url:
        cv.text(62, 1010, url, "semi", 24, SKY, anchor="lm")
    return cv


# =====================================================================
#  ПРОБНОЕ ЗАНЯТИЕ: билет
# =====================================================================

def _ticket(meta):
    cv = Cv(BLUE)
    cv.gradient(NAVY if meta.get("theme") == "night" else BLUE, NAVY if meta.get("theme") != "night" else (8, 12, 40))
    cv.glow(540, 560, 520, ROYAL, 0.5)
    confetti(cv, meta.get("title", "x"), [GOLD, WHITE, SKY, ROYAL, GOLD_D], n=60, avoid=[(30, 20, 520, 140), (30, 130, 1050, 830)])
    cv.logo(52, 36, 110)
    pill(cv, 190, 70, meta.get("tag", "ПРИГЛАШАЕМ").upper(), WHITE, BLUE, size=24, h=48)
    head = meta.get("title", "Приглашаем на пробное занятие")
    cv.paragraph(60, 168, head, "black", 70, WHITE, 960, line_h=1.06, max_lines=2, min_size=44)
    # билет: маска с вырезами
    x0, y0, x1, y1 = 60, 330, 1020, 790
    perf = 760
    mask = Image.new("L", (W * S, W * S), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle(cv._b(x0, y0, x1, y1), radius=36 * S, fill=255)
    for cx, cy, r in [(x0, (y0 + y1) / 2, 40), (x1, (y0 + y1) / 2, 40), (perf, y0, 26), (perf, y1, 26)]:
        md.ellipse(cv._b(cx - r, cy - r, cx + r, cy + r), fill=0)
    cv.shadow_mask(mask, blur=22, dy=16, alpha=120)
    grad = Image.new("RGB", (1, 256))
    for i in range(256):
        grad.putpixel((0, i), mix((255, 214, 110), (255, 176, 40), i / 255))
    grad = grad.resize((W * S, int((y1 - y0) * S)))
    fill = Image.new("RGB", (W * S, W * S), GOLD)
    fill.paste(grad, (0, int(y0 * S)))
    cv.im.paste(fill, (0, 0), mask)
    cv.d = ImageDraw.Draw(cv.im, "RGBA")
    # пунктир
    for yy in range(int(y0 + 46), int(y1 - 40), 24):
        cv.line([(perf, yy), (perf, yy + 12)], (150, 90, 10, 190), 4)
    # левая часть
    cv.text(110, y0 + 56, meta.get("kicker", "ПРОБНОЕ ЗАНЯТИЕ").upper(), "bold", 28, (120, 70, 0), anchor="lm", spacing=4)
    big = meta.get("headline", "БЕСПЛАТНО").upper()
    cv.text(104, y0 + 150, big, "black", cv.fit(big, "black", 132, 610, 60), INK, anchor="lm")
    sub = meta.get("subtitle", "20 минут · онлайн · с тренером")
    cv.text(110, y0 + 242, sub, "bold", cv.fit(sub, "bold", 36, 610), (90, 55, 0), anchor="lm")
    yy = y0 + 296
    for it in _items(meta, 3):
        cv.ellipse(124, yy + 16, 9, fill=INK)
        cv.text(148, yy + 16, it, "semi", cv.fit(it, "semi", 30, 560, 22), INK, anchor="lm")
        yy += 46
    # корешок
    cx = (perf + x1) / 2
    cv.text(cx, y0 + 168, "♞", "pieces", 190, INK, anchor="mm")
    stub = meta.get("stub", "ЗАПИСЬ\nОТКРЫТА")
    yy = y0 + 306
    stub_lines = stub.replace("\\n", "\n").split("\n")
    ssz = min(cv.fit(ln, "black", 34, (x1 - perf) - 40, 20) for ln in stub_lines)
    for ln in stub_lines:
        cv.text(cx, yy, ln, "black", ssz, INK, anchor="mm", spacing=2)
        yy += ssz * 1.24
    # кнопка
    btn = meta.get("button", "Записаться на пробное занятие")
    bw = min(900, cv.width(btn, "black", 38) + 110)
    cv.shadow(W / 2 - bw / 2, 840, W / 2 + bw / 2, 930, r=45, blur=14, dy=10, alpha=110)
    cv.rect(W / 2 - bw / 2, 840, W / 2 + bw / 2, 930, fill=WHITE, r=45)
    cv.text(W / 2, 886, btn, "black", cv.fit(btn, "black", 38, bw - 60), BLUE, anchor="mm")
    url = meta.get("url", "")
    cv.text(W / 2, 982, url or _foot(meta), "semi", 26 if url else 22, SKY, anchor="mm")
    return cv


# =====================================================================
#  ФАКТ / ЦИТАТА
# =====================================================================

FACT_THEMES = {
    "ice": dict(bg=ICE, text=BLUE, mark=GOLD, tag_bg=BLUE, tag_t=WHITE, wm=BLUE, wm_a=0.09, sub=(80, 95, 150),
                logo=BLUE, foot=(100, 115, 170)),
    "night": dict(bg=None, text=WHITE, mark=GOLD, tag_bg=GOLD, tag_t=INK, wm=WHITE, wm_a=0.07, sub=SKY,
                  logo=WHITE, foot=SKY),
    "sun": dict(bg=(255, 205, 90), text=INK, mark=WHITE, tag_bg=INK, tag_t=WHITE, wm=WHITE, wm_a=0.28,
                sub=(120, 70, 0), logo=NAVY, foot=(120, 70, 0)),
}
PIECE_FOR_FACT = ["♞", "♛", "♜", "♝", "♚", "♟"]


def _fact(meta):
    th = FACT_THEMES[_pick(meta, list(FACT_THEMES))]
    cv = Cv(th["bg"] or BLUE)
    if th["bg"] is None:
        cv.gradient(BLUE, NAVY)
        cv.glow(180, 140, 360, ROYAL, 0.5)
    pc = meta.get("piece", "")
    ch = PIECE_FOR_FACT[int(hashlib.md5(meta.get("title", "").encode("utf-8")).hexdigest(), 16) % 6]
    ch = {"n": "♞", "q": "♛", "r": "♜", "b": "♝", "k": "♚", "p": "♟"}.get(pc.lower(), ch)
    big_piece(cv, ch, 760, 640, 1050, th["wm"], th["wm_a"])
    cv.logo(W - 52 - 90, 38, 118, tint=th["logo"])
    pill(cv, 60, 60, meta.get("tag", "ШАХМАТНЫЙ ФАКТ").upper(), th["tag_bg"], th["tag_t"], size=24, h=50)
    cv.text(46, 120, "“", "black", 330, th["mark"], anchor="la")
    txt = meta.get("title", "")
    y = cv.paragraph(70, 370, txt, "xbold", 62, th["text"], 880, line_h=1.18, max_lines=7, min_size=36)
    note = meta.get("note", "")
    if note:
        cv.rect(70, y + 22, 82, y + 22 + 8, fill=th["mark"])
        cv.paragraph(70, y + 52, note, "med", 31, th["sub"], 840, line_h=1.3, max_lines=4, min_size=24)
    footer(cv, _foot(meta), th["foot"], y=1038, size=19)
    return cv


# =====================================================================
#  ТЕРМИН ДНЯ
# =====================================================================

def _term(meta):
    theme = _pick(meta, ["blue", "light"])
    dark = theme == "blue"
    cv = Cv(BLUE if dark else ICE)
    if dark:
        cv.gradient(BLUE, NAVY)
    ink = WHITE if dark else INK
    accent = GOLD if dark else BLUE
    big_piece(cv, "♞", 800, 790, 760, WHITE if dark else BLUE, 0.06 if dark else 0.07)
    sub = SKY if dark else (80, 95, 150)
    checker_strip(cv, 0, 0, 1, 12, 90, ROYAL if dark else SKY, NAVY if dark else BLUE, 255)
    cv.logo(W - 52 - 90, 38, 118, tint=WHITE if dark else BLUE)
    pill(cv, 140, 60, meta.get("tag", "ТЕРМИН ДНЯ").upper(), GOLD if dark else BLUE, INK if dark else WHITE,
         size=24, h=50)
    word = meta.get("title", "Термин")
    wsz = cv.fit(word.upper(), "black", 150, 860, 56)
    # высота всего блока, чтобы поставить его по центру свободной области
    d_lines = len(cv.wrap(meta.get("definition", ""), "semi", 44, 840))
    ex_txt = meta.get("example", "")
    ex_h = (56 + len(cv.wrap(ex_txt, "med", 32, 790)) * 41 + 12 + 30) if ex_txt else 0
    block = wsz * 0.8 + 74 + 36 + min(d_lines, 6) * 44 * 1.26 + ex_h + wsz * 0.6
    top = 260 + max(0, min(150, ((1000 - 150) - block) / 2 - 20))
    cv.text(140, top, word.upper(), "black", wsz, ink, anchor="lm")
    hint = meta.get("subtitle", "")
    if hint:
        cv.text(142, top + wsz * 0.80 + 10, hint, "ital", 44, accent, anchor="lm")
    y = top + wsz * 0.80 + 74
    cv.rect(142, y, 142 + 90, y + 8, fill=accent)
    y = cv.paragraph(142, y + 36, meta.get("definition", ""), "semi", 44, ink, 840, line_h=1.26, max_lines=6, min_size=30)
    ex = meta.get("example", "")
    if ex:
        n_ex = max(1, len(cv.wrap(ex, "med", 32, 790)))
        eh = 56 + n_ex * 41 + 12
        cv.rect(142, y + 30, 1010, y + 30 + eh, fill=(255, 255, 255, 28) if dark else WHITE, r=22)
        cv.rect(142, y + 30, 154, y + 30 + eh, fill=accent)
        cv.text(184, y + 30 + 28, "ПРИМЕР", "bold", 20, accent, anchor="la", spacing=3)
        cv.paragraph(184, y + 30 + 56, ex, "med", 32, ink, 790, line_h=1.26, max_lines=4, min_size=24)
    footer(cv, _foot(meta), SKY if dark else (100, 115, 170), y=1038, size=19)
    return cv


# =====================================================================
#  ВОПРОС С ДВУМЯ ВАРИАНТАМИ
# =====================================================================

def _quiz(meta):
    cv = Cv(BLUE)
    cv.gradient(ROYAL, NAVY)
    cv.glow(160, 980, 420, GOLD, 0.18)
    diagonal_checks(cv, WHITE, 9, 90)
    cv.logo(52, 36, 110)
    pill(cv, 190, 70, meta.get("tag", "ВОПРОС ДНЯ").upper(), GOLD, INK, size=24, h=48)
    y = cv.paragraph(60, 190, meta.get("title", "Что выберете?"), "black", 70, WHITE, 960, line_h=1.08,
                     max_lines=3, min_size=40)
    top = max(y + 30, 430)
    h = 400
    opts = [("А", meta.get("a", "Вариант А")), ("Б", meta.get("b", "Вариант Б"))]
    xs = [(60, 520), (560, 1020)]
    for (x0, x1), (letter, text) in zip(xs, opts):
        cv.shadow(x0, top, x1, top + h, r=36, blur=18, dy=12, alpha=110)
        cv.rect(x0, top, x1, top + h, fill=WHITE, r=36)
        cv.ellipse(x0 + 80, top + 80, 52, fill=BLUE if letter == "А" else GOLD)
        cv.text(x0 + 80, top + 82, letter, "black", 60, WHITE if letter == "А" else INK, anchor="mm")
        big_piece(cv, "♞" if letter == "А" else "♝", x1 - 110, top + h - 110, 230, BLUE, 0.09)
        cv.paragraph(x0 + 36, top + 160, text, "xbold", 40, INK, x1 - x0 - 72, line_h=1.18, max_lines=5, min_size=26)
    cv.ellipse(W / 2, top + h / 2, 44, fill=GOLD, outline=NAVY, w=6)
    cv.text(W / 2, top + h / 2 + 2, "VS", "black", 34, INK, anchor="mm")
    note = meta.get("note", "Голосуйте в комментариях: А или Б?")
    cv.text(W / 2, top + h + 82, note, "bold", cv.fit(note, "bold", 36, 940), WHITE, anchor="mm")
    footer(cv, _foot(meta), SKY, y=1040, size=19)
    return cv


# =====================================================================
#  старые виды (для уже написанных постов)
# =====================================================================

def _legacy(name):
    def draw(meta):
        import cards_legacy
        return cards_legacy.KINDS[name](meta)
    draw.legacy = True
    return draw


KINDS = {
    "puzzle": _puzzle, "answer": _answer, "tips": _tips, "steps": _steps, "ticket": _ticket,
    "fact": _fact, "term": _term, "quiz": _quiz,
    "announce": _legacy("announce"), "list": _legacy("list"),
}


def make_card(meta, out_path):
    """Создаёт картинку по полям поста и сохраняет в out_path. Возвращает путь."""
    kind = meta.get("card", "").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"неизвестный вид картинки card: {kind!r} (есть: {', '.join(KINDS)})")
    if not meta.get("title") and kind not in ("puzzle", "answer"):
        raise ValueError("для картинки нужно поле title:")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    res = KINDS[kind](meta)
    if getattr(KINDS[kind], "legacy", False):
        res.save(out_path)  # старые виды возвращают готовую картинку PIL
    else:
        res.save(out_path)
    return out_path
