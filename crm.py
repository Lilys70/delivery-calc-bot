"""Передача заявки на доставку в Битрикс24.

Заявка уходит POST-запросом на входящий вебхук Битрикс24 методом
crm.deal.add (создание сделки). Если адрес вебхука не задан или сеть
недоступна, функция не роняет бота: пишет причину в консоль и
возвращает управление.

Адрес вебхука хранится в .env (BITRIX_WEBHOOK_URL), в коде и в
репозитории его быть не должно.
"""

import os

import requests

# Винительный падеж для запасной ветки названия сделки («Доставка в
# Москву»): она нужна, если в FSM не оказалось города отправления.
PADEZH = {
    "Москва": "Москву",
    "Санкт-Петербург": "Санкт-Петербург",
    "Новосибирск": "Новосибирск",
    "Екатеринбург": "Екатеринбург",
}


def send_lead_to_bitrix(name, phone, origin, city, weight, cost=None):
    """Отправляет заявку на доставку в Битрикс24.

    Параметры:
    - name   — имя клиента;
    - phone  — телефон;
    - origin — город отправления (None, если расчёт не делался);
    - city   — город назначения (None, если расчёт не делался);
    - weight — вес груза в килограммах (None, если расчёт не делался);
    - cost   — рассчитанная стоимость доставки, она же сумма сделки
               (None, если расчёт не делался, — в сделку уйдёт 0).

    Ошибки сети и отказы сервера наружу не поднимаются: бот продолжает
    работу, а статус ответа и текст ошибки печатаются в консоль.

    Возвращает True, если Битрикс24 принял сделку (ответ 2xx без ошибки
    метода), и False, если вебхук не задан, сеть недоступна или сервер
    вернул ошибку. По этому признаку bot.py решает, отправлять ли
    уведомление оператору.
    """
    # Основное имя переменной — BITRIX_WEBHOOK_URL; старое BITRIX_WEBHOOK
    # читаем как запасное, чтобы уже заполненный .env продолжал работать.
    bitrix_webhook_url = os.getenv("BITRIX_WEBHOOK_URL") or os.getenv(
        "BITRIX_WEBHOOK"
    )
    if not bitrix_webhook_url:
        print("[CRM MOCK] URL вебхука не задан")
        return False

    # Название сделки: маршрут «Доставка Москва → Санкт-Петербург».
    # Если расчёта не было, названия городов нет — берём нейтральное,
    # чтобы в CRM не пришло «Доставка → None».
    title = "Новая заявка на доставку"
    if origin and city:
        title = f"Доставка {origin} → {city}"
    elif city:
        title = f"Доставка в {PADEZH.get(city, city)}"

    # Комментарий — карточка заявки для менеджера: имя и телефон пишем
    # текстом, потому что поля NAME и PHONE относятся к контакту и на
    # карточке сделки могут не отображаться.
    comment = (
        f"Имя: {name}\n"
        f"Телефон: {phone}\n"
        f"Откуда: {origin or '-'}\n"
        f"Куда: {city or '-'}\n"
        f"Вес: {weight or '-'} кг"
    )

    # Поля сделки Битрикс24 принимает вложенно, внутри ключа "fields".
    # OPPORTUNITY — сумма сделки; без расчёта отправляем 0.
    payload = {
        "fields": {
            "TITLE": title,
            "OPPORTUNITY": cost if cost is not None else 0,
            "NAME": name,
            "PHONE": [{"VALUE": phone, "VALUE_TYPE": "WORK"}],
            "COMMENTS": comment,
        }
    }

    try:
        # Запросы к Битрикс24 идут напрямую, мимо системного прокси и VPN.
        # trust_env=False запрещает requests читать HTTP_PROXY/HTTPS_PROXY
        # из окружения, явные None в proxies отключают системные настройки.
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                f"{bitrix_webhook_url}crm.deal.add.json",
                json=payload,
                timeout=10,
                proxies={"http": None, "https": None},
            )
        print(f"[CRM] Статус ответа: {response.status_code}")
        print(f"[CRM] Ответ Битрикс24: {response.text}")
    except Exception as e:
        # Сеть, DNS, таймаут: бот не должен падать из-за CRM.
        print(f"[CRM ERROR] {e}")
        return False

    # Битрикс24 отвечает 200 и на ошибки метода, поэтому кроме статуса
    # проверяем, что в ответе нет ключа error.
    accepted = 200 <= response.status_code < 300
    return accepted and '"error"' not in response.text


if __name__ == "__main__":
    # Быстрая проверка без Telegram: python crm.py
    send_lead_to_bitrix(
        name="Иван",
        phone="+7 900 000-00-00",
        origin="Москва",
        city="Санкт-Петербург",
        weight=12.5,
        cost=2250,
    )
