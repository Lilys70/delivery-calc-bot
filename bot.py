"""Telegram-бот «Калькулятор доставки».

Учебный проект №3 Zerocoder, полная логика. Меню из трёх пунктов:
«Рассчитать стоимость» (города отправления и назначения, вес,
формула из данных/cities.py),
«Оформить заявку» (имя и телефон, заявка в хранилище/заявки.json,
реальная отправка в Битрикс24 через crm.py)
и «Связаться с оператором» (URL-кнопка, заглушка).

Запуск: python bot.py (из корня папки проекта; токен читается из .env).
Если api.telegram.org недоступен напрямую, в .env можно вписать прокси:
PROXY_URL=http://host:port или socks5://host:port — необязательная настройка.
"""

import asyncio
import html
import logging
import os
import sys
from pathlib import Path

from aiohttp import ClientConnectorError
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramUnauthorizedError,
)
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

from данные.cities import (
    CITIES,
    MAX_WEIGHT,
    MIN_WEIGHT,
    ORIGIN_RATES,
    calculate_cost,
)
from хранилище.заявки import save_application
from crm import send_lead_to_bitrix

# Сетевые сбои: к Telegram напрямую и через прокси.
NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    ClientConnectorError,
    TelegramNetworkError,
)

# --- Тексты сообщений --------------------------------------------------------

WELCOME_TEXT = (
    "Здравствуйте! Это бот «Калькулятор доставки».\n\n"
    "Считаю стоимость доставки по городам отправления и назначения "
    "и весу груза, принимаю заявки и передаю их оператору.\n\n"
    "Выберите, что нужно сделать:"
)

ASK_ORIGIN_TEXT = "Откуда везём груз? Выберите город отправления:"
ASK_CITY_TEXT = "Куда везём груз? Выберите город назначения:"
CITY_LOST_TEXT = (
    "Не вижу город отправления или назначения. "
    "Начнём заново: нажмите /start и выберите города кнопками."
)
ASK_WEIGHT_TEXT = "Какой вес у груза (в килограммах)? Напишите число."
WEIGHT_ERROR_TEXT = (
    f"Вес не поняла: нужен груз от {MIN_WEIGHT} до {MAX_WEIGHT} кг. "
    "Напишите число, например: 12.5"
)

ASK_NAME_TEXT = "Как вас зовут?"
NAME_ERROR_TEXT = (
    "Имя должно быть от 2 до 64 символов. "
    "Напишите, пожалуйста, ещё раз."
)

ASK_PHONE_TEXT = "Ваш телефон для связи:"
PHONE_ERROR_TEXT = (
    "Телефон не сохранился: нужно от 5 до 30 символов. "
    "Напишите номер, например: +7 900 123-45-67"
)

THANKS_TEXT = (
    "Спасибо, {name}! Ваша заявка принята. "
    "Мы свяжемся с вами в ближайшее время"
)
SAVE_ERROR_TEXT = (
    "Не удалось сохранить заявку: что-то сломалось на нашей стороне. "
    "Отправьте телефон ещё раз или напишите позже."
)

STALE_TEXT = "Эта кнопка устарела. Нажмите /start, чтобы открыть меню."

# URL-кнопка «Связаться с оператором»: ник оператора.
# Заменить на реальный ник оператора, если заявки ведёт другой человек.
OPERATOR_URL = "https://t.me/Lilysa24"


def result_text(
    origin: str,
    destination: str,
    weight: float,
    cost: int,
) -> str:
    """Текст результата: откуда и куда везём, вес и итоговая сумма.

    Стоимость приходит готовой: та же цифра уходит в FSM и в CRM,
    чтобы в сообщении и в сделке была одна и та же сумма.
    """
    return (
        f"Стоимость доставки {origin} → {destination} "
        f"для груза {weight:g} кг составляет: {cost} руб."
    )


# --- Состояния ---------------------------------------------------------------
class CalcStates(StatesGroup):
    """Расчёт стоимости: откуда везём, куда везём и вес груза."""

    waiting_origin = State()
    waiting_city = State()
    waiting_weight = State()


class OrderStates(StatesGroup):
    """Заявка на доставку: имя и телефон."""

    waiting_name = State()
    waiting_phone = State()


# --- Клавиатуры --------------------------------------------------------------
def menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню: расчёт, заявка и связь с оператором."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Рассчитать стоимость",
                    callback_data="calc_start",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Оформить заявку",
                    callback_data="order_start",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Связаться с оператором",
                    url=OPERATOR_URL,
                ),
            ],
        ]
    )


def cities_keyboard(prefix: str = "city") -> InlineKeyboardMarkup:
    """Кнопки городов: callback_data = <prefix>:<название>.

    prefix="origin" — шаг «Откуда везём?», prefix="city" — шаг
    «Куда везём?». По префиксу обработчик понимает, какой город
    выбрали: отправления или назначения.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=city, callback_data=f"{prefix}:{city}"
                )
            ]
            for city in CITIES
        ]
    )


def result_keyboard() -> InlineKeyboardMarkup:
    """Кнопки под результатом: оформить заявку или вернуться в меню."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Оформить заявку",
                    callback_data="order_start",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="В главное меню",
                    callback_data="menu",
                ),
            ],
        ]
    )


# --- Вспомогательные функции -------------------------------------------------
async def safe_delete(message: Message) -> None:
    """Удаляет сообщение и не падает, если оно уже удалено.

    В чате должно оставаться одно актуальное сообщение с кнопками:
    иначе пользователь нажимает кнопку со старого экрана, а бот
    реагирует неожиданно.
    """
    try:
        await message.delete()
    except TelegramBadRequest:
        # Сообщение старше 48 часов или уже удалено — это не ошибка.
        pass


def operator_notice(
    name: str,
    phone: str,
    origin: str | None,
    destination: str | None,
    weight: float | None,
    cost: int | None,
) -> str:
    """Текст уведомления оператору о новой заявке.

    Города, вес и стоимость показываются прочерком, если заявку оформили
    без расчёта: уведомление должно дойти в любом случае, а не упасть
    на подстановке None.
    """
    return (
        "Новая заявка на доставку\n\n"
        f"Имя: {name}\n"
        f"Телефон: {phone}\n"
        f"Откуда: {origin or '-'}\n"
        f"Куда: {destination or '-'}\n"
        f"Вес: {weight if weight is not None else '-'} кг\n"
        f"Стоимость: {cost if cost is not None else '-'} руб."
    )


async def notify_operator(
    message: Message,
    name: str,
    phone: str,
    origin: str | None,
    destination: str | None,
    weight: float | None,
    cost: int | None,
) -> None:
    """Отправляет оператору детали заявки в Telegram.

    Id оператора берётся из MANAGER_CHAT_ID в .env. Переменная не задана —
    уведомление пропускается и бот работает дальше. Ошибка Telegram
    (оператор не начинал диалог с ботом, сеть) тоже не мешает выдать
    благодарность: причина уходит в лог.
    """
    manager_chat_id = os.getenv("MANAGER_CHAT_ID", "").strip()
    if not manager_chat_id:
        logging.info(
            "MANAGER_CHAT_ID не задан: уведомление оператору пропущено"
        )
        return

    try:
        await message.bot.send_message(
            manager_chat_id,
            operator_notice(name, phone, origin, destination, weight, cost),
        )
        logging.info("Уведомление оператору отправлено: %s", manager_chat_id)
    except (
        TelegramAPIError,
        ClientConnectorError,
        TelegramNetworkError,
    ) as error:
        logging.warning("Уведомление оператору не ушло: %s", error)


def parse_weight(text: str) -> float | None:
    """Превращает текст в вес груза; None, если ввод не годится.

    Запятая принимается как десятичный разделитель, пробелы убираются.
    Вес должен укладываться в допустимые границы из данных/cities.py.
    """
    raw = (text or "").replace(",", ".").replace(" ", "").strip()
    try:
        weight = float(raw)
    except ValueError:
        return None

    if not MIN_WEIGHT <= weight <= MAX_WEIGHT:
        return None
    return weight


# --- Обработчики -------------------------------------------------------------
async def on_start(message: Message, state: FSMContext) -> None:
    """Приветствие и меню; /start сбрасывает незаконченный диалог."""
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=menu_keyboard())


async def on_reset(message: Message, state: FSMContext) -> None:
    """Сброс диалога: чистим состояние и показываем меню заново."""
    await state.clear()
    await message.answer(
        "Состояние сброшено.\n\n" + WELCOME_TEXT,
        reply_markup=menu_keyboard(),
    )


async def exit_form_on_command(
    message: Message, state: FSMContext
) -> bool:
    """True, если вместо данных пришла команда: шаг прерываем.

    Проверка стоит первой строкой в каждом текстовом шаге: имя, телефон
    и вес — свободный текст, и без проверки «/start» мог бы уйти в поле.
    """
    text = (message.text or "").strip()
    if not text.startswith("/"):
        return False

    await on_start(message, state)
    return True


# --- Расчёт стоимости --------------------------------------------------------
async def on_calc_start(callback: CallbackQuery, state: FSMContext) -> None:
    """«Рассчитать стоимость»: спрашиваем, откуда везём груз."""
    if callback.message is None:
        await callback.answer("Сообщение устарело, отправьте /start")
        return

    await state.set_state(CalcStates.waiting_origin)
    await state.set_data(
        {
            "origin": None,
            "city": None,
            "weight": None,
            "cost": None,
            "message_id": None,
        }
    )
    await safe_delete(callback.message)
    sent = await callback.message.answer(
        ASK_ORIGIN_TEXT, reply_markup=cities_keyboard("origin")
    )
    await state.update_data(message_id=sent.message_id)
    await callback.answer()


async def on_origin(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор города отправления: сохраняем и спрашиваем, куда везём."""
    if callback.message is None:
        await callback.answer("Сообщение устарело, отправьте /start")
        return

    data = await state.get_data()
    # Кнопка со старого экрана: её id уже не совпадает с текущим.
    if callback.message.message_id != data.get("message_id"):
        await callback.answer(STALE_TEXT, show_alert=True)
        return

    origin = callback.data.split(":", 1)[1]
    if origin not in ORIGIN_RATES:
        await callback.answer("Такого города нет, выберите заново")
        return

    await state.update_data(origin=origin)
    await state.set_state(CalcStates.waiting_city)
    await safe_delete(callback.message)
    sent = await callback.message.answer(
        ASK_CITY_TEXT, reply_markup=cities_keyboard("city")
    )
    await state.update_data(message_id=sent.message_id)
    await callback.answer()


async def on_city(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор города назначения: сохраняем его и спрашиваем вес груза."""
    if callback.message is None:
        await callback.answer("Сообщение устарело, отправьте /start")
        return

    data = await state.get_data()
    # Кнопка со старого экрана: её id уже не совпадает с текущим.
    if callback.message.message_id != data.get("message_id"):
        await callback.answer(STALE_TEXT, show_alert=True)
        return

    city = callback.data.split(":", 1)[1]
    if city not in CITIES:
        await callback.answer("Такого города нет, выберите заново")
        return

    await state.update_data(city=city)
    await state.set_state(CalcStates.waiting_weight)
    await safe_delete(callback.message)
    await callback.message.answer(ASK_WEIGHT_TEXT)
    await callback.answer()


async def on_weight(message: Message, state: FSMContext) -> None:
    """Вес груза: считаем стоимость и показываем результат."""
    if await exit_form_on_command(message, state):
        return

    weight = parse_weight(message.text)
    if weight is None:
        await message.answer(WEIGHT_ERROR_TEXT)
        return

    data = await state.get_data()
    origin = data.get("origin")
    city = data.get("city")
    # Страховка: если города потерялись (например, диалог начался
    # до правки сценария), начинаем расчёт заново, а не падаем.
    if origin not in ORIGIN_RATES or city not in CITIES:
        await state.set_state(CalcStates.waiting_origin)
        await state.set_data(
            {
                "origin": None,
                "city": None,
                "weight": None,
                "cost": None,
                "message_id": None,
            }
        )
        sent = await message.answer(
            CITY_LOST_TEXT, reply_markup=cities_keyboard("origin")
        )
        await state.update_data(message_id=sent.message_id)
        return

    cost = calculate_cost(origin, city, weight)
    await state.set_state(None)
    # Города, вес и стоимость оставляем в FSM: их возьмёт заявка, если
    # пользователь нажмёт «Оформить заявку» под результатом.
    await state.update_data(
        origin=origin, city=city, weight=weight, cost=cost
    )
    await message.answer(
        result_text(origin, city, weight, cost),
        reply_markup=result_keyboard(),
    )


async def on_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """«В главное меню»: сброс состояния и приветствие."""
    if callback.message is None:
        await callback.answer("Сообщение устарело, отправьте /start")
        return

    await state.clear()
    await safe_delete(callback.message)
    await callback.message.answer(
        WELCOME_TEXT, reply_markup=menu_keyboard()
    )
    await callback.answer()


# --- Заявка на доставку ------------------------------------------------------
async def on_order_start(callback: CallbackQuery, state: FSMContext) -> None:
    """«Оформить заявку» (из меню или под результатом): просим имя.

    Города, вес и стоимость берутся из FSM, если перед заявкой был
    расчёт; если заявка оформляется сразу из меню, их не будет (None).
    """
    if callback.message is None:
        await callback.answer("Сообщение устарело, отправьте /start")
        return

    await state.set_state(OrderStates.waiting_name)
    await safe_delete(callback.message)
    await callback.message.answer(ASK_NAME_TEXT)
    await callback.answer()


async def on_order_name(message: Message, state: FSMContext) -> None:
    """Имя из заявки: проверяем длину, спрашиваем телефон."""
    if await exit_form_on_command(message, state):
        return

    name = (message.text or "").strip()
    if not 2 <= len(name) <= 64:
        await message.answer(NAME_ERROR_TEXT)
        return

    await state.update_data(order_name=name)
    await state.set_state(OrderStates.waiting_phone)
    await message.answer(ASK_PHONE_TEXT)


async def on_order_phone(message: Message, state: FSMContext) -> None:
    """Телефон: последний шаг — сохраняем заявку и передаём в CRM."""
    if await exit_form_on_command(message, state):
        return

    phone = (message.text or "").strip()
    if not 5 <= len(phone) <= 30:
        await message.answer(PHONE_ERROR_TEXT)
        return

    data = await state.get_data()
    name = data.get("order_name", "")
    # Заявка может быть оформлена без расчёта: тогда городов, веса и
    # стоимости нет — в CRM уйдёт 0 руб. и нейтральное название сделки.
    origin = data.get("origin")
    city = data.get("city")
    weight = data.get("weight")
    cost = data.get("cost")

    try:
        save_application(
            user_id=message.from_user.id,
            name=name,
            phone=phone,
            origin=origin,
            city=city,
            weight=weight,
        )
    except OSError:
        # Файл недоступен (нет прав, диск занят). Состояние не снимаем:
        # пользователь может отправить телефон ещё раз.
        logging.exception("Не удалось сохранить заявку")
        await message.answer(SAVE_ERROR_TEXT)
        return

    # Реальная отправка в Битрикс24 через crm.py: стоимость — сумма сделки.
    # True — Битрикс24 создал сделку; по этому признаку уходит уведомление
    # оператору, чтобы за одну заявку оно не отправлялось повторно.
    deal_created = send_lead_to_bitrix(
        name, phone, origin, city, weight, cost=cost
    )
    if deal_created:
        await notify_operator(
            message, name, phone, origin, city, weight, cost
        )

    await state.clear()
    await message.answer(THANKS_TEXT.format(name=html.escape(name)))


async def on_stale(callback: CallbackQuery) -> None:
    """Незнакомая или устаревшая кнопка: подсказываем вернуться в меню."""
    await callback.answer(STALE_TEXT, show_alert=True)


# --- Сборка приложения -------------------------------------------------------
def register_handlers(dp: Dispatcher) -> None:
    """Подключает обработчики к диспетчеру.

    Порядок важен: /start и /reset стоят первыми и сбрасывают любое
    состояние, поэтому расчёт и форму можно прервать командой. Шаги
    с текстом ловятся только в своих состояниях.
    """
    dp.message.register(on_start, CommandStart())
    dp.message.register(on_reset, Command("reset"))
    dp.callback_query.register(on_calc_start, F.data == "calc_start")
    dp.callback_query.register(
        on_origin,
        StateFilter(CalcStates.waiting_origin),
        F.data.startswith("origin:"),
    )
    dp.callback_query.register(
        on_city,
        StateFilter(CalcStates.waiting_city),
        F.data.startswith("city:"),
    )
    dp.callback_query.register(on_order_start, F.data == "order_start")
    dp.callback_query.register(on_menu, F.data == "menu")
    dp.message.register(
        on_weight, StateFilter(CalcStates.waiting_weight)
    )
    dp.message.register(
        on_order_name, StateFilter(OrderStates.waiting_name)
    )
    dp.message.register(
        on_order_phone, StateFilter(OrderStates.waiting_phone)
    )
    dp.callback_query.register(on_stale)


def read_token() -> str:
    """Читает токен из окружения.

    Токен хранится только в .env — в коде и в репозитории его быть
    не должно.
    """
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token == "ваш_токен_здесь":
        raise RuntimeError(
            "Не найден BOT_TOKEN. Скопируйте .env.example в .env "
            "и вставьте токен, который выдал @BotFather."
        )
    return token


def read_proxy() -> str | None:
    """Прокси из .env: пустое значение — подключаемся напрямую.

    PROXY_URL — необязательная настройка. Пустая строка, пробелы и вовсе
    отсутствующая переменная означают «прокси не нужен».
    """
    proxy = os.getenv("PROXY_URL", "").strip()
    return proxy or None


def create_session() -> AiohttpSession:
    """Сессия для Telegram: через прокси, если он указан в .env.

    Сам URL прокси в лог не пишем: в нём бывают логин и пароль.
    """
    proxy = read_proxy()
    if proxy is None:
        logging.info("Прокси не задан: подключаюсь к Telegram напрямую")
        return AiohttpSession()

    try:
        session = AiohttpSession(proxy=proxy)
    except RuntimeError as error:
        # aiogram так сообщает, что для прокси не хватает aiohttp-socks.
        raise RuntimeError(
            "PROXY_URL задан, но пакет aiohttp-socks не установлен. "
            "Выполните: pip install aiohttp-socks"
        ) from error

    logging.info("Прокси включён: запросы к Telegram идут через него")
    return session


def network_error_message(error: Exception) -> str:
    """Подсказка при сетевой ошибке: что проверить и куда вписать прокси."""
    return (
        f"Бот не запущен: нет связи с api.telegram.org "
        f"({error.__class__.__name__}).\n"
        "Проверьте интернет и VPN. Если Telegram недоступен напрямую, "
        "впишите прокси в .env, например:\n"
        "PROXY_URL=http://host:port или PROXY_URL=socks5://host:port"
    )


async def main() -> None:
    """Настраивает бота и запускает получение сообщений (long polling)."""
    # Токен читаем строго из .env рядом с bot.py: без явного пути
    # python-dotenv поднимается по дереву папок и может взять токен
    # из соседнего проекта.
    load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    bot = Bot(
        token=read_token(),
        session=create_session(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    # MemoryStorage держит состояние в памяти: при перезапуске
    # незаконченные диалоги сбрасываются, для учебного проекта хватает.
    dp = Dispatcher(storage=MemoryStorage())

    register_handlers(dp)

    # Снимаем старый вебхук, чтобы polling не конфликтовал с ним.
    # Telegram может быть недоступен на старте (выключен VPN или прокси):
    # это не повод падать — polling сам переподключится, когда сеть
    # вернётся, а причина уходит в лог.
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as error:
        logging.warning(
            "Telegram недоступен на старте (%s). Жду сеть: бот начнёт "
            "принимать сообщения, как только соединение появится.",
            error,
        )

    # Опрос Telegram. Если прокси или VPN выключены, соединения нет:
    # бот не завершается, а пробует снова каждые 15 секунд — как только
    # сеть появится, он начнёт принимать сообщения без перезапуска.
    while True:
        try:
            await dp.start_polling(bot)
            break
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logging.warning(
                "Связи с Telegram нет (%s). Повторная попытка через 15 сек.",
                error,
            )
            await asyncio.sleep(15)

    await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as error:
        # Понятное сообщение вместо трейсбека, если не заполнен .env
        # или для прокси не хватает aiohttp-socks.
        print(f"Бот не запущен: {error}")
        sys.exit(1)
    except NETWORK_ERRORS as error:
        # Сеть не пускает к api.telegram.org: это не ошибка кода,
        # а ограничение доступа.
        print(network_error_message(error))
        sys.exit(1)
    except TelegramUnauthorizedError:
        # Токен не принят Telegram (401): подсказываем проверить .env.
        print(
            "Бот не запущен: Telegram не принял токен (ошибка авторизации). "
            "Проверьте BOT_TOKEN в .env: возможно, токен устарел или "
            "перепутан с другим ботом."
        )
        sys.exit(1)
    except KeyboardInterrupt:
        print("Бот остановлен вручную.")
