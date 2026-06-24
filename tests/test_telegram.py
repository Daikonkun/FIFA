from __future__ import annotations

from fifa_arb_agent.telegram import _split_telegram_message


def test_split_telegram_message_preserves_long_reports() -> None:
    text = "\n".join(f"line {index}" for index in range(700))

    chunks = _split_telegram_message(text, limit=500)

    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")
