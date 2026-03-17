from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_CREATE_ACCOUNT = "Создать аккаунт"

main_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_CREATE_ACCOUNT)]],
    resize_keyboard=True,
)
