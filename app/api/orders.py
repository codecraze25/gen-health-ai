import hashlib
import logging
import uuid
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, Extractor, limit_upload
from app.core.config import get_settings
from app.extraction.pdf import PdfError
from app.extraction.service import extract_order
from app.models import Order, OrderStatus
from app.schemas.order import OrderCreate, OrderList, OrderOut, OrderUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["orders"])


def get_owned_order(db: DbSession, user: CurrentUser, order_id: uuid.UUID) -> Order:
    order = db.scalar(select(Order).where(Order.id == order_id, Order.owner_id == user.id))
    if order is None:
        # 404 rather than 403 so other users' order IDs are not disclosed.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(body: OrderCreate, db: DbSession, user: CurrentUser) -> Order:
    order = Order(owner_id=user.id, validation_issues=[], **body.model_dump())
    order.refresh_status()
    db.add(order)
    db.commit()
    return order


@router.post(
    "/upload",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_upload)],
    responses={
        413: {"description": "File too large"},
        429: {"description": "Upload rate limit exceeded"},
        415: {"description": "Not a PDF"},
        422: {"description": "PDF is corrupt, encrypted, or blank"},
    },
)
def upload_order_document(
    db: DbSession,
    user: CurrentUser,
    extractor: Extractor,
    file: Annotated[UploadFile, File(description="Order PDF (scanned or digital)")],
) -> Order:
    """Create an order from a PDF.

    Extracts the patient's first/last name and date of birth and the ordering provider's name and
    NPI. Values that are missing or fail validation are left null and explained in
    `validation_issues`; the order stays `needs_review` until a user fixes them with PATCH.
    """
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"File exceeds {get_settings().max_upload_mb} MB",
        )
    if not data.lstrip()[:5].startswith(b"%PDF"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "File is not a PDF")

    try:
        outcome = extract_order(data, extractor)
    except PdfError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    filename = PurePath(file.filename or "upload.pdf").name[:255]
    order = Order(
        owner_id=user.id,
        **outcome.fields,
        validation_issues=outcome.issues,
        extraction=outcome.metadata,
        source_filename=filename,
        source_sha256=hashlib.sha256(data).hexdigest(),
    )
    order.refresh_status()
    db.add(order)
    db.commit()
    logger.info(
        "order created from upload",
        extra={
            "extra_fields": {
                "order_id": str(order.id),
                "status": order.status,
                "issue_codes": sorted({i["code"] for i in outcome.issues}),
                "pages": outcome.metadata.get("page_count"),
                "duration_ms": outcome.metadata.get("duration_ms"),
            }
        },
    )
    return order


@router.get("", response_model=OrderList)
def list_orders(
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
) -> OrderList:
    query = select(Order).where(Order.owner_id == user.id)
    if status_filter is not None:
        query = query.where(Order.status == status_filter.value)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(Order.created_at.desc(), Order.id).limit(limit).offset(offset)
    ).all()
    return OrderList(
        items=[OrderOut.model_validate(o) for o in items], total=total, limit=limit, offset=offset
    )


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Order:
    return get_owned_order(db, user, order_id)


@router.patch("/{order_id}", response_model=OrderOut)
def update_order(order_id: uuid.UUID, body: OrderUpdate, db: DbSession, user: CurrentUser) -> Order:
    order = get_owned_order(db, user, order_id)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(order, field, value)
    # A user edit of a field is a human review of it, so its open issues are resolved.
    issues = [i for i in order.validation_issues if i["field"] not in changes]
    if order.is_complete:
        # Document-level issues (failed extraction, multiple patients) are settled once a user
        # has supplied every required field themselves.
        issues = [i for i in issues if i["field"] != "document"]
    order.validation_issues = issues
    order.refresh_status()
    db.commit()
    return order


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Response:
    order = get_owned_order(db, user, order_id)
    db.delete(order)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
