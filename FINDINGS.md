# Findings and fixes

## 1. Revenue from another company shown on refresh (Client B, privacy)

**How I found it:** logged in as Sunset, opened `prop-001`, then logged in as Ocean and opened `prop-001`. Ocean saw Sunset's figures (1,000.00, 3 bookings), although Ocean has no reservations on its `prop-001`.

**Root causes**
- `services/cache.py` cached revenue under `revenue:{property_id}`. Property IDs are only unique per tenant (`properties` has a composite key `(id, tenant_id)` and `prop-001` exists for both tenants), so whichever tenant loaded first filled the cache for both for 5 minutes.
- `services/reservations.py` fell back to hard-coded mock figures keyed only by `property_id` whenever the database failed, which was on every request (see 2), so every tenant got the same numbers for the same property ID.
- `api/v1/dashboard.py` fell back to a shared `"default_tenant"` when a user had no tenant.

**Fixes**
- Cache key is now `revenue:{tenant_id}:{property_id}:{period}`.
- Removed the tenant-blind mock fallback; a DB failure now returns `503` instead of fake data.
- A user without a tenant gets `403` instead of a shared default tenant.

## 2. Revenue totals for March don't match the client's records (Client A)

**Root causes**
- `core/database_pool.py` built its URL from `settings.supabase_db_*` fields that do not exist on `Settings`, so pool initialisation always failed and every dashboard figure was mock data. It also used `QueuePool`, which is invalid for an async engine, and `get_session` was declared `async` but used with `async with`.
- `requirements.txt` had `sqlalchemy>=2.0.0`, which now installs SQLAlchemy 2.1, where `greenlet` (required for asyncio) is no longer pulled in automatically.
- Month boundaries were computed in naive UTC. Reservation `res-tz-1` checks in at `2024-02-29 23:30 UTC`, which is `2024-03-01 00:30` in Paris, so for the Paris property it belongs to March. The monthly function also just returned a placeholder `0`.

**Fixes**
- The pool now uses `settings.database_url` with the `asyncpg` driver and the default async pool, and is initialised once and reused.
- `sqlalchemy[asyncio]>=2.0.0` in requirements.
- `calculate_monthly_revenue` converts `check_in_date` to the property's own `timezone` before comparing it with the month boundaries. The summary endpoint accepts optional `month` and `year`.

**Result:** Sunset `prop-001` all-time total is now 2,250.00 from 4 bookings (was mock 1,000.00 / 3). For March 2024 it is 2,250.00 including `res-tz-1`; with UTC boundaries it would have been 1,000.00.

## 3. Totals off by a few cents (finance)

**Root cause:** amounts are stored as `NUMERIC(10,3)` (sub-cent), converted to a Python `float` in the API, sent to the browser with 3 decimals and rounded there with `Math.round(x * 100) / 100`. Binary floating point rounds values such as `x.xx5` the wrong way.

**Fix:** amounts stay `Decimal` end to end and are rounded once on the server to cents with `ROUND_HALF_UP` (`to_money` in `services/reservations.py`). The API returns totals already rounded to 2 decimals.

## How to verify

```bash
docker-compose up --build
# Log in as sunset@propertyflow.com and ocean@propertyflow.com and open prop-001 in each:
#   Sunset: 2,250.00 (4 bookings)   Ocean: 0.00 (0 bookings)
# Monthly: GET /api/v1/dashboard/summary?property_id=prop-001&month=3&year=2024
```

## Also noticed (not changed)

- The dashboard property dropdown is hard-coded and shows all five properties to both tenants. With the fixes above the API only returns a tenant's own data, but the list should come from the tenant's properties.
- The frontend sends an `X-Simulated-Tenant` header that the backend ignores; it should be removed so it can never be trusted by mistake.
