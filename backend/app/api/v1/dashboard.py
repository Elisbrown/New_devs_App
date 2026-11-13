from decimal import Decimal
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.cache import get_revenue_summary
from app.core.auth import authenticate_request as get_current_user

router = APIRouter()


@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str,
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:

    # FIX: never fall back to a shared "default_tenant". A user without a tenant
    # must be rejected, not served data from a bucket shared with others.
    tenant_id = getattr(current_user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant associated with this user")

    try:
        revenue_data = await get_revenue_summary(property_id, tenant_id, month, year)
    except Exception as e:
        raise HTTPException(status_code=503, detail="Revenue data is temporarily unavailable") from e

    # FIX: total is already rounded to cents as a Decimal string by the service;
    # convert once for JSON instead of passing a 3-decimal float to the browser.
    total = Decimal(revenue_data["total"])

    response = {
        "property_id": revenue_data["property_id"],
        "total_revenue": float(total),
        "currency": revenue_data["currency"],
        "reservations_count": revenue_data["count"],
    }
    if "period" in revenue_data:
        response["period"] = revenue_data["period"]
    return response
