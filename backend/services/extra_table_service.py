"""
Дополнительные столы между обычными (запрос пользователя 2026-10-13: "полная
посадка в зале, вынесли 2 доп. стола — их как-то надо вставить в очередь").

KJ во вкладке "Столы" добавляет стол "после стола N" и по желанию даёт ему
название — получается "N/1 (название)", следующий после того же стола —
"N/2". Внутренний номер — N*1000 + k (см. models.ExtraTable), вся остальная
механика столов (заказы, групповой стол, чек, закрытие) работает с ним как
с обычным номером. В круге очереди доп. столы идут сразу после своего
стола, по порядку N/1, N/2, ... Стол постоянный, пока KJ его не удалит.
"""
from extensions import db
from models import (
    STATUS_ERROR,
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_QUEUED,
    Club,
    ExtraTable,
    Order,
    TableGroup,
)

EXTRA_BASE = 1000
NAME_MAX = 40
_ACTIVE = (STATUS_PENDING, STATUS_PROCESSING, STATUS_QUEUED, STATUS_ERROR)


class ExtraTableError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def is_extra(table_no) -> bool:
    return isinstance(table_no, int) and table_no >= EXTRA_BASE


def label(table_no) -> str:
    if table_no is None:
        return "—"
    if is_extra(table_no):
        return f"{table_no // EXTRA_BASE}/{table_no % EXTRA_BASE}"
    return str(table_no)


def list_extra(club_id: int) -> list[ExtraTable]:
    return (
        ExtraTable.query
        .filter_by(club_id=club_id)
        .order_by(ExtraTable.after_table.asc(), ExtraTable.sub_index.asc())
        .all()
    )


def is_valid_table(club: Club | None, table_no: int) -> bool:
    """Существует ли такой стол в клубе: обычный 1..table_count или доп. стол."""
    if club is None:
        return True
    if is_extra(table_no):
        return ExtraTable.query.filter_by(club_id=club.club_id, table_no=table_no).first() is not None
    return club.table_count is None or table_no <= club.table_count


def out_of_range_message(club: Club) -> str:
    return f"В этом клубе {club.table_count} столов — выберите номер от 1 до {club.table_count} или доп. стол из списка"


def table_sequence(club: Club, table_count: int) -> list[int]:
    """Порядок обхода столов в круге: 1, 2, ..., 7, 7/1, 7/2, 8, ..."""
    extras: dict[int, list[int]] = {}
    for extra in list_extra(club.club_id):
        extras.setdefault(extra.after_table, []).append(extra.table_no)
    sequence = []
    for table_no in range(1, table_count + 1):
        sequence.append(table_no)
        sequence.extend(extras.get(table_no, []))
    # Доп. стол после стола, которого уже нет (число столов уменьшили) — в конец.
    for after_table in sorted(extras):
        if after_table > table_count:
            sequence.extend(extras[after_table])
    return sequence


def create(club: Club, after_table, name=None) -> ExtraTable:
    if isinstance(after_table, bool) or not isinstance(after_table, int) or after_table < 1:
        raise ExtraTableError("VALIDATION_ERROR", "Укажите, после какого стола поставить доп. стол")
    if club.table_count is not None and after_table > club.table_count:
        raise ExtraTableError("VALIDATION_ERROR", f"В клубе {club.table_count} столов — выберите стол от 1 до {club.table_count}")
    if name is not None and not isinstance(name, str):
        raise ExtraTableError("VALIDATION_ERROR", "Название — текст")
    name = (name or "").strip()[:NAME_MAX] or None
    last = (
        db.session.query(db.func.max(ExtraTable.sub_index))
        .filter(ExtraTable.club_id == club.club_id, ExtraTable.after_table == after_table)
        .scalar()
    ) or 0
    sub_index = last + 1
    if sub_index >= EXTRA_BASE:
        raise ExtraTableError("VALIDATION_ERROR", "Слишком много доп. столов после этого стола")
    extra = ExtraTable(
        club_id=club.club_id,
        table_no=after_table * EXTRA_BASE + sub_index,
        after_table=after_table,
        sub_index=sub_index,
        name=name,
    )
    db.session.add(extra)
    db.session.commit()
    return extra


def delete(club: Club, table_no: int) -> None:
    extra = ExtraTable.query.filter_by(club_id=club.club_id, table_no=table_no).first()
    if extra is None:
        raise ExtraTableError("NOT_FOUND", "Такого доп. стола нет", 404)
    if TableGroup.query.filter_by(club_id=club.club_id, table_no=table_no).first() is not None:
        raise ExtraTableError("TABLE_BUSY", f"За столом {extra.label} сидят гости — сначала закройте стол", 409)
    busy = (
        Order.query
        .filter(Order.club_id == club.club_id, Order.table_no == table_no, Order.status.in_(_ACTIVE))
        .first()
    )
    if busy is not None:
        raise ExtraTableError("TABLE_BUSY", f"У стола {extra.label} есть заказы — сначала закройте стол", 409)
    db.session.delete(extra)
    db.session.commit()
