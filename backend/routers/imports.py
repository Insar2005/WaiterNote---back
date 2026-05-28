"""
Import / share routes.

Two halves:
  * Owner-side (under /workplaces/{id}/import-shares): the workplace
    owner publishes a time-limited share and manages it.
  * Importer-side (under /import/{code}): anyone with the code reads
    a preview and optionally copies into their own workplace.

Auth model:
  * Creating / listing / revoking shares requires owner of the source
    workplace.
  * Preview only needs an authenticated user — knowledge of the code
    plus an active window is the access check.
  * Apply additionally requires the caller to have access to the
    target workplace (any role).
"""
from typing import Annotated

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select

from deps import (
    CurrentUser,
    SessionDep,
    WorkplaceOwnerDep,
)
from models import (
    Hall,
    ImportShare,
    MenuCategory,
    User,
    Workplace,
    WorkplaceMember,
)
from schemas.import_share import (
    ImportApplyRequest,
    ImportApplyResult,
    ImportPreviewOut,
    ImportShareCreate,
    ImportShareOut,
)
from services import imports as import_service
from services.telegram_bot import send_message


# ============================================================
# Owner side — manage your own shares
# ============================================================

owner_router = APIRouter(
    prefix="/workplaces/{workplace_id}/import-shares",
    tags=["imports"],
)


def _to_out(share: ImportShare) -> ImportShareOut:
    """Serialize a share including the derived `is_active` flag."""
    return ImportShareOut(
        id=share.id,
        code=share.code,
        workplace_id=share.workplace_id,
        created_by_user_id=share.created_by_user_id,
        created_at=share.created_at,
        expires_at=share.expires_at,
        revoked_at=share.revoked_at,
        import_count=share.import_count,
        is_active=import_service.share_is_active(share),
    )


@owner_router.post(
    "",
    response_model=ImportShareOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_import_share(
    body: ImportShareCreate,
    workplace: WorkplaceOwnerDep,
    user: CurrentUser,
    session: SessionDep,
):
    """Publish a new time-limited share. Owner-only by design — opening
    your menu and floor plan to the world should require explicit
    consent from the person who owns the data."""
    share = await import_service.create_share(
        session,
        workplace=workplace,
        user_id=user.id,
        ttl_hours=body.ttl_hours,
    )
    await session.commit()
    await session.refresh(share)
    return _to_out(share)


@owner_router.get("", response_model=list[ImportShareOut])
async def list_import_shares(
    workplace: WorkplaceOwnerDep,
    session: SessionDep,
):
    """List this workplace's shares (active + expired + revoked).
    Sorted newest first."""
    shares = await import_service.list_shares_for_workplace(session, workplace.id)
    return [_to_out(s) for s in shares]


# ============================================================
# Importer side
# ============================================================

import_router = APIRouter(prefix="/import", tags=["imports"])


async def _resolve_active_share(
    code: Annotated[str, Path()],
    session: SessionDep,
) -> ImportShare:
    """Path dependency: 404 if the code is wrong, revoked, or expired.
    We deliberately don't distinguish those cases in the error so a
    leaked code doesn't reveal whether it ever existed."""
    share = await import_service.get_active_share_by_code(session, code)
    if share is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="share not found or no longer active",
        )
    return share


ActiveShareDep = Annotated[ImportShare, Depends(_resolve_active_share)]


@import_router.get("/{code}/preview", response_model=ImportPreviewOut)
async def preview_import(
    share: ActiveShareDep,
    user: CurrentUser,
    session: SessionDep,
):
    """Read-only listing of what this share contains. No side effects."""
    return await import_service.build_preview(session, share)


@import_router.post("/{code}/apply", response_model=ImportApplyResult)
async def apply_import(
    body: ImportApplyRequest,
    share: ActiveShareDep,
    user: CurrentUser,
    session: SessionDep,
):
    """Copy the chosen halls and categories from the share into the
    caller's target workplace.

    The target must be a workplace the caller has access to — we check
    via WorkplaceMember rather than reusing WorkplaceDep so we can take
    `target_workplace_id` from the body (path is the share code, not
    the target)."""
    target = await session.scalar(
        select(Workplace)
        .join(WorkplaceMember, WorkplaceMember.workplace_id == Workplace.id)
        .where(
            Workplace.id == body.target_workplace_id,
            WorkplaceMember.user_id == user.id,
        )
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="target workplace not found or access denied",
        )

    # Make sure each id the caller listed actually belongs to this share's
    # source. Without this check, a clever client could try to copy halls
    # or categories from a different workplace by sending their ids. The
    # service does its own WHERE on workplace_id when fetching, so a bogus
    # id would otherwise be silently dropped — we surface a 400 instead.
    if body.hall_ids:
        result = await session.execute(
            select(Hall.id).where(
                Hall.workplace_id == share.workplace_id,
                Hall.id.in_(body.hall_ids),
            )
        )
        valid_hall_ids = set(result.scalars().all())
        if len(valid_hall_ids) != len(set(body.hall_ids)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="one or more hall_ids are not part of this share",
            )

    if body.category_ids:
        result = await session.execute(
            select(MenuCategory.id).where(
                MenuCategory.workplace_id == share.workplace_id,
                MenuCategory.id.in_(body.category_ids),
            )
        )
        valid_category_ids = set(result.scalars().all())
        if len(valid_category_ids) != len(set(body.category_ids)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="one or more category_ids are not part of this share",
            )

    # Self-import guard: importing into the same workplace the share came
    # from would let the user wipe their own data without copying anything
    # in return (delete-then-copy from just-deleted rows). The mere "copy
    # to myself" (without replace flags) is a legal no-op, but combining
    # it with a replace flag is destructive nonsense — reject loudly.
    if target.id == share.workplace_id and (
        body.replace_halls or body.replace_categories
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "нельзя импортировать с заменой в то же заведение, "
                "из которого создана ссылка"
            ),
        )

    result = await import_service.apply_import(
        session,
        share=share,
        target_workplace=target,
        hall_ids=body.hall_ids,
        category_ids=body.category_ids,
        replace_halls=body.replace_halls,
        replace_categories=body.replace_categories,
    )
    await session.commit()

    # Notify the share's owner that someone just imported from them.
    # Best-effort and non-blocking: we fire and forget on the asyncio
    # event loop. If Telegram is down or the owner blocked the bot,
    # the import still succeeded — the notification is a courtesy,
    # not part of the contract.
    asyncio.create_task(
        _notify_owner_about_import(
            owner_user_id=share.created_by_user_id,
            source_workplace_id=share.workplace_id,
            importer_user=user,
            target_workplace_title=target.title,
            result=result,
        )
    )

    return result


async def _notify_owner_about_import(
    *,
    owner_user_id: int,
    source_workplace_id: str,
    importer_user: User,
    target_workplace_title: str,
    result: dict,
) -> None:
    """
    Send a Telegram notification to the share owner.

    Opens its OWN DB session — the request session is gone by the time
    this fires (we scheduled it via asyncio.create_task after commit).

    Bonus: this also gives us crash isolation: any DB hiccup here can't
    poison the original request's session.
    """
    from models import async_session  # local import avoids router import cycles
    try:
        async with async_session() as s:
            owner = await s.get(User, owner_user_id)
            source_wp = await s.get(Workplace, source_workplace_id)

        if owner is None or source_wp is None:
            return

        # Build a short, human summary. Omit zero rows; "0 шаблонов"
        # is just noise. Importer's @username if they have one, else
        # generic "кто-то".
        importer_name = (
            f"@{importer_user.username}"
            if importer_user.username
            else "Кто-то"
        )
        parts = []
        if result.get("halls_imported"):
            parts.append(f"{result['halls_imported']} залов")
        if result.get("categories_imported"):
            parts.append(f"{result['categories_imported']} категорий")
        if result.get("items_imported"):
            parts.append(f"{result['items_imported']} позиций")
        summary = ", ".join(parts) if parts else "содержимое"

        # Mention if the importer wiped their existing content first, so
        # the owner has a clearer mental picture of what happened on the
        # other side.
        replaced_note = ""
        if result.get("halls_replaced") or result.get("categories_replaced"):
            replaced_note = (
                "\n\n(Перед импортом было удалено старое содержимое.)"
            )

        text = (
            f"📥 Импорт из «{source_wp.title}»\n\n"
            f"{importer_name} только что скопировал {summary} "
            f"к себе в «{target_workplace_title}».{replaced_note}"
        )
        await send_message(owner.tg_id, text)
    except Exception:  # noqa: BLE001 — fire-and-forget; never crash the loop
        pass


# ============================================================
# Single-share owner ops (revoke)
# ============================================================

# Lives under /import-shares (no workplace in the URL) so the path stays
# short and the share's PK is the identifier. We still verify ownership.

share_router = APIRouter(prefix="/import-shares", tags=["imports"])


@share_router.delete("/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_import_share(
    share_id: str,
    user: CurrentUser,
    session: SessionDep,
):
    """Permanently kill a share before its TTL. Idempotent — calling on
    an already-revoked share is a no-op."""
    share = await session.get(ImportShare, share_id)
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "share not found")

    # Must own the workplace the share belongs to.
    workplace = await session.get(Workplace, share.workplace_id)
    if workplace is None or workplace.owner_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "only the workplace owner can revoke shares"
        )

    await import_service.revoke_share(session, share)
    await session.commit()