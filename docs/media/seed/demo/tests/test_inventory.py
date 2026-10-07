from inventory import low_stock, total_value

ITEMS = [{"name": "tea", "price": 4.5, "qty": 10}, {"name": "cups", "price": 2.0, "qty": 3}]


def test_total_value():
    assert total_value(ITEMS) == 51.0


def test_low_stock():
    assert low_stock(ITEMS) == ["cups"]
