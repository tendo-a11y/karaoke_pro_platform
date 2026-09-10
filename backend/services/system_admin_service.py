"""
Сервис для Admin App — блок "Системные функции" (Block #4, аудит
handlers/admin.py: show_system_menu/system_support/system_logs/
system_backup/system_restart).

Согласовано перед реализацией (см. историю переписки):
- Доступ только super_admin — это общесистемная информация по всей БД
  (все клубы), а не по одному клубу, как и "Отчёты" (Block #3).
- "Всего пользователей" (старое SELECT COUNT(*) FROM users) заменено на
  "Заказов всего" (COUNT(*) по Order) — явно НЕ интерпретируем
  telegram_user_id/guest_id как "пользователей", т.к. в новой архитектуре
  нет отдельной сущности Guest, и придумывать такую интерпретацию только
  ради счётчика значило бы вводить новую бизнес-логику.
- system_support (memory/CPU процесса бота) не переносится вовсе — при
  gunicorn с несколькими воркерами "процесс бота" не имеет единственного
  смысла. Единственное, что из него выжило по прямому указанию, —
  размер БД, перенесённый сюда, в overview, через pg_database_size.
- system_restart не переносится — в оригинале кнопка не делала ничего
  программно (только текст "перезапустите бота вручную в терминале"),
  переносить там нечего.
- system_logs — последние 20 Transaction, поля 1:1 из старого текста
  (type/amount/description/created_at), без добавления club_name (в
  оригинале бот был однотенантным и такого поля не было — не выдумываем).
- Backup — pg_dump, Plain SQL (-F p), --no-owner --no-privileges,
  потоковая отдача клиенту без временного файла на диске (в отличие от
  старого shutil.copy2 + отправка файла + os.remove — здесь temp-файл
  просто не нужен, т.к. HTTP-ответ можно стримить прямо из stdout pg_dump).
"""
import subprocess
from datetime import datetime, timezone

from sqlalchemy import text

from extensions import db
from models import Club, KJOperator, Order, Transaction


class SystemAdminServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _require_super_admin(admin):
    if not admin.is_super_admin:
        raise SystemAdminServiceError(
            "FORBIDDEN", "Системная информация доступна только супер-админу", 403
        )


def get_overview(admin) -> dict:
    _require_super_admin(admin)

    db_size_bytes = db.session.execute(
        text("SELECT pg_database_size(current_database())")
    ).scalar()

    return {
        "clubs_count": Club.query.count(),
        "kj_count": KJOperator.query.count(),
        "kj_active_count": KJOperator.query.filter(KJOperator.is_active.is_(True)).count(),
        "orders_count": Order.query.count(),
        "db_size_mb": round(db_size_bytes / 1024 / 1024, 2),
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


def get_recent_transactions(admin, limit: int = 20) -> list:
    _require_super_admin(admin)

    rows = (
        Transaction.query.order_by(Transaction.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "type": tx.type,
            "amount": float(tx.amount),
            "description": tx.description,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
        }
        for tx in rows
    ]


def build_backup_command(database_uri: str) -> list:
    """
    Отдельная функция ради тестируемости самой команды без реального
    вызова pg_dump. database_uri — SQLALCHEMY_DATABASE_URI из конфига
    (driver-префикс "+psycopg2" не понимает libpq/pg_dump — убираем его,
    сам pg_dump принимает обычный postgresql:// URI через --dbname).
    """
    libpq_uri = database_uri.replace("postgresql+psycopg2://", "postgresql://")
    return ["pg_dump", "--no-owner", "--no-privileges", "-F", "p", "--dbname", libpq_uri]


def backup_filename() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"backup_{timestamp}.sql"


def stream_backup(admin, database_uri: str):
    """
    Возвращает (generator по чанкам stdout, Popen-процесс) — без
    временного файла: chunks читаются прямо из pipe pg_dump и уходят в
    HTTP-ответ. Вызывающий код (route) должен убедиться, что процесс
    завершился с returncode == 0 после исчерпания générator'а (см.
    routes/admin.py::system_backup).
    """
    _require_super_admin(admin)

    proc = subprocess.Popen(
        build_backup_command(database_uri),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def generate():
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.stdout.close()
            proc.wait()

    return generate(), proc
