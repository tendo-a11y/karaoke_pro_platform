"""backfill table_groups/table_group_members for already-seated guests

Revision ID: 92cb15093592
Revises: a47725a2b8ae
Create Date: 2026-09-29 21:00:00.000000

ДОБАВЛЕНО (2026-09-29, жалоба пользователя: карточка стола в KJ Panel
"ни в одной из карточек ничего нет" для столов, где реально сидят гости
с активными заказами) — только данные, без изменения схемы.

Корень проблемы: TableGroup/TableGroupMember (см. миграцию
d5eaf2153273 от 2026-09-06) заполняются только в момент, когда гость
входит через Google и выбирает стол (routes/guest.py::link_google ->
table_group_service.ensure_session_group_state). Карточка стола
(routes/kj.py::get_table_group, добавлена 2026-09-28) и прямое закрытие
стола (table_close_service.close_table_directly) читают ИСКЛЮЧИТЕЛЬНО
эти две таблицы — а не GuestStatus и не Order, как это делает доска
"Заказы по столам" (table_board_service). Гости, которые сели за стол и
вошли через Google ДО того, как этот шлюз появился в link_google, так и
остались без строки TableGroupMember — их стол (GuestStatus.table_no)
живой и правильный, реальные заказы есть, но карточка стола о них ничего
не знает и показывает пустоту вместо списка гостей.

Это разовая проблема момента выката, а не постоянный пробел в логике:
начиная с этой миграции (и без неё, для всех НОВЫХ входов через Google)
ensure_session_group_state вызывается всегда, так что строка
TableGroupMember появляется сама, синхронно с GuestStatus.table_no.
Разъехаться они могли только для тех, кто вошёл раньше момента, когда
этот вызов появился в коде.

Что делает эта миграция: для каждого стола, где по GuestStatus.table_no
кто-то сейчас сидит, но соответствующей строки TableGroupMember ещё нет —
дописывает недостающее членство (TableGroupMember), а если для стола
вообще нет строки TableGroup — создаёт и её. "Дата начала" такой
досозданной группы (TableGroup.created_at, от неё считается чек при
закрытии стола, см. table_close_service._build_receipt) берётся как
время САМОГО СТАРОГО ещё не решённого (pending/processing/queued/error)
заказа этого стола — а не "сейчас" (тогда уже сыгранные сегодня песни
пропали бы из чека) и не "давно" (тогда в чек рискуют попасть чужие,
уже отыгранные заказы с прошлых вечеров за тем же номером стола, если
он использовался другой компанией раньше). Если у стола прямо сейчас нет
ни одного ещё не решённого заказа — берётся время выполнения миграции;
чек при закрытии такого стола в этом случае может недосчитать уже
сыгранные сегодня песни, это осознанный компромисс в сторону "не
приписать лишнего", KJ в моменте видит стол своими глазами и может
досчитать вручную.

Столов, где заказы поставлены самим KJ вручную (services/vdj_service.py::
add_manual_song/claim_vdj_queue_item, telegram_user_id=-1, не настоящий
гость) — эта миграция не касается: для sentinel-guest'а -1 никогда не
создаётся строка GuestStatus, значит и заполнять здесь нечего, карточка
стола для таких столов по-прежнему будет пустой (это отдельный,
самостоятельный вопрос — не путать с этим бэкфиллом).

Идемпотентна: повторный запуск (или запуск на базе, где этот пробел уже
не воспроизводится) ничего не меняет — вставляются только недостающие
строки.
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '92cb15093592'
down_revision = 'a47725a2b8ae'
branch_labels = None
depends_on = None

# Только нужные колонки — самодостаточное описание таблиц для миграции
# (не импортируем модели напрямую, чтобы миграция не сломалась от будущих
# изменений models.py, обычная практика Alembic).
guest_statuses = sa.table(
    'guest_statuses',
    sa.column('club_id', sa.Integer),
    sa.column('telegram_user_id', sa.BigInteger),
    sa.column('table_no', sa.Integer),
)
table_groups = sa.table(
    'table_groups',
    sa.column('id', sa.Integer),
    sa.column('club_id', sa.Integer),
    sa.column('table_no', sa.Integer),
    sa.column('admin_guest_id', sa.BigInteger),
    sa.column('created_at', sa.DateTime(timezone=True)),
)
table_group_members = sa.table(
    'table_group_members',
    sa.column('id', sa.Integer),
    sa.column('club_id', sa.Integer),
    sa.column('table_no', sa.Integer),
    sa.column('guest_id', sa.BigInteger),
    sa.column('joined_at', sa.DateTime(timezone=True)),
)
orders = sa.table(
    'orders',
    sa.column('club_id', sa.Integer),
    sa.column('table_no', sa.Integer),
    sa.column('status', sa.String),
    sa.column('created_at', sa.DateTime(timezone=True)),
)

# Те же значения, что models.STATUS_PENDING/PROCESSING/QUEUED/ERROR и
# table_board_service.ACTIVE_TABLE_STATUSES — продублированы буквально,
# а не импортированы, по той же причине (самодостаточность миграции).
ACTIVE_ORDER_STATUSES = ('pending', 'processing', 'queued', 'error')


def upgrade():
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    seated = bind.execute(
        sa.select(
            guest_statuses.c.club_id,
            guest_statuses.c.telegram_user_id,
            guest_statuses.c.table_no,
        ).where(guest_statuses.c.table_no.isnot(None))
    ).fetchall()

    by_table: dict[tuple[int, int], list[int]] = {}
    for club_id, guest_id, table_no in seated:
        by_table.setdefault((club_id, table_no), []).append(guest_id)

    for (club_id, table_no), guest_ids in by_table.items():
        existing_group_id = bind.execute(
            sa.select(table_groups.c.id)
            .where(table_groups.c.club_id == club_id, table_groups.c.table_no == table_no)
        ).scalar()

        existing_member_ids = {
            row[0] for row in bind.execute(
                sa.select(table_group_members.c.guest_id)
                .where(
                    table_group_members.c.club_id == club_id,
                    table_group_members.c.table_no == table_no,
                )
            ).fetchall()
        }
        missing_guest_ids = [gid for gid in guest_ids if gid not in existing_member_ids]
        if not missing_guest_ids:
            continue

        if existing_group_id is None:
            earliest_active_order_at = bind.execute(
                sa.select(sa.func.min(orders.c.created_at))
                .where(
                    orders.c.club_id == club_id,
                    orders.c.table_no == table_no,
                    orders.c.status.in_(ACTIVE_ORDER_STATUSES),
                )
            ).scalar()
            created_at = earliest_active_order_at or now
            admin_guest_id = min(guest_ids)
            bind.execute(
                table_groups.insert().values(
                    club_id=club_id,
                    table_no=table_no,
                    admin_guest_id=admin_guest_id,
                    created_at=created_at,
                )
            )

        for guest_id in missing_guest_ids:
            bind.execute(
                table_group_members.insert().values(
                    club_id=club_id,
                    table_no=table_no,
                    guest_id=guest_id,
                    joined_at=now,
                )
            )


def downgrade():
    # Дописанные здесь строки неотличимы от тех, что к моменту отката уже
    # могли появиться обычным путём (тот же гость мог обычным образом
    # войти и создать то же самое членство после апгрейда) — откатывать
    # нечего и незачем, сама миграция безопасна и идемпотентна при
    # повторном запуске upgrade.
    pass
