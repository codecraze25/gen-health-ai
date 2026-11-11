import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.models import Order, OrderStatus
from app.schemas.order import OrderCreate, OrderList, OrderOut, OrderUpdate

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
    order.validation_issues = [i for i in order.validation_issues if i["field"] not in changes]
    order.refresh_status()
    db.commit()
    return order


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Response:
    order = get_owned_order(db, user, order_id)
    db.delete(order)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
