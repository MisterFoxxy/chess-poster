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

ВКонтакте: ключ сообщества не умеет прикреплять картинки к записям на стене,
поэтому действует схема «текст в отложку, картинка в личку»:
  * за VK_SCHEDULE_DAYS дней (по умолчанию 14) до времени when текст поста
    ставится в ОТЛОЖЕННЫЕ записи группы без картинки, дальше ВК публикует его сам;
  * картинка в этот момент приходит владельцу в личку Telegram (TELEGRAM_OWNER_ID)
    со ссылкой на запись, её остаётся прикрепить к записи вручную в ВК;
  * если время поста уже наступило, запись выходит сразу, картинку можно
    добавить через «Редактировать».
Старый способ (попытка прикрепить картинку) включается VK_IMAGE_MODE=attach.

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


def send_image_to_owner(image, caption):
    """Присылает картинку владельцу в личные сообщения Telegram (бот пишет ему сам,
    для этого владелец один раз должен нажать «Start» в чате с ботом)."""
    import requests

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    owner = os.environ["TELEGRAM_OWNER_ID"]
    with open(image, "rb") as f:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": owner, "caption": caption[:TG_CAPTION_LIMIT]},
            files={"photo": f},
            timeout=60,
        )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram (личка): {data.get('description')}")


# ---------- ВКонтакте ----------

def vk_call(method, **params):
    import requests

    params["access_token"] = os.environ["VK_TOKEN"]
    params["v"] = VK_VERSION
    data = requests.post(VK_API + method, data=params, timeout=30).json()
    if "error" in data:
        raise RuntimeError(f"VK {method}: {data['error'].get('error_msg')}")
    return data["response"]


def _vk_photo_wall(group_id, image):
    """Загрузка на стену. В ВК работает только с ключом пользователя, не сообщества."""
    import requests

    server = vk_call("photos.getWallUploadServer", group_id=group_id)
    with open(image, "rb") as f:
        uploaded = requests.post(server["upload_url"], files={"photo": f}, timeout=60).json()
    saved = vk_call(
        "photos.saveWallPhoto",
        group_id=group_id,
        photo=uploaded["photo"],
        server=uploaded["server"],
        hash=uploaded["hash"],
    )[0]
    return f"photo{saved['owner_id']}_{saved['id']}"


def _vk_photo_album(group_id, image, album_id):
    """Загрузка в альбом группы (может работать с ключом сообщества). Нужен VK_ALBUM_ID."""
    import requests

    server = vk_call("photos.getUploadServer", album_id=int(album_id), group_id=group_id)
    with open(image, "rb") as f:
        uploaded = requests.post(server["upload_url"], files={"file1": f}, timeout=60).json()
    saved = vk_call(
        "photos.save",
        album_id=int(album_id),
        group_id=group_id,
        server=uploaded["server"],
        photos_list=uploaded["photos_list"],
        hash=uploaded["hash"],
    )[0]
    return f"photo{saved['owner_id']}_{saved['id']}"


def _vk_photo_messages(group_id, image):
    """Загрузка как фото для сообщений сообщества. Часто разрешена ключу группы;
    потом пробуем прикрепить это фото к записи на стене."""
    import requests

    server = vk_call("photos.getMessagesUploadServer")
    with open(image, "rb") as f:
        uploaded = requests.post(server["upload_url"], files={"photo": f}, timeout=60).json()
    saved = vk_call(
        "photos.saveMessagesPhoto",
        photo=uploaded["photo"],
        server=uploaded["server"],
        hash=uploaded["hash"],
    )[0]
    key = f"_{saved['access_key']}" if saved.get("access_key") else ""
    return f"photo{saved['owner_id']}_{saved['id']}{key}"


def _vk_doc_wall(group_id, image):
    """Загрузка картинки как документа для стены (часто разрешена ключу сообщества).
    Нужно право «документы» у ключа. В записи выглядит как прикреплённый файл с превью."""
    import requests

    server = vk_call("docs.getWallUploadServer", group_id=group_id)
    with open(image, "rb") as f:
        uploaded = requests.post(server["upload_url"], files={"file": f}, timeout=60).json()
    if "file" not in uploaded:
        raise RuntimeError(f"VK docs upload: {uploaded}")
    saved = vk_call("docs.save", file=uploaded["file"], title=Path(image).stem)
    doc = saved.get("doc", saved) if isinstance(saved, dict) else saved[0]
    return f"doc{doc['owner_id']}_{doc['id']}"


def vk_upload_photo(group_id, image):
    """Пробует способы по очереди и возвращает строку-вложение (или бросает ошибку со всеми причинами).
    Документ (выглядит как файл, а не как картинка) включается только если VK_ALLOW_DOC=1."""
    errors = []
    methods = [("стена", lambda: _vk_photo_wall(group_id, image))]
    album_id = os.getenv("VK_ALBUM_ID")
    if album_id:
        methods.append(("альбом", lambda: _vk_photo_album(group_id, image, album_id)))
    methods.append(("сообщения", lambda: _vk_photo_messages(group_id, image)))
    if os.getenv("VK_ALLOW_DOC") == "1":
        methods.append(("документ", lambda: _vk_doc_wall(group_id, image)))
    for name, fn in methods:
        try:
            return fn()
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError(" | ".join(errors))


def send_vk(text, image, publish_ts=None):
    """Публикует запись на стене группы. С publish_ts (unixtime) запись становится
    отложенной: ВК сам опубликует её в это время, компьютер уже не нужен.
    По умолчанию запись идёт БЕЗ картинки (картинку владелец получает в личку Telegram).
    С VK_IMAGE_MODE=attach пробует прикрепить; не вышло, запись идёт без неё."""
    group_id = int(os.environ["VK_GROUP_ID"])
    params = {"owner_id": -group_id, "from_group": 1, "message": text}
    if publish_ts:
        params["publish_date"] = int(publish_ts)
    attachment = None
    if image and os.getenv("VK_IMAGE_MODE", "dm").strip().lower() == "attach":
        try:
            attachment = vk_upload_photo(group_id, image)
        except Exception as exc:
            print(f"[VK] картинку прикрепить не удалось, публикуем без неё: {exc}", file=sys.stderr)
    if attachment:
        try:
            return vk_call("wall.post", attachments=attachment, **params).get("post_id")
        except Exception as exc:
            print(f"[VK] запись с картинкой не принята ({exc}), публикуем без неё", file=sys.stderr)
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


def vk_ahead():
    """За сколько дней до времени поста его текст ставится в отложенные записи ВК."""
    try:
        return timedelta(days=float(os.getenv("VK_SCHEDULE_DAYS", "14")))
    except ValueError:
        return timedelta(days=14)


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
    if vk_post:
        lines.append(f"https://vk.com/wall-{os.environ['VK_GROUP_ID']}_{vk_post}")
    return "\n".join(lines)


def run(dry_run):
    now = datetime.now(tz())
    sent_any = False
    for path, meta, body in iter_posts():
        if meta.get("status") != "approved" or "when" not in meta:
            continue
        when = parse_when(meta["when"])
        due = when <= now
        targets = targets_of(meta)
        done = done_of(meta)

        # что нужно сделать с этим постом в этот запуск
        todo = []
        for target in targets:
            if target in done:
                continue
            if due:
                todo.append(target)
            elif target == "vk" and now + timedelta(minutes=2) < when <= now + vk_ahead():
                todo.append(target)  # заранее, в отложенные записи ВК
        has_pic = bool(meta.get("image") or meta.get("card"))
        dm_pending = "vk" in done and has_pic and meta.get("vk_image_dm") != "yes"
        if not todo and not dm_pending:
            if due and set(targets) <= set(done):
                if not dry_run:
                    save_meta(path, {"status": "sent", "sent_at": now.strftime("%Y-%m-%d %H:%M")})
            continue

        image, image_path = None, None
        try:
            image, image_path = resolve_image(path, meta)
        except Exception as exc:
            print(f"[{path.name}] картинка: {exc}", file=sys.stderr)
            continue

        vk_post = meta.get("vk_post")
        for target in todo:
            if target not in SENDERS:
                print(f"[{path.name}] неизвестный канал: {target}", file=sys.stderr)
                continue
            scheduled = target == "vk" and not due
            if dry_run:
                how = "в отложенные записи на " + meta["when"] if scheduled else "сразу"
                print(f"[dry-run] {path.name} -> {target} ({how}): {len(body)} симв., картинка: {image or 'нет'}")
                print("    " + body[:120].replace("\n", " ") + ("..." if len(body) > 120 else ""))
                continue
            missing = [k for k in REQUIRED_ENV[target] if not os.getenv(k)]
            if missing:
                print(f"[{path.name}] нет настроек для {target}: {', '.join(missing)}", file=sys.stderr)
                continue
            try:
                if target == "vk":
                    vk_post = send_vk(body, image_path, publish_ts=when.timestamp() if scheduled else None)
                else:
                    SENDERS[target](body, image_path)
            except Exception as exc:  # одна ошибка не должна ронять остальные посты
                print(f"[{path.name}] ошибка отправки в {target}: {exc}", file=sys.stderr)
                continue
            done.append(target)
            sent_any = True
            updates = {"sent_to": ",".join(done)}
            if target == "vk":
                updates["vk_post"] = str(vk_post)
                print(f"[{path.name}] ВК: " + (f"поставлено в отложку на {meta['when']}" if scheduled
                                               else "опубликовано сразу") + f" (запись {vk_post})")
            else:
                print(f"[{path.name}] отправлено в {target}")
            save_meta(path, updates)

        # картинка для ВК уходит владельцу в личку Telegram
        dm_failed = False
        vk_handled = "vk" in done or (dry_run and "vk" in todo)
        if vk_handled and image_path and meta.get("vk_image_dm") != "yes":
            if os.getenv("VK_IMAGE_MODE", "dm").strip().lower() == "attach":
                pass  # картинку пытались прикрепить сами, личка не нужна
            elif dry_run:
                print(f"[dry-run] {path.name}: картинка для ВК придёт владельцу в личку Telegram")
            elif not os.getenv("TELEGRAM_OWNER_ID"):
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
