from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_CREATE_ACCOUNT = "Создать аккаунт"
BTN_LOGIN = "Войти в аккаунт"

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_CREATE_ACCOUNT)],
        [KeyboardButton(text=BTN_LOGIN)],
    ],
    resize_keyboard=True,
)


BTN_APPLICATIONS = "Скачать приложения"
BTN_UPLOAD_MUSIC = "Загрузить музыку"
BTN_NOW_PLAYING = "🎵 Отправить текущий трек"

account_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_NOW_PLAYING)],
        [KeyboardButton(text=BTN_APPLICATIONS)],
        [KeyboardButton(text=BTN_UPLOAD_MUSIC)],
    ],
    resize_keyboard=True,
)
