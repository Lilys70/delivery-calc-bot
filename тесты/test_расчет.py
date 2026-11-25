"""Тесты расчёта стоимости доставки (данные/cities.py).

Что проверяем:
- формулу из ТЗ: стоимость = BASE_RATE + вес * RATE_PER_KG + надбавка;
- все четыре города, которые бот показывает кнопками;
- границы допустимого веса MIN_WEIGHT и MAX_WEIGHT;
- что стоимость — целое число рублей;
- что каждый килограмм прибавляет ровно RATE_PER_KG;
- что неизвестный город даёт ошибку, а не молчаливый ноль.

Telegram и сеть здесь не нужны: проверяется только арифметика,
поэтому тесты идут за доли секунды и не зависят от прокси.
"""

import unittest

from данные.cities import (
    BASE_RATE,
    CITIES,
    MAX_WEIGHT,
    MIN_WEIGHT,
    RATE_PER_KG,
    calculate_cost,
)


class CostFormulaTestCase(unittest.TestCase):
    """Стоимость по формуле из ТЗ для всех городов."""

    def test_formula_matches_base_rate_and_surcharge(self):
        """Стоимость = базовая ставка + вес * ставка + надбавка города."""
        for city, surcharge in CITIES.items():
            with self.subTest(city=city):
                expected = BASE_RATE + 5 * RATE_PER_KG + surcharge
                self.assertEqual(calculate_cost(city, 5), expected)

    def test_moscow_12_5_kg(self):
        """Москва, 12.5 кг: 500 + 1250 + 500 = 2250 руб."""
        self.assertEqual(calculate_cost("Москва", 12.5), 2250)

    def test_spb_5_kg(self):
        """Санкт-Петербург, 5 кг: 500 + 500 + 300 = 1300 руб."""
        self.assertEqual(calculate_cost("Санкт-Петербург", 5), 1300)

    def test_novosibirsk_10_kg(self):
        """Новосибирск, 10 кг: 500 + 1000 + 200 = 1700 руб."""
        self.assertEqual(calculate_cost("Новосибирск", 10), 1700)

    def test_ekaterinburg_min_weight(self):
        """Екатеринбург, минимальные 0.1 кг: 500 + 10 + 150 = 660 руб."""
        self.assertEqual(calculate_cost("Екатеринбург", MIN_WEIGHT), 660)

    def test_moscow_min_weight(self):
        """Москва, минимальные 0.1 кг: 500 + 10 + 500 = 1010 руб."""
        self.assertEqual(calculate_cost("Москва", MIN_WEIGHT), 1010)

    def test_max_weight(self):
        """Максимальные 10000 кг: 500 + 1 000 000 + 500 = 1 001 000 руб."""
        self.assertEqual(calculate_cost("Москва", MAX_WEIGHT), 1001000)

    def test_cost_is_integer(self):
        """Стоимость всегда целое число рублей, без копеек."""
        for weight in (0.1, 0.33, 1, 12.5, 99.9):
            with self.subTest(weight=weight):
                cost = calculate_cost("Москва", weight)
                self.assertIsInstance(cost, int)

    def test_every_kg_adds_rate_per_kg(self):
        """Разница между 7 и 6 кг равна ставке за килограмм."""
        for city in CITIES:
            with self.subTest(city=city):
                difference = (
                    calculate_cost(city, 7) - calculate_cost(city, 6)
                )
                self.assertEqual(difference, RATE_PER_KG)

    def test_more_city_surcharge_costs_more(self):
        """Москва с надбавкой 500 дороже Екатеринбурга с 150."""
        self.assertGreater(
            calculate_cost("Москва", 3),
            calculate_cost("Екатеринбург", 3),
        )

    def test_unknown_city_raises_key_error(self):
        """Города нет в справочнике — ошибка, а не бесплатная доставка."""
        with self.assertRaises(KeyError):
            calculate_cost("Казань", 5)


if __name__ == "__main__":
    unittest.main()
