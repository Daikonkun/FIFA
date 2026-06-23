from __future__ import annotations

import httpx


class TelegramClient:
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 20.0) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout

    async def send_message(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text[:4096],
                    "disable_web_page_preview": True,
                },
            )
            response.raise_for_status()
