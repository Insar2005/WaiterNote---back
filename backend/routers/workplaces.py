# backend/routers/workplaces.py
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, func, update as sql_update

from models import Workplace, WorkplaceMember, WorkplaceRole
from deps import SessionDep, CurrentUser, WorkplaceDep, WorkplaceOwnerDep
from schemas.workplace import WorkplaceCreate, WorkplaceUpdate, WorkplaceOut
from schemas.common import IDOut, ReorderRequest

router = APIRouter(prefix="/workplaces", tags=["workplaces"])


def _to_out(w: Workplace, role: str) -> WorkplaceOut:
    return WorkplaceOut(
        id=w.id,
        owner_id=w.owner_id,
        title=w.title,
        timezone=w.timezone,
        currency=w.currency,
        service_percent_default=w.service_percent_default,
        shift_type_default=w.shift_type_default,
        pay_for_shift_default=w.pay_for_shift_default,
        position=w.position,
        is_archived=w.is_archived,
        created_at=w.created_at,
        updated_at=w.updated_at,
        my_role=role,
    )


@router.get("", response_model=list[WorkplaceOut])
async def list_workplaces(
    user: CurrentUser,
    session: SessionDep,
    include_archived: bool = False,
):
    """List all workplaces the current user has access to (own + shared)."""
    stmt = (
        select(Workplace, WorkplaceMember.role)
        .join(WorkplaceMember, WorkplaceMember.workplace_id == Workplace.id)
        .where(WorkplaceMember.user_id == user.id)
        .order_by(Workplace.position)
    )
    if not include_archived:
        stmt = stmt.where(Workplace.is_archived.is_(False))

    result = await session.execute(stmt)
    return [_to_out(w, role) for w, role in result.all()]


@router.post("", response_model=WorkplaceOut, status_code=status.HTTP_201_CREATED)
async def create_workplace(
    body: WorkplaceCreate,
    user: CurrentUser,
    session: SessionDep,
):
    """Create a new workplace. Caller becomes owner + member with role='owner'."""
    # ID conflict check (FK + PK will raise too, but cleaner error here)
    existing = await session.get(Workplace, body.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="workplace with this id already exists",
        )

    # Compute next position for this owner
    max_pos = await session.scalar(
        select(func.coalesce(func.max(Workplace.position), -1))
        .where(Workplace.owner_id == user.id)
    )

    workplace = Workplace(
        id=body.id,
        owner_id=user.id,
        title=body.title,
        timezone=body.timezone,
        currency=body.currency,
        service_percent_default=body.service_percent_default,
        shift_type_default=body.shift_type_default,
        pay_for_shift_default=body.pay_for_shift_default,
        position=max_pos + 1,
    )
    session.add(workplace)
    await session.flush()

    # Owner is also a member with role='owner' — единый запрос на доступ
    from utils.ids import is_valid_id  # noqa
    # Generate membership id on server (not user-facing entity)
    import secrets, string
    alphabet = string.ascii_letters + string.digits + "_-"
    membership_id = "".join(secrets.choice(alphabet) for _ in range(21))

    membership = WorkplaceMember(
        id=membership_id,
        workplace_id=workplace.id,
        user_id=user.id,
        role=WorkplaceRole.owner.value,
    )
    session.add(membership)

    # Update user.last_workplace_id — automatically switch to new workplace
    user.last_workplace_id = workplace.id

    await session.commit()
    await session.refresh(workplace)

    return _to_out(workplace, WorkplaceRole.owner.value)


@router.get("/{workplace_id}", response_model=WorkplaceOut)
async def get_workplace(
    workplace: WorkplaceDep,
    user: CurrentUser,
    session: SessionDep,
):
    role = await session.scalar(
        select(WorkplaceMember.role).where(
            WorkplaceMember.workplace_id == workplace.id,
            WorkplaceMember.user_id == user.id,
        )
    )
    return _to_out(workplace, role or "member")


@router.patch("/{workplace_id}", response_model=WorkplaceOut)
async def update_workplace(
    body: WorkplaceUpdate,
    workplace: WorkplaceDep,
    user: CurrentUser,
    session: SessionDep,
):
    """Any member can edit metadata. (If you want owner-only — swap to WorkplaceOwnerDep.)"""
    patch = body.model_dump(exclude_unset=True)
    for k, v in patch.items():
        setattr(workplace, k, v)

    await session.commit()
    await session.refresh(workplace)

    role = await session.scalar(
        select(WorkplaceMember.role).where(
            WorkplaceMember.workplace_id == workplace.id,
            WorkplaceMember.user_id == user.id,
        )
    )
    return _to_out(workplace, role or "member")


@router.post("/{workplace_id}/archive", response_model=WorkplaceOut)
async def archive_workplace(
    workplace: WorkplaceOwnerDep,
    session: SessionDep,
):
    workplace.is_archived = True
    await session.commit()
    await session.refresh(workplace)
    return _to_out(workplace, WorkplaceRole.owner.value)


@router.post("/{workplace_id}/unarchive", response_model=WorkplaceOut)
async def unarchive_workplace(
    workplace: WorkplaceOwnerDep,
    session: SessionDep,
):
    workplace.is_archived = False
    await session.commit()
    await session.refresh(workplace)
    return _to_out(workplace, WorkplaceRole.owner.value)


@router.delete("/{workplace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workplace(
    workplace: WorkplaceOwnerDep,
    session: SessionDep,
):
    """Hard delete. Cascades to halls, menu, shifts, orders, notes (per FK)."""
    await session.delete(workplace)
    await session.commit()


@router.post("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_workplaces(
    body: ReorderRequest,
    user: CurrentUser,
    session: SessionDep,
):
    """Reorder owned workplaces. IDs not owned by the user are silently skipped."""
    # Fetch only owned workplaces
    result = await session.execute(
        select(Workplace.id).where(
            Workplace.owner_id == user.id,
            Workplace.id.in_(body.ids),
        )
    )
    owned_ids = {r[0] for r in result.all()}

    for position, wp_id in enumerate(body.ids):
        if wp_id in owned_ids:
            await session.execute(
                sql_update(Workplace)
                .where(Workplace.id == wp_id)
                .values(position=position)
            )
    await session.commit()


# ===== Switch current workplace (lightweight) =====

@router.post("/{workplace_id}/select", status_code=status.HTTP_204_NO_CONTENT)
async def select_workplace(
    workplace: WorkplaceDep,
    user: CurrentUser,
    session: SessionDep,
):
    """Set as user's last_workplace_id (used by client on app start)."""
    user.last_workplace_id = workplace.id
    await session.commit()