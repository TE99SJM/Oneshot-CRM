"""Shared FastAPI dependencies and helpers."""
from typing import TypeVar

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import User
from .security import decode_token

bearer = HTTPBearer(auto_error=False)
T = TypeVar("T", bound=Base)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                                 headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    user_id = decode_token(creds.credentials)
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise unauthorized
    return user


def get_or_404(db: Session, model: type[T], obj_id: int | None, label: str | None = None) -> T:
    obj = db.get(model, obj_id) if obj_id is not None else None
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label or model.__name__} not found")
    return obj


def ensure_exists(db: Session, model: type[T], obj_id: int | None, label: str) -> None:
    """Validate an optional foreign key: None is allowed, unknown ids are a 422."""
    if obj_id is not None and db.get(model, obj_id) is None:
        raise HTTPException(422, f"{label} {obj_id} does not exist")
