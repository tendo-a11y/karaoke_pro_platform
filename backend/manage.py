"""
Небольшие административные команды, пока нет отдельной админки.

ВАЖНО про схему БД: с этого шага источник истины для схемы — Alembic-
миграции в migrations/ (Flask-Migrate), а не db.create_all(). Разворачивать
реальную БД (стейджинг/прод) нужно через:

    export FLASK_APP=wsgi.py
    flask db upgrade

`init-db` ниже оставлен только для быстрого локального/одноразового
использования (например, когда лень поднимать миграции для песочницы) —
он не пишет строку в alembic_version, поэтому смешивать его с `flask db
upgrade` на одной и той же базе нельзя: Alembic не будет знать, что
таблицы уже есть, и попытается создать их заново.

    python manage.py init-db
    python manage.py add-club --club-id 1 --name "Absolutis Chisinau"
    python manage.py add-kj --telegram-id 5450586697 --club-id 1 --name "DJ Vasile"
    python manage.py kj-link --telegram-id 5450586697 --panel-url http://localhost:3000
    python manage.py add-admin --telegram-id 111222333 --club-id 1 --name "Owner"
    python manage.py admin-link --telegram-id 111222333 --panel-url http://localhost:3001
    python manage.py set-admin-google-email --telegram-id 111222333 --google-email you@gmail.com
    python manage.py set-bridge-token --club-id 1

club-id рекомендуется указывать равным venue_id из существующей SQLite базы
karaoke_pro, чтобы клуб в новой системе соответствовал уже существующему
клубу в боте (ТЗ п.25, п.31).
"""
import argparse
import secrets

from app import create_app
from auth import issue_admin_token, issue_guest_token, issue_kj_token
from extensions import db
from models import AdminUser, Club, KJOperator


def cmd_init_db(args):
    app = create_app()
    with app.app_context():
        db.create_all()
    print("OK: таблицы созданы")


def cmd_add_club(args):
    app = create_app()
    with app.app_context():
        club = db.session.get(Club, args.club_id)
        if club:
            # ИЗМЕНЕНО (2026-10, жалоба пользователя: "имя не сохраняется, я
            # несколько раз переименовал его в Voice Vocal Club"): эта команда
            # выполняется при каждом запуске сервера и раньше каждый раз
            # затирала название клуба тем, что указано в команде запуска.
            # Теперь у уже существующего клуба название не трогаем — оно
            # меняется только из Admin App.
            club.is_active = True
        else:
            club = Club(club_id=args.club_id, name=args.name, is_active=True)
            db.session.add(club)
        db.session.commit()
        final_name = club.name
    print(f"OK: клуб {args.club_id} ({final_name})")


def cmd_add_kj(args):
    app = create_app()
    with app.app_context():
        kj = KJOperator.query.filter_by(telegram_user_id=args.telegram_id).first()
        if kj:
            kj.club_id = args.club_id
            kj.display_name = args.name
            kj.is_active = True
        else:
            kj = KJOperator(
                telegram_user_id=args.telegram_id,
                club_id=args.club_id,
                display_name=args.name,
                is_active=True,
            )
            db.session.add(kj)
        db.session.commit()
    print(f"OK: KJ {args.telegram_id} привязан к клубу {args.club_id}")


def cmd_kj_link(args):
    app = create_app()
    with app.app_context():
        token = issue_kj_token(
            args.telegram_id, app.config["KJ_JWT_SECRET"], app.config["KJ_JWT_TTL_SECONDS"]
        )
    print(f"{args.panel_url}?token={token}")


def cmd_add_admin(args):
    app = create_app()
    with app.app_context():
        admin = AdminUser.query.filter_by(telegram_user_id=args.telegram_id).first()
        if admin:
            admin.club_id = args.club_id
            admin.display_name = args.name
            admin.is_super_admin = args.super_admin
            admin.is_active = True
        else:
            admin = AdminUser(
                telegram_user_id=args.telegram_id,
                club_id=args.club_id,
                display_name=args.name,
                is_super_admin=args.super_admin,
                is_active=True,
            )
            db.session.add(admin)
        db.session.commit()
    print(f"OK: администратор {args.telegram_id} привязан к клубу {args.club_id}"
          f"{' (супер-админ)' if args.super_admin else ''}")


def cmd_admin_link(args):
    app = create_app()
    with app.app_context():
        token = issue_admin_token(
            args.telegram_id, app.config["ADMIN_JWT_SECRET"], app.config["ADMIN_JWT_TTL_SECONDS"]
        )
    print(f"{args.panel_url}?token={token}")


def cmd_set_admin_google_email(args):
    """
    Привязывает Google-почту к уже существующему администратору (запрос
    пользователя 2026-09: "нормальный вход через Google в админку" — по
    образцу google_email у KJ, см. docstring AdminUser в models.py). В
    отличие от KJ, для админов пока нет экрана управления в самом Admin
    App — единственный способ вписать первую разрешённую почту (в первую
    очередь себе) — эта команда. google_sub НЕ трогаем: если почта
    меняется на другую, старая Google-привязка (google_sub) сбрасывается,
    чтобы вход снова потребовал подтверждения новой почтой.
    """
    app = create_app()
    with app.app_context():
        admin = AdminUser.query.filter_by(telegram_user_id=args.telegram_id).first()
        if admin is None:
            print(f"ОШИБКА: администратор {args.telegram_id} не найден — сначала добавь его через add-admin")
            return
        new_email = args.google_email.strip().lower()
        if admin.google_email != new_email:
            admin.google_sub = None
        admin.google_email = new_email
        db.session.commit()
    print(f"OK: почта {new_email} привязана к администратору {args.telegram_id} — можно входить в Admin App через Google")


def cmd_reset_table_group(args):
    """
    Разовая ручная починка "зависшего" группового стола (см. модель
    TableGroup) — первый гость, который когда-либо ввёл этот номер стола,
    становится его "админом" навсегда; если тот админ — старая/потерянная
    тестовая сессия (например, сессия автотеста), все следующие гости на
    этом же столе застревают в статусе "pending" (ждут одобрения), а
    одобрить их некому, потому что того самого админа больше нет за
    компьютером. Команда убирает старые group/members/join-requests для
    club_id+table_no и сразу делает указанного guest_id новым админом —
    гость получает доступ к форме заказа сразу же, без лишнего клика
    "Запросить присоединение" на экране "Групповой стол".
    """
    print(
        f"START: reset-table-group club_id={args.club_id} table_no={args.table_no} "
        f"guest_id={args.guest_id}",
        flush=True,
    )
    try:
        app = create_app()
        with app.app_context():
            from models import TableGroup, TableGroupMember, TableJoinRequest

            TableJoinRequest.query.filter_by(club_id=args.club_id, table_no=args.table_no).delete()
            TableGroupMember.query.filter_by(club_id=args.club_id, table_no=args.table_no).delete()
            TableGroup.query.filter_by(club_id=args.club_id, table_no=args.table_no).delete()
            db.session.flush()

            group = TableGroup(club_id=args.club_id, table_no=args.table_no, admin_guest_id=args.guest_id)
            db.session.add(group)
            db.session.flush()
            db.session.add(TableGroupMember(club_id=args.club_id, table_no=args.table_no, guest_id=args.guest_id))
            db.session.commit()
    except Exception:
        import traceback

        traceback.print_exc()
        raise
    print(
        f"OK: групповой стол {args.table_no} клуба {args.club_id} сброшен, "
        f"новый админ — гость {args.guest_id}",
        flush=True,
    )


def cmd_guest_link(args):
    """
    Печатает JWT гостя (аналог kj-link/admin-link) для указанных
    club_id/table_no/guest_id — нужен только для ручной диагностики через
    curl/браузер (сравнить показания /api/guest/me и /api/guest/table-group
    с тем, что видно в самом Guest App), приложение сам этот путь никогда
    не использует.
    """
    app = create_app()
    with app.app_context():
        token = issue_guest_token(
            args.guest_id, args.club_id, args.table_no,
            app.config["GUEST_JWT_SECRET"], app.config["GUEST_JWT_TTL_SECONDS"],
        )
    print(f"GUEST_TOKEN: {token}", flush=True)


def cmd_set_bridge_token(args):
    """
    Генерирует (или показывает существующий) секрет для локального моста
    VirtualDJ этого клуба (см. sockets.py::handle_bridge_connect,
    vdj/bridge_client.py). Значение нужно прописать в конфиг
    vdj_bridge/agent.py на компьютере KJ — оно не для людей, не показывается
    больше нигде и не логируется.
    """
    app = create_app()
    with app.app_context():
        club = db.session.get(Club, args.club_id)
        if club is None:
            print(f"ОШИБКА: клуб {args.club_id} не найден — сначала добавь его через add-club")
            return
        if club.bridge_token and not args.regenerate:
            print(f"У клуба {args.club_id} уже есть bridge_token (используй --regenerate, чтобы заменить):")
            print(club.bridge_token)
            return
        club.bridge_token = secrets.token_urlsafe(32)
        db.session.commit()
        token_value = club.bridge_token
    print(f"OK: bridge_token для клуба {args.club_id} (сохрани — больше не показывается автоматически):")
    print(token_value)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(required=True)

    sub.add_parser("init-db").set_defaults(func=cmd_init_db)

    p = sub.add_parser("add-club")
    p.add_argument("--club-id", type=int, required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_add_club)

    p = sub.add_parser("add-kj")
    p.add_argument("--telegram-id", type=int, required=True)
    p.add_argument("--club-id", type=int, required=True)
    p.add_argument("--name", default=None)
    p.set_defaults(func=cmd_add_kj)

    p = sub.add_parser("kj-link")
    p.add_argument("--telegram-id", type=int, required=True)
    p.add_argument("--panel-url", default="http://localhost:3000")
    p.set_defaults(func=cmd_kj_link)

    p = sub.add_parser("add-admin")
    p.add_argument("--telegram-id", type=int, required=True)
    p.add_argument("--club-id", type=int, required=True)
    p.add_argument("--name", default=None)
    p.add_argument("--super-admin", action="store_true", help="выдать права супер-админа")
    p.set_defaults(func=cmd_add_admin)

    p = sub.add_parser("admin-link")
    p.add_argument("--telegram-id", type=int, required=True)
    p.add_argument("--panel-url", default="http://localhost:3001")
    p.set_defaults(func=cmd_admin_link)

    p = sub.add_parser("set-admin-google-email")
    p.add_argument("--telegram-id", type=int, required=True)
    p.add_argument("--google-email", required=True)
    p.set_defaults(func=cmd_set_admin_google_email)

    p = sub.add_parser("reset-table-group")
    p.add_argument("--club-id", type=int, required=True)
    p.add_argument("--table-no", type=int, required=True)
    p.add_argument("--guest-id", type=int, required=True)
    p.set_defaults(func=cmd_reset_table_group)

    p = sub.add_parser("guest-link")
    p.add_argument("--club-id", type=int, required=True)
    p.add_argument("--table-no", type=int, required=True)
    p.add_argument("--guest-id", type=int, required=True)
    p.set_defaults(func=cmd_guest_link)

    p = sub.add_parser("set-bridge-token")
    p.add_argument("--club-id", type=int, required=True)
    p.add_argument("--regenerate", action="store_true", help="заменить уже существующий токен")
    p.set_defaults(func=cmd_set_bridge_token)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
