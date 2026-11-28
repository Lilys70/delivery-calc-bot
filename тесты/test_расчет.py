"""Тесты расчёта стоимости доставки (данные/cities.py).

Что проверяем:
- формулу из ТЗ: ставка отправления + вес * RATE_PER_KG + надбавка;
- все четыре города отправления и назначения из кнопок бота;
- что города в обоих справочниках совпадают: кнопки одни и те же;
- границы допустимого веса MIN_WEIGHT и MAX_WEIGHT;
- что стоимость — целое число рублей;
- что каждый килограмм прибавляет ровно RATE_PER_KG;
- что неизвестный город даёт ошибку, а не молчаливый ноль.

Telegram и сеть здесь не нужны: проверяется только арифметика,
поэтому тесты идут за доли секунды и не зависят от прокси.
"""

import unittest

from данные.cities import (
    CITIES,
    MAX_WEIGHT,
    MIN_WEIGHT,
    ORIGIN_RATES,
    RATE_PER_KG,
    calculate_cost,
)


class CostFormulaTestCase(unittest.TestCase):
    """Стоимость по формуле из ТЗ для всех городов."""

    def test_formula_matches_origin_rate_and_surcharge(self):
        """Стоимость = ставка отправления + вес * ставка + надбавка."""
        for origin, base_rate in ORIGIN_RATES.items():
            for destination, surcharge in CITIES.items():
                with self.subTest(origin=origin, destination=destination):
                    expected = base_rate + 5 * RATE_PER_KG + surcharge
                    self.assertEqual(
                        calculate_cost(origin, destination, 5), expected
                    )

    def test_moscow_to_moscow_12_5_kg(self):
        """Москва → Москва, 12.5 кг: 500 + 1250 + 500 = 2250 руб."""
        self.assertEqual(
            calculate_cost("Москва", "Москва", 12.5), 2250
        )

    def test_spb_to_moscow_5_kg(self):
        """Санкт-Петербург → Москва, 5 кг: 400 + 500 + 500 = 1400 руб."""
        self.assertEqual(
            calculate_cost("Санкт-Петербург", "Москва", 5), 1400
        )

    def test_novosibirsk_to_ekaterinburg_10_kg(self):
        """Новосибирск → Екатеринбург, 10 кг: 600 + 1000 + 150 = 1750."""
        self.assertEqual(
            calculate_cost("Новосибирск", "Екатеринбург", 10), 1750
        )

    def test_moscow_to_ekaterinburg_min_weight(self):
        """Москва → Екатеринбург, 0.1 кг: 500 + 10 + 150 = 660 руб."""
        self.assertEqual(
            calculate_cost("Москва", "Екатеринбург", MIN_WEIGHT), 660
        )

    def test_moscow_to_moscow_min_weight(self):
        """Москва → Москва, 0.1 кг: 500 + 10 + 500 = 1010 руб."""
        self.assertEqual(
            calculate_cost("Москва", "Москва", MIN_WEIGHT), 1010
        )

    def test_max_weight(self):
        """Максимальные 10000 кг: 500 + 1 000 000 + 500 = 1 001 000 руб."""
        self.assertEqual(
            calculate_cost("Москва", "Москва", MAX_WEIGHT), 1001000
        )

    def test_cost_is_integer(self):
        """Стоимость всегда целое число рублей, без копеек."""
        for weight in (0.1, 0.33, 1, 12.5, 99.9):
            with self.subTest(weight=weight):
                cost = calculate_cost("Москва", "Москва", weight)
                self.assertIsInstance(cost, int)

    def test_every_kg_adds_rate_per_kg(self):
        """Разница между 7 и 6 кг равна ставке за килограмм."""
        for origin in ORIGIN_RATES:
            for destination in CITIES:
                with self.subTest(origin=origin, destination=destination):
                    difference = (
                        calculate_cost(origin, destination, 7)
                        - calculate_cost(origin, destination, 6)
                    )
                    self.assertEqual(difference, RATE_PER_KG)

    def test_more_city_surcharge_costs_more(self):
        """Москва дороже Екатеринбурга при одинаковом маршруте."""
        self.assertGreater(
            calculate_cost("Москва", "Москва", 3),
            calculate_cost("Москва", "Екатеринбург", 3),
        )

    def test_expensive_origin_costs_more(self):
        """Из Новосибирска (600) дороже, чем из Москвы (500)."""
        self.assertGreater(
            calculate_cost("Новосибирск", "Москва", 3),
            calculate_cost("Москва", "Москва", 3),
        )

    def test_both_directions_have_all_cities(self):
        """Кнопки «Откуда» и «Куда» показывают одни и те же города."""
        self.assertEqual(set(CITIES), set(ORIGIN_RATES))

    def test_unknown_origin_raises_key_error(self):
        """Города отправления нет в справочнике — ошибка, а не ноль."""
        with self.assertRaises(KeyError):
            calculate_cost("Казань", "Москва", 5)

    def test_unknown_destination_raises_key_error(self):
        """Города назначения нет в справочнике — ошибка, а не ноль."""
        with self.assertRaises(KeyError):
            calculate_cost("Москва", "Казань", 5)


if __name__ == "__main__":
    unittest.main()
