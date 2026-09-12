"""
Категории песни (доп. ТЗ "KJ Pro — функции оригинальной роли KJ", пункты
KJ-01/KJ-03/KJ-07) — по решению пользователя это то же самое, что уже было
в проекте как "услуга/тариф" (модель Service, см. её докстринг в
models.py): один и тот же список, гость выбирает его при заказе (см.
routes/guest.py::list_services, уже работает и не менялось), а роль 2 (KJ)
теперь может им управлять — добавлять, менять название/описание/цену,
включать/выключать "бесплатно" для конкретной категории отдельно (KJ-07) —
это отдельный переключатель, не совпадающий с общим клубным "Бесплатным
вечером" (KJ-02, см. club_service.py::set_free_evening), и удалять
неиспользуемые категории.

Деньги за категорию по факту не проходят через эту систему как настоящий
платёж (решение пользователя: "деньги проходят через финансовую систему
клуба, но не через караоке программу") — цена здесь нужна для учёта/
отчётности и для расчётов с VIP-балансом (services/billing_service.py),
а не для приёма реальных платежей от обычных гостей.

DEFAULT_CATEGORIES — реальные данные из старого бота (таблица services,
клуб "Voice", venue_id=1, файл karaoke.db в корне репозитория) — по
явному решению пользователя "все недостающие данные ты по умолчанию
берёшь из оригинал бота". Используются только для ленивого
автозаполнения: если у клуба ещё нет ни одной категории (новый клуб, или
клуб без единой Service-записи), они подставляются при первом обращении к
списку, чтобы KJ не начинал с пустого экрана.
"""
from decimal import Decimal, InvalidOperation

from extensions import db
from models import Order, Service

DEFAULT_CATEGORIES = [
    {"name": "KARAOKE", "description": "Обычное караоке", "price": Decimal("35"), "is_free": False},
    {"name": "KARAOKE BACK", "description": "Караоке с бэквокалом", "price": Decimal("35"), "is_free": False},
    {
        "name": "INTERNET",
        "description": (
            "Любой заказ послушать или спеть из интернета. Послушать — можно вне очереди. "
            "Спеть — строго по очереди."
        ),
        "price": Decimal("100"),
        "is_free": False,
    },
    {
        "name": "KJ VOCAL",
        "description": "Заказ спеть KJ лично, или спеть с KJ дуэтом",
        "price": Decimal("200"),
        "is_free": False,
    },
    {"name": "CRAZY", "description": "Песня вне очереди", "price": Decimal("1000"), "is_free": False},
    {"name": "BONUS", "description": "Бесплатный бонус — ставит только KJ", "price": Decimal("0"), "is_free": True},
]


class CategoryServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def list_categories(club_id: int) -> list[Service]:
    """Список категорий клуба. Если у клуба ещё нет ни одной — заводим
    сразу набор по умолчанию (см. докстринг файла), а не показываем KJ
    пустой экран при первом открытии."""
    categories = Service.query.filter_by(club_id=club_id).order_by(Service.id.asc()).all()
    if categories:
        return categories

    for data in DEFAULT_CATEGORIES:
        db.session.add(Service(club_id=club_id, **data))
    db.session.commit()
    return Service.query.filter_by(club_id=club_id).order_by(Service.id.asc()).all()


def _parse_price(raw) -> Decimal:
    try:
        price = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        raise CategoryServiceError("VALIDATION_ERROR", "Цена должна быть числом")
    if price < 0:
        raise CategoryServiceError("VALIDATION_ERROR", "Цена не может быть отрицательной")
    return price


def create_category(club_id: int, name, description, price, is_free) -> Service:
    name = (name or "").strip()
    if not name:
        raise CategoryServiceError("VALIDATION_ERROR", "Название категории обязательно")
    category = Service(
        club_id=club_id,
        name=name,
        description=(description or None),
        price=_parse_price(price),
        is_free=bool(is_free),
    )
    db.session.add(category)
    db.session.commit()
    return category


def update_category(club_id: int, category_id: int, **fields) -> Service:
    category = Service.query.filter_by(id=category_id, club_id=club_id).first()
    if category is None:
        raise CategoryServiceError("NOT_FOUND", "Категория не найдена")
    if "name" in fields:
        name = (fields["name"] or "").strip()
        if not name:
            raise CategoryServiceError("VALIDATION_ERROR", "Название категории обязательно")
        category.name = name
    if "description" in fields:
        category.description = fields["description"] or None
    if "price" in fields:
        category.price = _parse_price(fields["price"])
    if "is_free" in fields:
        category.is_free = bool(fields["is_free"])
    db.session.commit()
    return category


def delete_category(club_id: int, category_id: int) -> None:
    """Удалить категорию нельзя, если она уже встречалась в каких-то
    заказах — иначе история/отчётность потеряла бы, чем на самом деле был
    тот заказ. В этом случае категорию можно только переименовать или
    поменять ей цену, а не удалить."""
    category = Service.query.filter_by(id=category_id, club_id=club_id).first()
    if category is None:
        raise CategoryServiceError("NOT_FOUND", "Категория не найдена")
    in_use = Order.query.filter_by(service_id=category_id).first() is not None
    if in_use:
        raise CategoryServiceError(
            "CATEGORY_IN_USE",
            "Эта категория уже использовалась в заказах — удалить нельзя, можно переименовать или изменить цену",
        )
    db.session.delete(category)
    db.session.commit()
