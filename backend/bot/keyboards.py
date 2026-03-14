from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_CREATE_ACCOUNT = "Create Account"

main_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_CREATE_ACCOUNT)]],
    resize_keyboard=True,
)
