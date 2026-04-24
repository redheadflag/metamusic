// i18n.js — all UI strings in one place.
// Add a key here, then use t("key") anywhere via useLang().

export const translations = {
  en: {
    // Header
    appTitle: "Upload to music.redheadflag.com",

    // ModeSelector
    fromFiles:        "From files",
    fromFilesHint:    "Upload audio files or .zip albums",
    soundcloud:       "SoundCloud",
    soundcloudHint:   "Paste a track or playlist URL",

    // UploadZone
    dropHere:         "Drop audio files here",
    dropSub:          "audio files or .zip albums",
    clickBrowse:      "click to browse",

    // ScInput
    scUrlLabel:       "SoundCloud URL",
    scUrlPlaceholder: "https://soundcloud.com/artist or /artist/track or /artist/sets/album",
    scTypeTrack:      "Single track",
    scTypePlaylist:   "Playlist / album",
    scTypeArtist:     "Artist profile — fetches all albums and tracks",
    scTypeInvalid:    "Enter a valid SoundCloud URL",
    back:             "← Back",
    fetch:            "Fetch",
    fetchingArtist:   "Fetching artist profile…",
    fetchingMeta:     "Fetching metadata…",

    // MetaEditor
    single:           "Single",
    songFromAlbum:    "Song from album",
    artistLabel:      "Artist",
    artistsLabel:     "Artists",
    artistsPlaceholder: "Add artist (Enter, comma, &, /)",
    albumLabel:       "Album",
    yearLabel:        "Year",
    tracksLabel:      "Tracks",
    trackLabel:       "Track",
    titleRequired:    "Title required",
    saveToLibrary:    "Save to library",
    deleteConfirm:    (title) => `Delete "${title}"?`,

    // BulkEditor
    albumCount:       (n) => `${n} album${n !== 1 ? "s" : ""}`,
    collapseAll:      "Collapse all",
    expandAll:        "Expand all",
    noArtist:         "No artist",
    trackCount:       (n) => `${n} track${n !== 1 ? "s" : ""}`,
    removeAlbum:      "Remove",
    saveAllToLibrary: "Save all to library",

    // Request modal
    requestBtn:       "Request artist / album / track",
    requestTitle:     "Request music",
    requestBody:      "List the artists, albums, or tracks you'd like added to the server. Please include only content you actually listen to — server space is not unlimited.",
    close:            "Close",

    // YouTube (ModeSelector)
    ytImport:         "Load from YouTube",
    ytImportHint:     "Download a track or playlist — added to library in the background",

    // PlaylistImport component
    ytPlaylistUrl:    "YouTube URL",
    ytUrlPlaceholder: "youtube.com/watch?v=… or music.youtube.com/playlist?list=…",
    ytScan:           "Load",
    ytScanning:       "Loading…",
    ytTracksFound:    (total, matched) => `${total} track${total !== 1 ? "s" : ""} · ${matched} in library`,
    ytImportBtn:      (n) => `Queue ${n} track${n !== 1 ? "s" : ""} for download`,
    ytAllMatched:     "All tracks are already in the library",
    ytSkip:           "Skip",
    ytUnskip:         "Undo skip",
    edit:             "Edit",
    ytQueued:         (queued, matched) => `${queued} track${queued !== 1 ? "s" : ""} queued for download, ${matched} already in library`,
    ytViewQueue:      "View download queue",
    ytLatencyWarning: "Tracks are downloaded in the background and will appear in your library after a short delay.",
    ytSingleTrack:    "Single video detected",
    ytAddToQueue:     "Add to download queue",

    // Metadata fields (shared)
    albumArtistsLabel:   "Album artists",
    albumArtistHint:     "Used for folder organization — usually same as artists",

    // App states
    uploadingLabel:   "Uploading…",
    fetchingSc:       "Fetching metadata from SoundCloud…",
    jobQueued:        "Waiting in queue…",
    jobInProgress:    "Processing tracks…",
    jobSubmitting:    "Submitting job…",
    jobLongNote:      "This may take a few minutes for large albums or SoundCloud downloads.",
    jobSentTitle:     "Request sent",
    jobSentNote:      "Your tracks are being processed in the background. You can go back and upload more.",
    goBack:           "← Go back",
    uploadMore:       "Upload more",
    savedCount:       (n) => `✓ ${n} track${n !== 1 ? "s" : ""} saved`,
    tryAgain:         "Try again",
    tracksLabel2:     (n) => `${n} track${n !== 1 ? "s" : ""}`,
    albumsLabel:      (n) => `${n} album${n !== 1 ? "s" : ""}`,
  },

  ru: {
    // Header
    appTitle: "Загрузить на music.redheadflag.com",

    // ModeSelector
    fromFiles:        "Из файлов",
    fromFilesHint:    "Загрузите аудиофайлы или .zip-архивы альбомов",
    soundcloud:       "SoundCloud",
    soundcloudHint:   "Вставьте ссылку на трек или плейлист",

    // UploadZone
    dropHere:         "Перетащите аудиофайлы сюда",
    dropSub:          "аудиофайлы или .zip-архивы альбомов",
    clickBrowse:      "нажмите для выбора",

    // ScInput
    scUrlLabel:       "Ссылка SoundCloud",
    scUrlPlaceholder: "https://soundcloud.com/artist или /artist/track или /artist/sets/album",
    scTypeTrack:      "Отдельный трек",
    scTypePlaylist:   "Плейлист / альбом",
    scTypeArtist:     "Профиль исполнителя — загружает все альбомы и треки",
    scTypeInvalid:    "Введите корректную ссылку SoundCloud",
    back:             "← Назад",
    fetch:            "Загрузить",
    fetchingArtist:   "Загружаю профиль исполнителя…",
    fetchingMeta:     "Загружаю метаданные…",

    // MetaEditor
    single:           "Сингл",
    songFromAlbum:    "Трек из альбома",
    artistLabel:      "Исполнитель",
    artistsLabel:     "Исполнители",
    artistsPlaceholder: "Добавить (Enter, запятая, &, /)",
    albumLabel:       "Альбом",
    yearLabel:        "Год",
    tracksLabel:      "Треки",
    trackLabel:       "Трек",
    titleRequired:    "Название обязательно",
    saveToLibrary:    "Сохранить в библиотеку",
    deleteConfirm:    (title) => `Удалить «${title}»?`,

    // BulkEditor
    albumCount:       (n) => `${n} ${n === 1 ? "альбом" : n < 5 ? "альбома" : "альбомов"}`,
    collapseAll:      "Свернуть все",
    expandAll:        "Развернуть все",
    noArtist:         "Нет исполнителя",
    trackCount:       (n) => `${n} ${n === 1 ? "трек" : n < 5 ? "трека" : "треков"}`,
    removeAlbum:      "Удалить",
    saveAllToLibrary: "Сохранить всё в библиотеку",

    // Request modal
    requestBtn:       "Попросить добавить артиста / альбом / трек",
    requestTitle:     "Запрос на добавление музыки",
    requestBody:      "Укажите список исполнителей, альбомов или треков, которые вы хотели бы видеть на сервере. Просьба включать только то, что вы действительно слушаете — место на сервере ограничено.",
    close:            "Закрыть",

    // YouTube (ModeSelector)
    ytImport:         "Загрузить с YouTube",
    ytImportHint:     "Скачать трек или плейлист — добавляется в библиотеку в фоне",

    // PlaylistImport component
    ytPlaylistUrl:    "Ссылка YouTube",
    ytUrlPlaceholder: "youtube.com/watch?v=… или music.youtube.com/playlist?list=…",
    ytScan:           "Загрузить",
    ytScanning:       "Загружаю…",
    ytTracksFound:    (total, matched) => `${total} ${total === 1 ? "трек" : total < 5 ? "трека" : "треков"} · ${matched} в библиотеке`,
    ytImportBtn:      (n) => `Поставить в очередь ${n} ${n === 1 ? "трек" : n < 5 ? "трека" : "треков"}`,
    ytAllMatched:     "Все треки уже есть в библиотеке",
    ytSkip:           "Пропустить",
    ytUnskip:         "Отмена",
    edit:             "Изменить",
    ytQueued:         (queued, matched) => `${queued} ${queued === 1 ? "трек поставлен" : queued < 5 ? "трека поставлено" : "треков поставлено"} в очередь, ${matched} уже в библиотеке`,
    ytViewQueue:      "Смотреть очередь загрузки",
    ytLatencyWarning: "Треки скачиваются в фоне и появятся в библиотеке после небольшой задержки.",
    ytSingleTrack:    "Обнаружено отдельное видео",
    ytAddToQueue:     "Добавить в очередь загрузки",

    // Metadata fields (shared)
    albumArtistsLabel:   "Исполнители альбома",
    albumArtistHint:     "Используется для папок — обычно совпадает с исполнителями",

    // App states
    uploadingLabel:   "Загрузка…",
    fetchingSc:       "Загружаю метаданные с SoundCloud…",
    jobQueued:        "Ожидание в очереди…",
    jobInProgress:    "Обрабатываю треки…",
    jobSubmitting:    "Отправляю задачу…",
    jobLongNote:      "Для больших альбомов или загрузки с SoundCloud это может занять несколько минут.",
    jobSentTitle:     "Запрос отправлен",
    jobSentNote:      "Треки обрабатываются в фоновом режиме. Можно вернуться назад и загрузить ещё.",
    goBack:           "← На главную",
    uploadMore:       "Загрузить ещё",
    savedCount:       (n) => `✓ ${n} ${n === 1 ? "трек сохранён" : n < 5 ? "трека сохранено" : "треков сохранено"}`,
    tryAgain:         "Попробовать снова",
    tracksLabel2:     (n) => `${n} ${n === 1 ? "трек" : n < 5 ? "трека" : "треков"}`,
    albumsLabel:      (n) => `${n} ${n === 1 ? "альбом" : n < 5 ? "альбома" : "альбомов"}`,
  },
};
