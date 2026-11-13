from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Optional

from sqlalchemy import text

from app.core.database_pool import db_pool

CENT = Decimal("0.01")


def to_money(value) -> Decimal:
    """
    Convert a DB NUMERIC value to a 2-decimal money amount.

    FIX: amounts are stored as NUMERIC(10,3) (sub-cent precision). They used to be
    passed around as floats and rounded in the browser, which produced totals a
    few cents off. We now keep Decimal end to end and round once, half-up, here.
    """
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


async def _session():
    # FIX: reuse the shared pool (it was re-created on every request) and make
    # sure it is initialised.
    await db_pool.initialize()
    if not db_pool.session_factory:
        raise RuntimeError("Database pool not available")
    return db_pool.get_session()


async def calculate_monthly_revenue(
    property_id: str, tenant_id: str, month: int, year: int
) -> Dict[str, Any]:
    """
    Calculates revenue for a calendar month in the PROPERTY's local time zone.

    FIX: the previous version built naive UTC month boundaries and returned a
    placeholder 0. A booking checking in at 2024-02-29 23:30 UTC is 1 March in
    Paris, so it belongs to March for a Paris property. We convert check-in to
    the property's time zone before comparing it with the month boundaries.
    """
    # Naive (local wall-clock) month boundaries, compared with check-in converted
    # to the property's local time below.
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)

    query = text("""
        SELECT
            COALESCE(SUM(r.total_amount), 0) AS total_revenue,
            COUNT(r.id) AS reservation_count,
            MIN(r.currency) AS currency
        FROM reservations r
        JOIN properties p
          ON p.id = r.property_id AND p.tenant_id = r.tenant_id
        WHERE r.property_id = :property_id
          AND r.tenant_id = :tenant_id
          AND (r.check_in_date AT TIME ZONE p.timezone) >= :start
          AND (r.check_in_date AT TIME ZONE p.timezone) <  :end
    """)

    async with await _session() as session:
        row = (await session.execute(query, {
            "property_id": property_id,
            "tenant_id": tenant_id,
            "start": start,
            "end": end,
        })).fetchone()

    return {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "total": str(to_money(row.total_revenue)),
        "currency": row.currency or "USD",
        "count": row.reservation_count,
        "period": f"{year:04d}-{month:02d}",
    }


async def calculate_total_revenue(
    property_id: str, tenant_id: str, month: Optional[int] = None, year: Optional[int] = None
) -> Dict[str, Any]:
    """
    Aggregates revenue from the database, always scoped to the tenant.
    """
    if month and year:
        return await calculate_monthly_revenue(property_id, tenant_id, month, year)

    query = text("""
        SELECT
            COALESCE(SUM(total_amount), 0) AS total_revenue,
            COUNT(*) AS reservation_count,
            MIN(currency) AS currency
        FROM reservations
        WHERE property_id = :property_id AND tenant_id = :tenant_id
    """)

    # FIX: no more silent fallback to hard-coded mock figures keyed only by
    # property_id. That fallback hid the broken DB connection and showed every
    # tenant the same "prop-001" numbers. Errors now surface to the caller.
    async with await _session() as session:
        row = (await session.execute(query, {
            "property_id": property_id,
            "tenant_id": tenant_id,
        })).fetchone()

    return {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "total": str(to_money(row.total_revenue)),
        "currency": row.currency or "USD",
        "count": row.reservation_count,
    }
