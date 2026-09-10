"""
Постоянный профиль гостя (ТЗ п.45). См. models.py::GuestAccount и
services/google_auth_service.py для проверки Google-подтверждения.
"""
from extensions import db
from models import GuestAccount


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
