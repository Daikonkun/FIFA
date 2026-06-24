from __future__ import annotations

import httpx


TELEGRAM_MESSAGE_LIMIT = 4096


class TelegramClient:
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 20.0) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout

    async def send_message(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for chunk in _split_telegram_message(text):
                response = await client.post(
                    url,
                    json={
                        "chat_id": self.chat_id,
                        "text": chunk,
                        "disable_web_page_preview": True,
                    },
                )
                response.raise_for_status()


def _split_telegram_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                chunks.append(current.rstrip())
                current = ""
            for index in range(0, len(line), limit):
                chunks.append(line[index : index + limit].rstrip())
            continue
        if len(current) + len(line) > limit:
            chunks.append(current.rstrip())
            current = line
        else:
            current += line
    if current:
        chunks.append(current.rstrip())
    return chunks
