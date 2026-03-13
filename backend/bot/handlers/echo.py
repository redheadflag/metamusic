from aiogram import Router
from aiogram.types import Message
 
router = Router()
 
 
@router.message()
async def echo_handler(message: Message) -> None:
    """Echo every text message back to the user."""
    await message.answer(message.text or "")
 