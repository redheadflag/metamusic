from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

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
BTN_REQUEST_MUSIC = "Попросить добавить артиста / альбом / трек"

def apps_os_keyboard() -> InlineKeyboardMarkup:
    from constants import APPS
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=os_name, callback_data=f"apps_os:{os_name}")]
            for os_name in APPS
        ]
    )


account_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_NOW_PLAYING)],
        [KeyboardButton(text=BTN_APPLICATIONS)],
        [KeyboardButton(text=BTN_UPLOAD_MUSIC)],
        [KeyboardButton(text=BTN_REQUEST_MUSIC)],
    ],
    resize_keyboard=True,
)
