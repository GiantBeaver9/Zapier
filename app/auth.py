"""Authentication: ``Authorization: Bearer <api_key>`` -> ``Customer`` (D10).

The API key *is* the credential. The server derives ``customer_id`` from it via
an indexed lookup; any ``customer_id`` in the request body/query is ignored, so
there is no tenant id to spoof and cross-tenant reads are structurally
impossible.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import Customer
from .store import EventStore

# auto_error=False so we return a JSON 401 (with WWW-Authenticate) ourselves
# rather than FastAPI's terse default when the header is missing.
_bearer = HTTPBearer(auto_error=False)


def get_store(request: Request) -> EventStore:
    return request.app.state.store


def require_customer(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    store: EventStore = Depends(get_store),
) -> Customer:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    customer = store.get_customer_by_api_key(credentials.credentials)
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return customer
