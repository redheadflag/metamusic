from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_CREATE_ACCOUNT = "Создать аккаунт"
BTN_ALREADY_HAVE_ACCOUNT = "У меня уже есть аккаунт"

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_CREATE_ACCOUNT)],
        [KeyboardButton(text=BTN_ALREADY_HAVE_ACCOUNT)]
    ],
    resize_keyboard=True,
)


BTN_APPLICATIONS = "Скачать приложения"
BTN_UPLOAD_MUSIC = "Загрузить музыку"

account_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_APPLICATIONS)],
        [KeyboardButton(text=BTN_UPLOAD_MUSIC)],
    ],
    resize_keyboard=True
)
