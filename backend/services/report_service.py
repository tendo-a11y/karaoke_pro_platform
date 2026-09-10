"""
Сервис для Admin App — блок "Отчёты" (аудит handlers/admin.py:
show_reports_menu/report_today/report_week/report_month/report_venues/
report_cashback/report_export/export_csv/export_excel). План согласован
перед реализацией: доступ только super_admin (у обычного админа вся эта
детализация уже есть в карточке его единственного клуба, см.
club_service.get_club_detail — отдельный экран был бы чистым дублированием).

Переиспользует club_service._revenue_since — тот же скользящий расчёт
"выручки" (сумма Transaction.type=order_payment за окно), чтобы не
заводить второе определение выручки в проекте.

ВАЖНЫЙ баг старого бота, который сознательно НЕ переносится: report_today
(handlers/admin.py:908-941) считал процент клуба от НАКАПЛИВАЕМОЙ внутри
того же цикла суммы (total_revenue ещё не финальная на момент деления), а
не от полного итога по всем клубам — доля первого клуба в списке всегда
получалась 100%. Здесь процент считается от already-computed totals после
прохода по всем клубам.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from extensions import db
from models import Club, Order, STATUS_COMPLETED
from services.club_service import _revenue_since


class ReportServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _orders_completed_since(club_id: int, since: datetime) -> int:
    return Order.query.filter(
        Order.club_id == club_id,
        Order.status == STATUS_COMPLETED,
        Order.completed_at >= since,
    ).count()


def get_overview(admin) -> dict:
    if not admin.is_super_admin:
        raise ReportServiceError("FORBIDDEN", "Отчёты по всем клубам доступны только супер-админу", 403)

    now = datetime.now(timezone.utc)
    since_today = now - timedelta(days=1)
    since_week = now - timedelta(days=7)
    since_month = now - timedelta(days=30)

    clubs = Club.query.all()
    rows = []
    for club in clubs:
        rows.append({
            "club_id": club.club_id,
            "name": club.name,
            "city": club.city,
            "is_active": club.is_active,
            "revenue_today": _revenue_since(club.club_id, since_today),
            "revenue_week": _revenue_since(club.club_id, since_week),
            "revenue_month": _revenue_since(club.club_id, since_month),
            "orders_completed_today": _orders_completed_since(club.club_id, since_today),
        })

    rows.sort(key=lambda r: r["revenue_month"], reverse=True)

    total_today = sum((r["revenue_today"] for r in rows), Decimal("0"))
    total_week = sum((r["revenue_week"] for r in rows), Decimal("0"))
    total_month = sum((r["revenue_month"] for r in rows), Decimal("0"))
    total_orders_today = sum(r["orders_completed_today"] for r in rows)

    commission = admin_commission_rate()
    for row in rows:
        # Процент считается от ПОЛНОГО итога total_today (уже посчитан выше по
        # всем клубам), а не от промежуточной суммы внутри цикла — см. docstring
        # модуля про баг старого бота, который здесь не воспроизводится.
        row["percent_of_total_today"] = (
            float(row["revenue_today"] / total_today * 100) if total_today > 0 else 0.0
        )
        row["revenue_today"] = float(row["revenue_today"])
        row["revenue_week"] = float(row["revenue_week"])
        row["revenue_month"] = float(row["revenue_month"])

    return {
        "clubs": rows,
        "totals": {
            "revenue_today": float(total_today),
            "revenue_week": float(total_week),
            "revenue_month": float(total_month),
            "orders_completed_today": total_orders_today,
            "admin_commission_today": float((total_today * commission).quantize(Decimal("0.01"))),
            "admin_commission_week": float((total_week * commission).quantize(Decimal("0.01"))),
            "admin_commission_month": float((total_month * commission).quantize(Decimal("0.01"))),
        },
    }


def admin_commission_rate() -> Decimal:
    from flask import current_app
    return Decimal(str(current_app.config["ADMIN_COMMISSION"]))
