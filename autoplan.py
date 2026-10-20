#!/usr/bin/env python3
"""
Автопланировщик постов: сам заранее создаёт новые посты в папке posts/.

Каждый запуск (раз в 5 минут вместе с публикатором) смотрит расписание content/schedule.json
и заполняет свободные слоты на ближайшие horizon_days дней (по умолчанию 14):

  * Пн 19:00 — «Задача дня» (мат в 1-2 хода) из банка content/puzzles.json;
  * на следующий день в 12:00 — «Ответ на задачу» к ней (для любой задачи из банка,
    в том числе написанной вручную: ищется по расположению фигур);
  * Чт 19:00 — советы тренера или шахматный факт (по очереди);
  * Сб 12:00 — термин, вопрос-голосование или факт (по очереди);
  * Вс 18:00 — пост о школе (набор, пробное занятие, польза шахмат).

Каждый пост — обычный файл в posts/ с полями  source: auto  и  slot: ...  Дальше его подхватывает
publisher.py: в Telegram он уходит в назначенное время, в ВК текст ставится в отложку заранее.

Если на слот уже есть пост (ваш, написанный вручную, в пределах часа от времени слота),
слот пропускается. Чтобы отменить автопост: удалите его файл (повторно он не появится, это
записано в posts/autoplan_state.json) или поменяйте status на draft.

Настройки (переменные окружения):
  AUTOPLAN=off        полностью выключить автопланирование
  AUTO_STATUS=draft   создавать посты черновиками (по умолчанию approved — публикуются сами)
  AUTOPLAN_DAYS=14    на сколько дней вперёд создавать посты

Запуск:
  python autoplan.py              создать недостающие посты
  python autoplan.py --dry-run    показать, что было бы создано
  python autoplan.py --now "2026-10-20 16:40"   подставить «текущее» время (для проверки)
"""
import argparse
import json
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

import publisher
from publisher import parse_post, save_meta

BASE = Path(__file__).resolve().parent
CONTENT = BASE / "content"
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
LEAD = timedelta(minutes=10)         # пост создаётся, только если до него больше 10 минут
COLLISION = timedelta(minutes=60)    # чужой пост ближе этого — слот считается занятым


# ---------- вспомогательное ----------

def load_json(name):
    return json.loads((CONTENT / name).read_text(encoding="utf-8"))


def one_line(value):
    return " ".join(str(value).replace("\r", " ").replace("\n", " ").split())


def sentence(text):
    text = one_line(text)
    return text if not text or text[-1] in ".!?…»)" else text + "."


def placement(fen):
    return (fen or "").split()[0]


def parse_dt(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=publisher.tz())


def fmt_dt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def write_post(path, header, body):
    lines = [f"{k}: {one_line(v)}" for k, v in header.items() if str(v).strip() != ""]
    path.write_text("\n".join(lines) + "\n\n" + body.strip() + "\n", encoding="utf-8")


def slot_free(dt, posts, ignore=None):
    for p in posts:
        if p["when"] is None or p["path"].name == ignore:
            continue
        if p["meta"].get("status") in ("cancelled", "skipped"):
            continue
        if abs(p["when"] - dt) < COLLISION:
            return False
    return True


# ---------- тексты постов ----------

class Texts:
    def __init__(self, cfg, cta):
        self.url = cfg["url"]
        self.cta = cta

    def next_cta(self, state):
        n = state["cta"] % len(self.cta)
        state["cta"] += 1
        return self.cta[n]

    def puzzle(self, pz, state):
        side = "Белые" if pz["side"] == "w" else "Чёрные"
        goal = pz["goal"][0].lower() + pz["goal"][1:]
        out = [f"♟ Задача дня: {goal}", "", f"{side} начинают и {pz['task']}."]
        if pz.get("intro"):
            out += [pz["intro"]]
        elif pz.get("caption"):
            out += [f"Позиция получилась после ходов: {pz['caption']}."]
        out += ["", "Найдите решение и напишите ответ в комментариях. Правильный ответ покажем завтра в 12:00.",
                "", self.next_cta(state)]
        return "\n".join(out)

    def answer(self, pz, state):
        out = ["✅ Ответ на вчерашнюю задачу", ""]
        expl = pz["explain"]
        if expl.startswith("Решение"):
            out.append(expl)
        else:
            out += [f"Правильный ход: {pz['san']}", "", expl]
        if pz.get("name") and pz["name"].lower() not in expl.lower():
            out += ["", f"📚 Знаменитая позиция: «{pz['name']}»."]
        out += ["", "Получилось найти решение? Расскажите в комментариях!", "", self.next_cta(state)]
        return "\n".join(out)

    def tips(self, tip, state):
        out = [f"♟ {tip['title']}", ""]
        for i, line in enumerate(tip["lines"], 1):
            main, _, detail = line.partition("::")
            out.append(f"{i}. {sentence(main)}" + (f" {sentence(detail)}" if detail else ""))
        if tip.get("note"):
            out += ["", sentence(tip["note"])]
        out += ["", self.next_cta(state)]
        return "\n".join(out)

    def fact(self, fact, state):
        out = ["💡 Шахматный факт", "", sentence(fact["title"])]
        if fact.get("note"):
            out.append(sentence(fact["note"]))
        out += ["", self.next_cta(state)]
        return "\n".join(out)

    def term(self, term, state):
        out = [f"📖 Шахматный термин: {term['title']}", "", sentence(term["definition"]), "",
               f"Пример: {sentence(term['example'])}", "", self.next_cta(state)]
        return "\n".join(out)

    def quiz(self, q, state):
        return "\n".join([f"❓ Вопрос дня: {q['title']}", "", f"А — {q['a']}", f"Б — {q['b']}", "",
                          "Голосуйте в комментариях: напишите А или Б. Можно объяснить свой выбор!"])

    def promo(self, promo, state):
        return promo["text"].replace("{url}", self.url)


def card_fields(kind, item, side_flip=None):
    """Поля шапки поста, из которых cards.py рисует картинку."""
    if kind == "puzzle":
        side_ru = "Белые" if item["side"] == "w" else "Чёрные"
        h = {"card": "puzzle", "title": "ЗАДАЧА ДНЯ", "subtitle": f"{side_ru} начинают и {item['task']}",
             "goal": item["goal"], "fen": item["fen"], "side": item["side"], "caption": item.get("caption", "")}
        if item["side"] == "b":
            h["flip"] = "yes"
        return h
    if kind == "tips":
        h = {"card": "tips", "title": item["title"], "lines": " | ".join(item["lines"]),
             "note": item.get("note", ""), "theme": item.get("theme", "")}
        return h
    if kind == "fact":
        return {"card": "fact", "title": item["title"], "note": item.get("note", ""), "piece": item.get("piece", "")}
    if kind == "term":
        return {"card": "term", "title": item["title"], "subtitle": item.get("subtitle", ""),
                "definition": item["definition"], "example": item["example"]}
    if kind == "quiz":
        return {"card": "quiz", "title": item["title"], "a": item["a"], "b": item["b"]}
    if kind == "promo":
        h = {"card": item["card"], "title": item["title"], "theme": item.get("theme", "")}
        for key in ("subtitle", "button", "url", "note", "kicker", "headline", "stub", "steps"):
            if item.get(key):
                h[key] = item[key]
        lines = item.get("lines", "")
        h["lines"] = " | ".join(lines) if isinstance(lines, list) else lines
        return h
    raise KeyError(kind)


# ---------- банки контента ----------

BANK_FILES = {"puzzle": "puzzles.json", "tips": "tips.json", "fact": "facts.json", "term": "terms.json",
              "quiz": "quiz.json", "promo": "promos.json"}


def pick_item(kind, banks, state, taken_fens, notes):
    """Следующий ещё не использованный элемент банка (когда банк кончился, идём по кругу)."""
    bank = banks[kind]
    used = state["used"].setdefault(kind, [])

    def free(it):
        if it["id"] in used:
            return False
        return not (kind == "puzzle" and placement(it["fen"]) in taken_fens)

    avail = [it for it in bank if free(it)]
    if not avail:
        notes.append(f"банк «{kind}» закончился, начинаю по кругу")
        state["used"][kind] = []
        used = state["used"][kind]
        avail = [it for it in bank if not (kind == "puzzle" and placement(it["fen"]) in taken_fens)] or bank
    item = avail[0]
    used.append(item["id"])
    return item


# ---------- основная логика ----------

def scan(posts_dir):
    posts = []
    for path in sorted(posts_dir.glob("*.md")):
        meta, body = parse_post(path)
        when = None
        if meta.get("when"):
            try:
                when = parse_dt(meta["when"])
            except ValueError:
                pass
        posts.append({"path": path, "meta": meta, "body": body, "when": when})
    return posts


def load_state(path):
    state = {}
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            state = {}
    state.setdefault("slots", {})
    state.setdefault("rot", {})
    state.setdefault("used", {})
    state.setdefault("answers", {})
    state.setdefault("cta", 0)
    return state


def plan(now, posts_dir, state_path, dry_run=False, status="approved", horizon_days=None):
    """Создаёт недостающие посты. Возвращает список (файл, время, описание) созданных."""
    cfg = load_json("schedule.json")
    banks = {k: load_json(v) for k, v in BANK_FILES.items()}
    texts = Texts(cfg, load_json("cta.json"))
    state = load_state(state_path)
    horizon = timedelta(days=float(horizon_days or cfg.get("horizon_days", 14)))
    posts = scan(posts_dir)
    by_fen = {placement(pz["fen"]): pz for pz in banks["puzzle"]}
    taken = {placement(p["meta"].get("fen", "")) for p in posts if p["meta"].get("card") == "puzzle"}
    notes, created = [], []

    def create(when, kind, item, header_extra, body):
        stem = f"{when.strftime('%Y-%m-%d')}-{kind}"
        name = f"{stem}.md"
        n = 2
        while (posts_dir / name).exists():
            name = f"{stem}-{n}.md"
            n += 1
        header = {"when": fmt_dt(when), "to": "telegram, vk", "status": status, "source": "auto"}
        header.update(header_extra)
        header.update(card_fields(kind, item) if kind != "answer" else {})
        path = posts_dir / name
        if not dry_run:
            write_post(path, header, body)
        posts.append({"path": path, "meta": {k: one_line(v) for k, v in header.items()}, "body": body, "when": when})
        created.append((name, when, header.get("title", kind), kind))
        return name

    # 1) слоты расписания
    day = now.date()
    last = (now + horizon).date()
    while day <= last:
        for slot in cfg["slots"]:
            if WEEKDAYS[day.weekday()] != slot["day"]:
                continue
            hh, mm = map(int, slot["time"].split(":"))
            when = datetime.combine(day, time(hh, mm), tzinfo=publisher.tz())
            key = f"{day.isoformat()}|{slot['day']}"
            if when <= now + LEAD or when > now + horizon or key in state["slots"]:
                continue
            if not slot_free(when, posts):
                continue
            kinds = slot["kind"] if isinstance(slot["kind"], list) else [slot["kind"]]
            start = state["rot"].get(slot["day"], 0)
            kind = kinds[start % len(kinds)]
            item = pick_item(kind, banks, state, taken, notes)
            state["rot"][slot["day"]] = start + 1
            if kind == "puzzle":
                taken.add(placement(item["fen"]))
            body = getattr(texts, kind)(item, state)
            name = create(when, kind, item, {"slot": key, "content": f"{kind}-{item['id']}"}, body)
            state["slots"][key] = name
        day += timedelta(days=1)

    # 2) ответы к задачам
    ans = cfg.get("answer", {"days_after": 1, "time": "12:00"})
    hh, mm = map(int, ans["time"].split(":"))
    for p in list(posts):
        meta = p["meta"]
        if meta.get("card") != "puzzle" or p["when"] is None or meta.get("status") not in ("approved", "sent"):
            continue
        pz = by_fen.get(placement(meta.get("fen", "")))
        if pz is None or p["path"].name in state["answers"]:
            continue
        when = datetime.combine((p["when"] + timedelta(days=ans["days_after"])).date(), time(hh, mm),
                                tzinfo=publisher.tz())
        if when <= now + LEAD or when > now + horizon + timedelta(days=ans["days_after"]):
            continue
        for _ in range(8):  # если время занято, сдвигаем на полчаса
            if slot_free(when, posts):
                break
            when += timedelta(minutes=30)
        else:
            continue
        flip = meta.get("flip", "")
        header = {"slot": f"answer|{p['path'].name}", "answer_for": p["path"].name, "content": f"answer-{pz['id']}",
                  "card": "answer", "title": "ОТВЕТ НА ЗАДАЧУ", "subtitle": "Вчерашняя задача",
                  "fen": pz["fen"], "move": pz["move"], "san": pz["san"], "result": pz["result"],
                  "mate": pz["mate"], "flip": flip, "targets": " ".join(pz.get("targets", []))}
        name = create(when, "answer", pz, header, texts.answer(pz, state))
        state["answers"][p["path"].name] = name

    # 3) ответ нужен только пока жива его задача
    live = {p["path"].name: p["meta"].get("status") for p in posts}
    for p in posts:
        src = p["meta"].get("answer_for")
        if src and p["meta"].get("status") == "approved" and live.get(src) not in ("approved", "sent"):
            if not dry_run:
                save_meta(p["path"], {"status": "cancelled"})
            notes.append(f"{p['path'].name}: задача «{src}» отменена, ответ на неё тоже")

    if not dry_run and (created or notes):
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return created, notes


def summary_text(created, notes):
    out = [f"🗓 Бот запланировал новых постов: {len(created)}", ""]
    for name, when, title, kind in sorted(created, key=lambda c: c[1]):
        out.append(f"• {WEEKDAYS_RU[when.weekday()]} {when.strftime('%d.%m %H:%M')} — {title}")
    out += ["", "Чтобы отменить пост, удалите его файл в папке posts на GitHub."]
    out += [f"⚠️ {n}" for n in notes]
    return "\n".join(out)


def notify_owner(text):
    token, owner = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_OWNER_ID")
    if not token or not owner:
        return
    try:
        import requests
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": owner, "text": text[:4000]}, timeout=30)
    except Exception as exc:  # уведомление не обязательно
        print(f"не удалось отправить сводку в личку: {exc}", file=sys.stderr)


def main():
    publisher.load_env()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="ничего не создавать, только показать")
    parser.add_argument("--now", help='подставить текущее время, "ГГГГ-ММ-ДД ЧЧ:ММ" (для проверки)')
    args = parser.parse_args()
    if os.getenv("AUTOPLAN", "on").strip().lower() in ("off", "0", "no", "нет"):
        print("Автопланирование выключено (AUTOPLAN=off).")
        return
    status = "draft" if os.getenv("AUTO_STATUS", "").strip().lower() == "draft" else "approved"
    now = parse_dt(args.now) if args.now else datetime.now(publisher.tz())
    posts_dir = publisher.POSTS_DIR
    created, notes = plan(now, posts_dir, posts_dir / "autoplan_state.json", dry_run=args.dry_run,
                          status=status, horizon_days=os.getenv("AUTOPLAN_DAYS") or None)
    for name, when, title, kind in sorted(created, key=lambda c: c[1]):
        print(f"{'[dry-run] ' if args.dry_run else ''}создан {name}  ({fmt_dt(when)}, {kind}: {title})")
    for n in notes:
        print("внимание:", n)
    if not created and not notes:
        print("Автопланирование: новых постов не нужно.")
    elif created and not args.dry_run:
        notify_owner(summary_text(created, notes))


if __name__ == "__main__":
    main()
