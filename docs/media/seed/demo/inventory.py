"""A tiny stock tracker."""


def total_value(items):
    return sum(i["price"] * i["qty"] for i in items)


def low_stock(items, limit=5):
    return [i["name"] for i in items if i["qty"] < limit]
