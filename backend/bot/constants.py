# ── Apps by OS ────────────────────────────────────────────────────────────────
# Each key is an OS name; each value is a list of apps.
# Fields: name (str), url (str), note (str, optional).

APPS: dict[str, list[dict]] = {
    "iOS": [
        {"name": "Arpeggi",   "url": "https://example.com/arpeggi",  "note": "Красивый и удобный плеер. Доступен бесплатно через TestFlight."},
        {"name": "Nautiline", "url": "https://example.com/nautiline", "note": "Полнофункциональный iOS-клиент. Единоразовая покупка без подписок."},
    ],
    "Android": [
        {"name": "Symfonium", "url": "https://example.com/symfonium"},
    ],
    "Desktop (Windows, macOS, Linux)": [
        {"name": "Aonsoku", "url": "https://example.com/aonsoku"},
    ],
}


def _build_apps_text() -> str:
    lines = ["Список приложений для разных операционных систем (ты можешь выбрать любое)"]
    for os_name, apps in APPS.items():
        lines.append(f"\n<b>{os_name}</b>\n──────────────")
        for app in apps:
            link = f'<a href="{app["url"]}">{app["name"]}</a>'
            lines.append(link)
            if app.get("note"):
                lines.append(app["note"])
    lines.append(
        '\nПомимо этих приложений, ты можешь выбрать любое из списка на официальном сайте Navidrome: '
        '<a href="https://www.navidrome.org/apps/">https://www.navidrome.org/apps/</a>'
    )
    return "\n".join(lines)


TEXT_APPLICATIONS_LIST = _build_apps_text()

TEXT_NOW_PLAYING = """🎵 <b>Поделиться треком в любом чате</b>

Ты можешь отправить текущий играющий трек прямо в любой чат — личный или групповой.

Для этого в поле ввода сообщения напиши <code>@{bot_username}</code> и нажми на появившийся трек.

Telegram отправит аудио собеседнику — без необходимости пересылать файл вручную.
"""

TEXT_UPLOAD_MUSIC = """Ты можешь загрузить любую свою музыку на сервер при помощи специального сайта, который я сделал.

Загрузить музыку можно двумя способами.

1. Из файлов
Загружайте MP3, FLAC, AAC и другие форматы прямо с вашего устройства.

2. По ссылке из SoundCloud
Просто вставьте ссылку — сервис сам скачает трек и заполнит все данные.

Ссылка на сайт: https://upload.redheadflag.com/
"""
