"""Тесты уведомления оператору о новой заявке.

Проверяем без сети и без Telegram:
- текст уведомления содержит имя, телефон, откуда и куда везём,
  вес и стоимость;
- заявка без расчёта показывает прочерки вместо None;
- без MANAGER_CHAT_ID уведомление не отправляется и бот не падает;
- с MANAGER_CHAT_ID сообщение уходит на этот id;
- crm.send_lead_to_bitrix() без вебхука возвращает False, поэтому
  уведомление за «моковую» сделку не улетает.

Telegram заменён заглушкой с методом send_message, окружение
подменяется через mock.patch.dict: реальный .env в тестах не читается.
"""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

import bot as bot_module
from crm import send_lead_to_bitrix


class FakeBot:
    """Заглушка Bot: запоминает, кому и что бот отправил."""

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=1)


class FakeMessage:
    """Заглушка Message: у настоящего Message есть .bot."""

    def __init__(self):
        self.bot = FakeBot()


class OperatorNoticeTextTestCase(unittest.TestCase):
    """Текст уведомления: все поля заявки на месте."""

    def test_full_booking_contains_all_fields(self):
        text = bot_module.operator_notice(
            "Иван",
            "+7 900 000-00-00",
            "Москва",
            "Санкт-Петербург",
            12.5,
            2250,
        )
        for expected in (
            "Новая заявка на доставку",
            "Имя: Иван",
            "Телефон: +7 900 000-00-00",
            "Откуда: Москва",
            "Куда: Санкт-Петербург",
            "Вес: 12.5 кг",
            "Стоимость: 2250 руб.",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_booking_without_calc_shows_dashes(self):
        text = bot_module.operator_notice(
            "Иван", "+7 900 000-00-00", None, None, None, None
        )
        self.assertIn("Откуда: -", text)
        self.assertIn("Куда: -", text)
        self.assertIn("Вес: - кг", text)
        self.assertIn("Стоимость: - руб.", text)
        self.assertNotIn("None", text)


class NotifyOperatorTestCase(unittest.IsolatedAsyncioTestCase):
    """Отправка уведомления: адрес из MANAGER_CHAT_ID."""

    async def test_skipped_without_manager_chat_id(self):
        message = FakeMessage()
        with mock.patch.dict(
            os.environ, {"MANAGER_CHAT_ID": ""}, clear=False
        ):
            await bot_module.notify_operator(
                message,
                "Иван",
                "+7 900 000-00-00",
                "Москва",
                "Санкт-Петербург",
                12.5,
                2250,
            )
        self.assertEqual(message.bot.sent, [])

    async def test_sent_to_manager_chat_id(self):
        message = FakeMessage()
        with mock.patch.dict(
            os.environ, {"MANAGER_CHAT_ID": "1284467730"}, clear=False
        ):
            await bot_module.notify_operator(
                message,
                "Иван",
                "+7 900 000-00-00",
                "Москва",
                "Санкт-Петербург",
                12.5,
                2250,
            )
        self.assertEqual(len(message.bot.sent), 1)
        chat_id, text = message.bot.sent[0]
        self.assertEqual(chat_id, "1284467730")
        self.assertIn("Откуда: Москва", text)
        self.assertIn("Куда: Санкт-Петербург", text)
        self.assertIn("Стоимость: 2250 руб.", text)


class CrmStatusTestCase(unittest.TestCase):
    """Без вебхука сделки нет — уведомление не должно уходить."""

    def test_no_webhook_returns_false(self):
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in ("BITRIX_WEBHOOK_URL", "BITRIX_WEBHOOK")
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch("builtins.print"):
                result = send_lead_to_bitrix(
                    "Иван",
                    "+7 900 000-00-00",
                    "Москва",
                    "Санкт-Петербург",
                    12.5,
                    2250,
                )
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
