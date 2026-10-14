#!/usr/bin/env python3
"""
Публикатор постов для Telegram и ВКонтакте (шахматные турниры и школа).

Как работает:
  * Каждый пост — отдельный файл .md в папке posts/.
  * Скрипт запускается по расписанию (например, раз в 5 минут).
  * Публикуются только посты со status: approved, у которых наступило время when.
  * После отправки в файле обновляются поля sent_to и status.

Запуск:
  python publisher.py            # сделать то, что пора
  python publisher.py --dry-run  # показать, что было бы сделано, ничего не отправляя
  python publisher.py --list     # показать очередь

Telegram: пост с картинкой уходит в канал, когда наступило время when.

ВКонтакте: ключ сообщества не умеет прикреплять картинки к записям на стене.
Поэтому по умолчанию (VK_MODE=schedule) действует схема «текст в отложку, картинка в личку»:
  * за VK_AHEAD_DAYS дней (по умолчанию 14) до времени when текст поста ставится в
    ОТЛОЖЕННЫЕ записи группы без картинки, дальше ВК публикует его сам;
  * картинка в этот момент приходит владельцу в личку Telegram (TELEGRAM_OWNER_ID)
    со ссылкой на запись, её остаётся прикрепить вручную («Редактировать»);
  * если ВК запись не принял, бот присылает владельцу в личку полный пост
    (картинку и текст) с причиной, и владелец публикует его сам;
  * если время поста уже наступило, запись выходит в ВК сразу.
Режим VK_MODE=manual: бот ничего не пишет в ВК, а за VK_AHEAD_DAYS (по умолчанию 3)
дней присылает владельцу полный пост в личку.

Картинка к посту: либо готовый файл (поле image:), либо автоматическая
карточка из полей поста (поле card:, см. cards.py и README). Если указан
и image:, и card:, берётся image:. При --dry-run автокарточка тоже
создаётся (posts/img/auto/), чтобы её можно было посмотреть до отправки.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
POSTS_DIR = BASE / "posts"
VK_API = "https://api.vk.com/method/"
VK_VERSION = "5.199"
TG_CAPTION_LIMIT = 1024


# ---------- настройки ----------

def load_env():
    """Читает файл .env рядом со скриптом (KEY=value), не затирая уже заданные переменные."""
    env_file = BASE / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def tz():
    return ZoneInfo(os.getenv("POST_TZ", "Europe/Moscow"))


# ---------- разбор файлов постов ----------

def parse_post(path):
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    head, _, body = raw.partition("\n\n")
    meta = {}
    for line in head.splitlines():
        if line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip()
    return meta, body.strip()


def save_meta(path, updates):
    """Обновляет поля в шапке файла, остальное не трогает."""
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    head, sep, body = raw.partition("\n\n")
    lines = head.splitlines()
    for key, value in updates.items():
        for i, line in enumerate(lines):
            if line.lower().startswith(key + ":"):
                lines[i] = f"{key}: {value}"
                break
        else:
            lines.append(f"{key}: {value}")
    path.write_text("\n".join(lines) + sep + body, encoding="utf-8")


def parse_when(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=tz())


def targets_of(meta):
    return [t.strip().lower() for t in meta.get("to", "telegram,vk").split(",") if t.strip()]


def done_of(meta):
    return [t.strip().lower() for t in meta.get("sent_to", "").split(",") if t.strip()]


# ---------- Telegram ----------

def send_telegram(text, image):
    import requests

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    api = f"https://api.telegram.org/bot{token}/"

    def check(resp):
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram: {data.get('description')}")

    if image:
        caption = text if len(text) <= TG_CAPTION_LIMIT else ""
        with open(image, "rb") as f:
            resp = requests.post(
                api + "sendPhoto",
                data={"chat_id": chat_id, "caption": caption},
                files={"photo": f},
                timeout=60,
            )
        check(resp)
        if caption:
            return
    resp = requests.post(api + "sendMessage", data={"chat_id": chat_id, "text": text}, timeout=30)
    check(resp)


def _owner_api():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    return os.environ["TELEGRAM_OWNER_ID"], f"https://api.telegram.org/bot{token}/"


def _check(resp):
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram (личка): {data.get('description')}")


def send_vk_manual(text, image, when, due, reason=None):
    """Присылает владельцу в личку Telegram полный пост для ВК: картинку (с короткой пометкой)
    и отдельным сообщением чистый текст, который удобно скопировать целиком.
    Бот пишет в личку сам, для этого владелец один раз должен нажать «Start» у бота."""
    import requests

    owner, api = _owner_api()
    when_s = when.strftime("%d.%m в %H:%M")
    if due:
        head = f"📣 Пост для ВК. Время публикации уже наступило ({when_s} МСК), опубликуйте сейчас."
    else:
        head = (f"📣 Пост для ВК на {when_s} (МСК). Ниже картинка, а следующим сообщением текст. "
                "Опубликуйте или поставьте в отложенные записи ВК на это время.")
    if reason:
        head += f"\n⚠️ Бот сам поставить запись в ВК не смог: {reason}"
    head = head[:TG_CAPTION_LIMIT]
    if image:
        with open(image, "rb") as f:
            _check(requests.post(api + "sendPhoto", data={"chat_id": owner, "caption": head},
                                 files={"photo": f}, timeout=60))
    else:
        _check(requests.post(api + "sendMessage", data={"chat_id": owner, "text": head}, timeout=30))
    for i in range(0, len(text), 4000):  # лимит сообщения Telegram 4096
        _check(requests.post(api + "sendMessage",
                             data={"chat_id": owner, "text": text[i:i + 4000]}, timeout=30))


def send_image_to_owner(image, caption):
    """Присылает владельцу в личку только картинку (текст уже стоит в отложке ВК)."""
    import requests

    owner, api = _owner_api()
    with open(image, "rb") as f:
        _check(requests.post(api + "sendPhoto",
                             data={"chat_id": owner, "caption": caption[:TG_CAPTION_LIMIT]},
                             files={"photo": f}, timeout=60))


# ---------- ВКонтакте ----------

def vk_call(method, **params):
    import requests

    params["access_token"] = os.environ["VK_TOKEN"]
    params["v"] = VK_VERSION
    data = requests.post(VK_API + method, data=params, timeout=30).json()
    if "error" in data:
        raise RuntimeError(f"VK {method}: {data['error'].get('error_msg')}")
    return data["response"]


def send_vk(text, publish_ts=None):
    """Запись на стене группы (только текст: ключ сообщества не может прикрепить картинку).
    С publish_ts (unixtime) запись становится отложенной: ВК сам опубликует её в это время.
    Возвращает id записи."""
    group_id = int(os.environ["VK_GROUP_ID"])
    params = {"owner_id": -group_id, "from_group": 1, "message": text}
    if publish_ts:
        params["publish_date"] = int(publish_ts)
    return vk_call("wall.post", **params).get("post_id")


SENDERS = {"telegram": send_telegram, "vk": send_vk}
REQUIRED_ENV = {
    "telegram": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
    "vk": ["VK_TOKEN", "VK_GROUP_ID"],
}


# ---------- основная логика ----------

def iter_posts():
    for path in sorted(POSTS_DIR.glob("*.md")):
        meta, body = parse_post(path)
        yield path, meta, body


def show_queue():
    now = datetime.now(tz())
    for path, meta, _ in iter_posts():
        when = meta.get("when", "?")
        mark = ""
        if meta.get("status") == "approved" and "when" in meta and parse_when(meta["when"]) <= now:
            mark = "  <- пора публиковать"
        print(f"{path.name:40} {meta.get('status', '?'):9} {when:17} -> {meta.get('to', 'telegram,vk')}{mark}")


def resolve_image(path, meta):
    """Возвращает (подпись, путь к файлу) для картинки поста или (None, None); ошибка -> исключение."""
    image = meta.get("image")
    if image:
        image_path = (path.parent / image).resolve()
        if not image_path.exists():
            raise FileNotFoundError(f"картинка не найдена: {image}")
        return image, str(image_path)
    if meta.get("card"):
        from cards import make_card
        out = make_card(meta, path.parent / "img" / "auto" / (path.stem + ".png"))
        return "авто: " + Path(out).name, str(out)
    return None, None


def vk_mode():
    """schedule (по умолчанию): текст в отложку ВК, картинка в личку; manual: весь пост в личку."""
    return "manual" if os.getenv("VK_MODE", "schedule").strip().lower() == "manual" else "schedule"


def ahead_window():
    """За сколько дней до публикации бот занимается постом для ВК."""
    default = "3" if vk_mode() == "manual" else "14"
    try:
        return timedelta(days=float(os.getenv("VK_AHEAD_DAYS") or default))
    except ValueError:
        return timedelta(days=float(default))


def required_env(target):
    if target == "vk":
        return ["TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_ID"] if vk_mode() == "manual" else REQUIRED_ENV["vk"]
    return REQUIRED_ENV[target]


def run(dry_run):
    now = datetime.now(tz())
    sent_any = False
    owner_ok = bool(os.getenv("TELEGRAM_OWNER_ID"))
    for path, meta, body in iter_posts():
        if meta.get("status") != "approved" or "when" not in meta:
            continue
        when = parse_when(meta["when"])
        due = when <= now
        targets = targets_of(meta)
        done = done_of(meta)
        vk_post = meta.get("vk_post")

        # что нужно сделать с этим постом в этот запуск
        todo = []
        for target in targets:
            if target in done:
                continue
            if due:
                todo.append(target)
            elif target == "vk":
                # заранее; для отложки ВК время должно быть хоть немного в будущем
                lead = timedelta(minutes=2) if vk_mode() == "schedule" else timedelta(0)
                if now + lead < when <= now + ahead_window():
                    todo.append(target)
        has_pic = bool(meta.get("image") or meta.get("card"))
        dm_pending = ("vk" in done and bool(vk_post) and has_pic and owner_ok
                      and meta.get("vk_image_dm") != "yes")
        if not todo and not dm_pending:
            if due and set(targets) <= set(done) and not dry_run:
                save_meta(path, {"status": "sent", "sent_at": now.strftime("%Y-%m-%d %H:%M")})
            continue

        try:
            image, image_path = resolve_image(path, meta)
        except Exception as exc:
            print(f"[{path.name}] картинка: {exc}", file=sys.stderr)
            continue

        for target in todo:
            if target not in SENDERS:
                print(f"[{path.name}] неизвестный канал: {target}", file=sys.stderr)
                continue
            scheduled = target == "vk" and not due
            if dry_run:
                if target == "vk" and vk_mode() == "manual":
                    how = "весь пост вам в личку (публикуете сами)"
                elif target == "vk":
                    how = ("в отложенные записи на " + meta["when"]) if scheduled else "сразу"
                    how += ", картинка вам в личку"
                else:
                    how = "публикация"
                print(f"[dry-run] {path.name} -> {target} ({how}): {len(body)} симв., картинка: {image or 'нет'}")
                print("    " + body[:120].replace("\n", " ") + ("..." if len(body) > 120 else ""))
                continue
            missing = [k for k in required_env(target) if not os.getenv(k)]
            if missing:
                print(f"[{path.name}] нет настроек для {target}: {', '.join(missing)}", file=sys.stderr)
                continue
            updates = {}
            try:
                if target == "telegram":
                    send_telegram(body, image_path)
                    note = "отправлено в telegram"
                elif vk_mode() == "manual":
                    send_vk_manual(body, image_path, when, due)
                    note = "ВК: весь пост отправлен вам в личку Telegram"
                else:
                    try:
                        vk_post = send_vk(body, publish_ts=when.timestamp() if scheduled else None)
                        updates["vk_post"] = str(vk_post)
                        note = (f"ВК: поставлено в отложку на {meta['when']}" if scheduled
                                else "ВК: опубликовано сразу") + f" (запись {vk_post})"
                    except Exception as vk_exc:
                        if not owner_ok:
                            raise
                        # ВК запись не принял: отдаём владельцу полный пост, чтобы он ничего не потерял
                        print(f"[{path.name}] ВК не принял запись: {vk_exc}", file=sys.stderr)
                        send_vk_manual(body, image_path, when, due, reason=str(vk_exc))
                        updates["vk_manual"] = "yes"
                        vk_post = None
                        note = "ВК: запись не принята, полный пост отправлен вам в личку Telegram"
            except Exception as exc:  # одна ошибка не должна ронять остальные посты
                print(f"[{path.name}] ошибка отправки в {target}: {exc}", file=sys.stderr)
                continue
            done.append(target)
            sent_any = True
            updates["sent_to"] = ",".join(done)
            save_meta(path, updates)
            print(f"[{path.name}] {note}")

        # картинка для записи, которую бот поставил в ВК, уходит владельцу в личку Telegram
        dm_failed = False
        if "vk" in done and vk_post and image_path and meta.get("vk_image_dm") != "yes":
            if dry_run:
                print(f"[dry-run] {path.name}: картинка придёт вам в личку Telegram")
            elif not owner_ok:
                print(f"[{path.name}] картинка для ВК не отправлена: не задан TELEGRAM_OWNER_ID", file=sys.stderr)
            else:
                try:
                    send_image_to_owner(image_path, owner_caption(body, when, when > now, vk_post))
                    save_meta(path, {"vk_image_dm": "yes"})
                    sent_any = True
                    print(f"[{path.name}] картинка для ВК отправлена в личку")
                except Exception as exc:
                    dm_failed = True
                    print(f"[{path.name}] не удалось отправить картинку в личку: {exc}", file=sys.stderr)

        if not dry_run and due and set(targets) <= set(done) and not dm_failed:
            save_meta(path, {"status": "sent", "sent_at": now.strftime("%Y-%m-%d %H:%M")})

    if not sent_any and not dry_run:
        print("Нечего публиковать.")


def owner_caption(body, when, scheduled, vk_post):
    """Подпись к картинке, которую владелец получает в личку."""
    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    if len(first) > 80:
        first = first[:77] + "…"
    lines = ["🖼 Картинка для поста в ВК", f"«{first}»", f"Время публикации: {when.strftime('%d.%m %H:%M')} (МСК)"]
    if scheduled:
        lines.append("Текст уже стоит в отложенных записях группы. Откройте запись, "
                     "нажмите «Редактировать», прикрепите эту картинку и сохраните.")
    else:
        lines.append("Запись уже опубликована без картинки. Откройте её, нажмите "
                     "«Редактировать» и прикрепите эту картинку.")
    lines.append(f"https://vk.com/wall-{os.environ['VK_GROUP_ID']}_{vk_post}")
    return "\n".join(lines)


def main():
    load_env()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="ничего не отправлять, только показать")
    parser.add_argument("--list", action="store_true", help="показать очередь постов")
    args = parser.parse_args()
    if args.list:
        show_queue()
    else:
        run(args.dry_run)


if __name__ == "__main__":
    main()
