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
    albumLabel:       "Album",
    yearLabel:        "Year",
    tracksLabel:      "Tracks",
    trackLabel:       "Track",
    singleHint:       "Album name will be set to",
    singleHintSuffix: "(Single)",
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
    albumLabel:       "Альбом",
    yearLabel:        "Год",
    tracksLabel:      "Треки",
    trackLabel:       "Трек",
    singleHint:       "Название альбома будет установлено как",
    singleHintSuffix: "(Сингл)",
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
