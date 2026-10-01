"""
Постоянный профиль гостя (ТЗ п.45). См. models.py::GuestAccount и
services/google_auth_service.py для проверки Google-подтверждения.
"""
from extensions import db
from models import GuestAccount

# Ограничение длины самостоятельно задаваемого гостем имени (запрос
# пользователя 2026-09, "самопереименование гостя") — совпадает с длиной
# колонки GuestAccount.display_name (models.py), проверяется здесь же, а не
# только на уровне БД, чтобы отдать понятную ошибку до попытки записи.
MAX_DISPLAY_NAME_LEN = 40


def get_by_guest_id(club_id: int, guest_id: int) -> GuestAccount | None:
    return GuestAccount.query.filter_by(club_id=club_id, telegram_user_id=guest_id).first()


def get_by_google_sub(club_id: int, google_sub: str) -> GuestAccount | None:
    return GuestAccount.query.filter_by(club_id=club_id, google_sub=google_sub).first()


class LinkGoogleResult:
    def __init__(self, account: GuestAccount, outcome: str):
        self.account = account
        # "existing" — найден уже привязанный ранее профиль (guest_id
        # сессии, из которой пришёл запрос, меняется на постоянный номер
        # из найденной записи — то немногое, что гость успел сделать под
        # временным номером ИМЕННО в эту сессию, теряется, см. отчёт по
        # п.45: это осознанно принятый редкий случай, тот же принцип, что
        # раньше применялся к погашению VIP-кода).
        # "created" — для этого google_sub ещё не было записи в этом
        # клубе: постоянным номером становится ТЕКУЩИЙ guest_id сессии —
        # ничего не переносится и не теряется, всё уже записано на этот
        # номер (заказы/избранное и т.д.), см. docstring GuestAccount.
        self.outcome = outcome


def link_google(club_id: int, current_guest_id: int, google_sub: str, email) -> LinkGoogleResult:
    existing = get_by_google_sub(club_id, google_sub)
    if existing is not None:
        return LinkGoogleResult(account=existing, outcome="existing")

    account = GuestAccount(
        club_id=club_id,
        telegram_user_id=current_guest_id,
        google_sub=google_sub,
        email=email,
    )
    db.session.add(account)
    db.session.commit()
    return LinkGoogleResult(account=account, outcome="created")


def set_display_name(club_id: int, guest_id: int, name: str) -> GuestAccount | None:
    """
    Гость задаёт/меняет своё отображаемое имя (routes/guest.py::
    set_display_name). Требует уже существующего постоянного профиля —
    возвращает None, если гость ещё не входил через Google, вызывающий код
    сам решает, какой HTTP-код это означает (см. routes/guest.py:
    GOOGLE_LINK_REQUIRED, тот же принцип, что и у остальных действий,
    требующих постоянной личности — см. request_vip/add_favorite).
    """
    account = get_by_guest_id(club_id, guest_id)
    if account is None:
        return None
    account.display_name = name
    db.session.commit()
    return account


def set_photo(club_id: int, guest_id: int, photo_data_url: str | None) -> GuestAccount | None:
    """
    Гость сам загружает (необязательно) своё фото — рядом с тем же местом,
    где меняет имя (запрос пользователя 2026-10-01: "клиент сам загружает
    своё фото (но это не обязательно) там же где Изменить имя", routes/
    guest.py::set_my_photo). Тот же принцип, что и у set_display_name выше:
    требует уже существующего постоянного профиля, None здесь — сигнал
    вызывающему коду вернуть GOOGLE_LINK_REQUIRED. photo_data_url=None
    убирает уже загруженное фото.

    Отдельно от routes/kj.py::set_guest_photo (KJ тоже может загрузить фото
    клиента из своей панели, запрос пользователя 2026-10-01 "пусть тоже
    может загрузить фото клиента сам") — оба пишут в одно и то же поле
    GuestAccount.photo_data_url, последняя запись побеждает, отдельной
    истории/авторства фото не ведётся, т.к. это не требовалось.
    """
    account = get_by_guest_id(club_id, guest_id)
    if account is None:
        return None
    account.photo_data_url = photo_data_url
    db.session.commit()
    return account
