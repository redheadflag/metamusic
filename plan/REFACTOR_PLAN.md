# План рефакторинга metamusic

## 1. Контекст проекта (коротко)

- **backend/** — FastAPI + ARQ worker. Принимает файлы, SoundCloud URL,
  YouTube плейлисты. Складывает треки в SFTP: `<SFTP_BASE>/<artist>/<album>/<file>`.
  Рядом пишет `.album` control file (`needs_processing`, `is_processed`) и
  `cover.jpg`.
- **processor_service/** — отдельный контейнер. Поллит SFTP, конвертирует
  файлы с разными расширениями в доминирующее.
- **backend/bot/** — Telegram бот (aiogram).
- **frontend/** — React + Vite.
- **fix-artists.sh** (и дубль `backend/fix-artists.sh`) — zsh + Python helper.
  Разбивает multi-value артистов в тегах (mp3, flac, ogg, opus, m4a, aac).
- Все скачки идут через SFTP напрямую в папку альбома (кода с
  `unprocessed/` больше нет в проекте — прошлый рефакторинг уже убрал этот
  префикс. Нужно проверить и удалить любые остатки семантики "Single"-папок).

### Что нужно изменить (из запроса пользователя)

1. **Скачивание треков → корень указанной папки**: треки-синглы сейчас идут
   в `<artist>/<Title> (Single)/<Title>.mp3`. Пользователь хочет, чтобы они
   ложились сразу в `<artist>/<Title>.mp3` (без псевдо-альбомной папки).
2. **Переписать `fix-artists.sh` на Python**, сохранив всю текущую логику и
   добавив санитайзер m4a-файлов с двумя аудио/видео-стримами (первый
   аудио оставляем, видео помечаем `attached_pic`). **Путь файла не меняется**
   — замена in-place. Скрипт должен вызываться для каждого трека,
   загружаемого через сайт.
3. **Загрузка через сайт (SoundCloud, файлы)**:
   - Убрать префикс `(Single)` из названия альбома/папки одиночных треков.
   - Не добавлять `(feat. ...)` в title. Вместо этого записывать всех
     артистов в тег artist как multi-value (как делает `fix-artists.sh`).
   - UI: на фронтенде добавить редактор артистов (список с
     добавлением/удалением/drag-to-reorder).
4. **YouTube плейлисты**:
   - Треки, не найденные в Navidrome, не качаются на сервере сразу. Вместо
     этого пишутся в очередь (sqlite) как "pending". Worker на локальной
     машине пользователя подтягивает pending, качает, обрабатывает,
     заливает по SFTP и помечает как done.
   - Треки, найденные в Navidrome (или помеченные `skip`), сразу попадают
     в плейлист Navidrome — без скачивания.

---

## 2. Детальный план реализации

### Этап A — Python-версия fix-artists.sh

**Новый файл:** `backend/fix_artists.py` (подчёркивание, не дефис — чтобы
можно было импортировать как модуль).

- Все константы (`SUPPORTED_EXT`, `SEPARATORS`) → модульные глобалы.
- Публичный API:
  - `process_file(path: str, dry_run: bool = False) -> bool` — обрабатывает
    один файл: split артистов + sanitize m4a стримов. True если что-то
    изменилось.
  - `process_directory(root: str, dry_run: bool = False) -> dict` — рекурсивный
    обход. Counters: scanned, changed, skipped. Для совместимости с CLI.
  - `sanitize_m4a_streams(path: str) -> bool` — если файл `.m4a` содержит
    ≥2 аудио-стрима **или** видео-стрим без `attached_pic` disposition,
    запускаем `ffmpeg -i in -map 0:a:0 -map 0:v:0 -c copy
    -disposition:v:0 attached_pic out.m4a`, перезаписываем in-place через
    atomic `os.replace`. Если видео-стрима нет — только `-map 0:a:0`.
    Возвращает True, если файл был переписан.
  - `split_artist_tag(path: str, dry_run: bool = False) -> bool` — текущая
    логика `process_field` (artist + album_artist + solo-album heuristic).
- Зависимости: `mutagen` (уже в `backend/requirements.txt`), `ffmpeg`/
  `ffprobe` (уже в Dockerfile).
- CLI обёртка в `if __name__ == "__main__":` — `python3 fix_artists.py
  [path] [--write]` с тем же UX, что у старого zsh-скрипта.
- **Удалить** `fix-artists.sh` и `backend/fix-artists.sh` после миграции.
- **Обновить** `backend/Dockerfile`: убрать `zsh` из `apt-get install`
  (остаётся только `ffmpeg`).
- **Обновить** `backend/youtube/downloader.py::run_fix_artists`:
  переименовать функцию в `fix_track(path)`, вызывать
  `fix_artists.process_file(path, dry_run=False)` напрямую (один трек,
  не директория).
- **Обновить** все места, где зовётся санитайзер:
  - `backend/soundcloud/downloader.py::sanitize_m4a_streams` сохраняет
    текущую сигнатуру, но внутри делегирует в `fix_artists.sanitize_m4a_streams`.
    После миграции можно удалить дубликат.
  - `backend/processing.py::process_album` — вызывает `fix_artists.process_file`
    вместо `sanitize_m4a_streams` + `embed_tags` по отдельности
    (fix_artists работает *после* embed, чтобы разбить свежезаписанный
    artist-тег).
- **Обновить** `backend/worker/main.py::yt_import_task` — убрать
  `run_fix_artists(tmp_dir)`, звать `fix_artists.process_file(mp3_path)` на
  конкретный файл.

**Критерии готовности этапа A:** старый zsh-скрипт удалён; все места,
вызывавшие его, работают через Python-модуль; `docker compose build
backend` не требует `zsh`.

---

### Этап B — Загрузка в корень, без (Single)-папки

**Задача:** синглы ложатся в `<SFTP_BASE>/<artist>/<title>.<ext>`, а не в
`<SFTP_BASE>/<artist>/<title> (Single)/<title>.<ext>`.

1. **`backend/services/sftp.py`** — добавить helper:
   ```python
   def track_path(artist: str, filename: str) -> str:
       return str(PurePosixPath(SFTP_BASE) / artist / filename)
   ```

2. **`backend/processing.py::process_album`** (и `process_sc_album`):
   - Если `req.is_single`:
     - Ветка: заливаем каждый трек в `track_path(artist, fname)`.
     - `.album` и `cover.jpg` **не пишем** для синглов (их "альбомом"
       будет сама папка артиста, а cover берётся из эмбеда в файл).
   - Иначе — текущая логика с `album_path(...)`.
   - Убрать `req = req.model_copy(update={"album": f"{req.tracks[0].title} (Single)"})`.
     В режиме single мы больше не сочиняем фейковое имя альбома;
     передаём `album=""` (или title трека, если нужно для тегов — см.
     соображение ниже).

3. **Решение про `album` в тегах single-трека:**
   - Навидром без заполненного album будет показывать трек в "Non-album
     tracks". Это OK по запросу пользователя. В тег `TALB`/`album`
     пишем пустую строку.

4. **`backend/worker/main.py::yt_import_task`** — текущий код строит
   `album_name = f"{title} (Single)"`. Заменить на:
   ```python
   remote = track_path(_safe(track.artist), _safe(track.title) + ext)
   upload_file(mp3_path, remote)
   # .album НЕ пишем — это сингл в корне артиста
   ```

5. **`backend/processing.py::process_bulk_task`** — для `is_single` альбомов
   (которых сейчас нет в bulk, но на будущее) та же ветка.

6. **Frontend `MetaEditor.jsx`** — блок с подсказкой
   `"Album name will be set to <title> (Single)"` удалить (а вместе с ним
   i18n ключи `singleHint`, `singleHintSuffix`). Для single-режима
   `album` просто не отправляется.

7. **Processor service** — `full_sync` / `_handle_album` опираются на
   `.album` файлы. Раз у single-треков его нет, они в обработку не
   попадают, что и требуется (файлы уже в целевом формате).

**Критерии готовности этапа B:** новый сингл с сайта ложится как
`/<artist>/<title>.mp3`; старые папки `*(Single)` не создаются.

---

### Этап C — Multi-value artists (убираем feat. в title)

1. **`backend/models.py`:**
   - `TrackMeta.artist: str` → `TrackMeta.artists: list[str]` (основной
     список). Для обратной совместимости с фронтом оставить свойство
     `artist` в виде `@computed_field` возвращающее `", ".join(artists)`
     **ИЛИ** (проще) — принимать оба на вход и нормализовать в
     `model_validator(mode="before")`.
   - Аналогично `ProcessRequest.artist` → `artists: list[str]`.
   - Добавить `album_artists: list[str]` (одно значение для "solo album",
     несколько — для "various"). Если не передано, дефолтится к первому
     элементу `artists`.

2. **`backend/processing.py`:**
   - Удалить `_normalize_artists(artist, title)` — больше не клеим
     `(feat. ...)` в title.
   - `read_tags`: отдавать `artists: list[str]`. Для ID3 — `TPE1.text`
     (это уже список). Для Vorbis — `tags.get("artist")` (тоже список).
     Для MP4 — `tags["\xa9ART"]` (список). Если есть только одиночное
     значение и в нём встречаются сепараторы — сплитить через
     `fix_artists.split_artist(raw)` прямо в `read_tags`, так UI получит
     нормальный список сразу.
   - `process_album` / `process_sc_album` → передают в `embed_tags`
     dict с `artists: list[str]`, `album_artists: list[str]`.

3. **`backend/soundcloud/tagger.py::embed_tags`:**
   - Вход: `meta["artists"]: list[str]`, `meta["album_artists"]: list[str]`.
   - ID3: `TPE1(encoding=3, text=artists)`, `TPE2(encoding=3, text=album_artists)`.
   - FLAC/OGG/Opus: `audio.tags["artist"] = artists` (mutagen принимает
     список).
   - MP4: `audio["\xa9ART"] = artists` (MP4 тоже поддерживает массив для
     этих атомов).

4. **Удалить `fix_artists.process_file` вызов в processing.py / worker** —
   тег уже корректно записан как multi-value. Санитайзер m4a-стримов
   остаётся (это отдельная функция из Этапа A).

5. **`backend/soundcloud/api.py`** (SC resolver) — возвращает уже
   `artists: list[str]`. Sources: SC API поле `publisher_metadata.artist`
   может содержать артистов через `,` / `&` — сплитим тем же
   `fix_artists.split_artist`.

6. **YouTube retag** (`backend/youtube/downloader.py::retag_mp3`):
   принимает `artists: list[str]`. Пишет `TPE1/TPE2` со списком.

7. **Frontend:**
   - Новый компонент `frontend/src/ArtistsEditor.jsx`. Принимает
     `value: string[]`, `onChange(list)`. UI: список чипов с
     крестиком, поле ввода + кнопка "+", Enter/запятая/амперсанд/слэш
     в поле добавляют чип. Drag-to-reorder (как track_number в
     MetaEditor). Делает split на тех же сепараторах, что и Python-код
     (feat., ft., &, /, ;, ,).
   - `MetaEditor.jsx` — заменить поле `artist` на `<ArtistsEditor
     value={shared.artists} onChange={...} />`. Убрать `album_artist`
     (он всегда равен artists).
   - `BulkEditor.jsx` — та же замена.
   - `PlaylistImport.jsx` — в режиме редактирования трека тоже показать
     `<ArtistsEditor />` (один артист = один чип).
   - `App.jsx::handleConfirm` — в payload отправляется `artists`
     (массив) вместо `artist` (строка).

**Критерии готовности этапа C:** файл с двумя артистами получает
TPE1 с двумя значениями напрямую из фронта, без `(feat. ...)` в
title; fix_artists.py не делает split (нет что сплитить).

---

### Этап D — Очередь для YouTube на VPS + локальный даунлоадер

**Общая идея:**
- VPS (backend): приняли `/api/yt-import`, записали треки в sqlite как
  `pending`. В Navidrome сразу создаём/обновляем плейлист, включая:
  - треки, которые уже были в Navidrome (`in_navidrome=true`),
  - pending-треки мы **пока не можем** добавить в плейлист, потому что
    их navidrome-ID ещё нет. Храним `pending_playlist_entries` — после
    успешной заливки с локальной машины сервис дописывает трек в
    плейлист.
- Локальная машина: CLI-скрипт `tools/yt_puller.py`, подключается к
  VPS через SSH-тоннель или HTTP API, забирает pending, качает, тегирует,
  заливает через SFTP, шлёт "done" на API.

#### D1. SQLite на VPS

**Новый файл:** `backend/services/download_queue.py`.
- Путь к базе: `$DOWNLOAD_QUEUE_DB` (default `/app/data/queue.db`).
  Монтируется в compose через уже существующий named volume — см. ниже.
- Схема:
  ```sql
  CREATE TABLE IF NOT EXISTS yt_downloads (
      id           INTEGER PRIMARY KEY AUTOINCREMENT,
      video_id     TEXT NOT NULL UNIQUE,
      title        TEXT NOT NULL,
      artists      TEXT NOT NULL,  -- JSON list
      duration     INTEGER,
      playlist_id  TEXT,           -- navidrome playlist id (optional)
      playlist_name TEXT,
      status       TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','claimed','done','failed')),
      claimed_by   TEXT,           -- hostname of local worker
      claimed_at   TEXT,           -- ISO timestamp
      done_at      TEXT,
      error        TEXT,
      remote_path  TEXT,           -- SFTP path after upload
      navidrome_id TEXT,           -- id обнаруженный после rescan
      created_at   TEXT NOT NULL
  );
  ```
- Публичный API: `enqueue(video_id, title, artists, ...)`, `claim(limit,
  worker_id)`, `mark_done(id, remote_path, navidrome_id)`,
  `mark_failed(id, error)`, `list_pending()`, `list_all(status=None)`.

#### D2. Navidrome playlist helper

**Новый файл:** `backend/services/navidrome_playlists.py`.
- `create_or_update_playlist(name, song_ids: list[str]) -> str` (id).
  Использует Subsonic `createPlaylist` / `updatePlaylist`. Кредиты
  читаются из тех же env-переменных, что и `backend/services/navidrome.py`.
- `append_to_playlist(playlist_id, song_id)`.
- `find_song_by_path(remote_path)` — вызывает Subsonic search по
  `title`+`artist`, маппит на id. Нужен, когда локальный воркер
  сообщает `done`.

#### D3. API endpoints

Отредактировать `backend/api/youtube.py`:

- `POST /api/yt-import`: текущая задача — ARQ `yt_import_task`. Меняем на:
  1. Создать/получить Navidrome playlist по имени.
  2. Добавить в плейлист все `in_navidrome=True` треки сразу через
     `navidrome_playlists.append_to_playlist`.
  3. Все остальные (и не `skip`) — записать в `yt_downloads` со
     статусом `pending` и `playlist_id`=id созданного плейлиста.
  4. Вернуть `JobStatus{status:"queued"}` как раньше (хотя job теперь
     не ARQ — для совместимости UI).
- Удалить `yt_import_task` из `backend/worker/main.py` и из
  `WorkerSettings.functions`.

Новые endpoints (для локального воркера):

- `GET  /api/yt-queue?status=pending` → список задач (для мониторинга).
- `POST /api/yt-queue/claim` body `{worker_id, limit}` → помечает
  задачи `claimed` и возвращает их. Авторизация — shared secret в
  header `X-Puller-Token` (env `YT_PULLER_TOKEN`).
- `POST /api/yt-queue/{id}/done` body `{remote_path}` → ставит `done`,
  ищет трек в Navidrome (возможно с ретраями, пока Navidrome не
  отсканирует), дописывает в плейлист.
- `POST /api/yt-queue/{id}/failed` body `{error}`.

Всё под префиксом `/api` и требует заголовок `X-Puller-Token`.

#### D4. compose и volumes

`docker-compose.yml`:
- Новый named volume `queue_db` монтируется в backend и worker по пути
  `/app/data` (worker пока не нужен, но пусть будет).
- `DOWNLOAD_QUEUE_DB=/app/data/queue.db` env в backend.
- `YT_PULLER_TOKEN=${YT_PULLER_TOKEN}` в backend.

#### D5. Локальный CLI puller

**Новый файл:** `tools/yt_puller/main.py` (+ `requirements.txt`,
`README.md`).

Алгоритм:
```python
while True:
    jobs = POST /api/yt-queue/claim   # с токеном
    if not jobs:
        sleep 30; continue
    for job in jobs:
        mp3 = download_youtube_track(job.video_id, tmp)
        retag_mp3(mp3, title=job.title, artists=job.artists, album="")
        fix_artists.process_file(mp3)
        remote = f"{job.artists[0]}/{sanitize(job.title)}.mp3"
        sftp_upload(mp3, remote)
        POST /api/yt-queue/{id}/done with remote_path
```

- Конфиг из `.env` рядом со скриптом: `API_BASE`, `PULLER_TOKEN`,
  `SFTP_*` (те же поля, что в `backend/.env`).
- Зависимости: `httpx`, `paramiko`, `yt-dlp`, `mutagen`.
- `README.md` — как запускать (`python -m yt_puller.main` или
  `make run`).
- Переиспользуем `backend/fix_artists.py` и
  `backend/youtube/downloader.py::download_youtube_track` / `retag_mp3`
  через относительный импорт или простое копирование (проще
  копирование, чтобы puller работал автономно без backend-пакета).

#### D6. Frontend

- Новый компонент `frontend/src/YtQueuePanel.jsx`. Показывает статус
  очереди (GET `/api/yt-queue`), обновляется каждые ~10 сек. Доступ
  по кнопке "Очередь" в хедере, скрыт за хэшем/URL. (Минимально —
  можно добавить в PlaylistImport после импорта: "Добавлено 5 треков
  в очередь. Смотреть →".)
- В `PlaylistImport.jsx` после успешного импорта показывать:
  "X добавлено в плейлист сразу, Y поставлено в очередь на скачивание".

**Критерии готовности этапа D:** `/api/yt-import` с 10 треками не
запускает скачивание на VPS, а записывает 10 строк в `yt_downloads`
(pending); локальный `yt_puller` на мак/линукс делает claim, скачивает,
заливает в SFTP, после чего трек появляется в Navidrome-плейлисте.

---

## 3. Порядок работ и зависимости

1. **Этап A** (fix_artists.py) — независимый, можно делать первым.
2. **Этап C** (multi-value artists) — опирается на A (split helper).
3. **Этап B** (single → в корень) — независимый, но затрагивает те же
   файлы что C. Делать вместе в одном PR.
4. **Этап D** (YT queue) — опирается на все три.

Commit-план (один коммит на завершённый подэтап):
- `refactor: port fix-artists to python`
- `refactor: drop (Single) pseudo-album folder`
- `feat: multi-value artists in uploads and UI`
- `feat: sqlite queue + local puller for youtube imports`

## 4. Что НЕ делаем

- Не трогаем processor_service (этап B обходится без него).
- Не добавляем retries/backoff в локальный puller — проблема видна в
  `yt_downloads.status='failed'` и чинится руками.
- Не переписываем SC тэггер на новый API в отдельный файл — правки
  вносим in-place.
