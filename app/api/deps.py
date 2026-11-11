from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.rate_limit import login_limiter, register_limiter, upload_limiter
from app.core.security import decode_access_token
from app.db.session import get_db
from app.extraction.llm import ExtractionLLM, OpenAIExtractor
from app.models import User

DbSession = Annotated[Session, Depends(get_db)]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(db: DbSession, token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user_id = decode_access_token(token)
    if user_id is None:
        raise unauthorized
    user = db.get(User, user_id)
    if user is None:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def _client_ip(request: Request) -> str:
    # Uvicorn runs with --proxy-headers, so this is the real client behind Render's proxy.
    return request.client.host if request.client else "unknown"


def limit_register(request: Request) -> None:
    register_limiter.hit(_client_ip(request))


def limit_login(request: Request) -> None:
    login_limiter.hit(_client_ip(request))


def limit_upload(user: CurrentUser) -> None:
    upload_limiter.hit(str(user.id))


@lru_cache
def _openai_extractor() -> OpenAIExtractor:
    return OpenAIExtractor()


def get_extractor() -> ExtractionLLM:
    try:
        return _openai_extractor()
    except RuntimeError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Document extraction is not configured"
        ) from exc


Extractor = Annotated[ExtractionLLM, Depends(get_extractor)]
