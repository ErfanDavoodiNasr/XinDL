import uuid
import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Update
from src.core.logger import reference_id_var

logger = logging.getLogger(__name__)

class RequestContextMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        # Generate a unique reference ID for this request
        ref_id = str(uuid.uuid4())
        
        # Set the context variable for the logger
        token = reference_id_var.set(ref_id)
        
        try:
            return await handler(event, data)
        except Exception as e:
            logger.exception(f"Unhandled exception in bot handler: {e}")
            
            # Try to send an error message to the user if we can determine the chat
            try:
                chat_id = None
                if event.message:
                    chat_id = event.message.chat.id
                elif event.callback_query:
                    chat_id = event.callback_query.message.chat.id
                    
                if chat_id:
                    from aiogram import Bot
                    bot: Bot = data.get('bot')
                    if bot:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"❌ <b>An unexpected error occurred.</b>\n\n"
                                 f"Our engineers have been notified. If the issue persists, "
                                 f"please report this reference ID:\n"
                                 f"<code>{ref_id}</code>"
                        )
            except Exception as inner_e:
                logger.error(f"Failed to send error message to user: {inner_e}")
        finally:
            # Reset the context variable
            reference_id_var.reset(token)
