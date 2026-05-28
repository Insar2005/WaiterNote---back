"""
Import-share business logic.

Three concerns:
  1. Generating short, friendly, collision-free codes for sharing.
  2. Building a preview from a code (no copying yet).
  3. Performing the actual deep copy from source workplace to target.

The copy is best-effort transactional via the caller's session. The
router commits once at the end; on any exception nothing is persisted.
"""
from __future__ import annotations

import secrets
import time
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import (
    Hall,
    HallLayout,
    ImportShare,
    MenuCategory,
    MenuItem,
    Table,
    TablePosition,
    Workplace,
)
from utils.ids import new_id
from utils.time import utc_ts


# ============================================================
# Code generation
# ============================================================

# Friendly alphabet: uppercase letters and digits, MINUS visually-ambiguous
# characters (0/O, 1/I, L). 32 symbols ⇒ 32^8 ≈ 10^12 combinations, plenty
# for a non-guessable code while staying short enough to dictate over the
# phone.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


async def _generate_unique_code(session: AsyncSession, attempts: int = 8) -> str:
    """
    Try a few times to find a code that doesn't already exist. At 32^8
    combinations the first attempt practically always wins; the loop is
    insurance, not necessity.
    """
    for _ in range(attempts):
        code = _generate_code()
        existing = await session.scalar(
            select(ImportShare.id).where(ImportShare.code == code)
        )
        if existing is None:
            return code
    # Should never happen with the chosen alphabet/length, but fail loud
    # rather than return a duplicate that would later 500 on insert.
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="could not generate a unique share code, please retry",
    )


# ============================================================
# Create
# ============================================================

async def create_share(
    session: AsyncSession,
    *,
    workplace: Workplace,
    user_id: int,
    ttl_hours: int,
) -> ImportShare:
    """Create a new share. Caller (router) must have verified owner rights."""
    code = await _generate_unique_code(session)
    now = utc_ts()
    share = ImportShare(
        id=new_id(),
        code=code,
        workplace_id=workplace.id,
        created_by_user_id=user_id,
        created_at=now,
        expires_at=now + ttl_hours * 3600,
        revoked_at=None,
        import_count=0,
    )
    session.add(share)
    await session.flush()
    return share


# ============================================================
# Lookup
# ============================================================

async def get_active_share_by_code(
    session: AsyncSession, code: str
) -> Optional[ImportShare]:
    """
    Resolve a share by its public code, but only if it's still active —
    not revoked and not expired. Returns None for missing/inactive so the
    caller can return a friendly 404 instead of leaking which codes exist.
    """
    code_upper = code.strip().upper()
    share = await session.scalar(
        select(ImportShare).where(ImportShare.code == code_upper)
    )
    if share is None:
        return None
    if share.revoked_at is not None:
        return None
    if share.expires_at <= utc_ts():
        return None
    return share


async def list_shares_for_workplace(
    session: AsyncSession, workplace_id: str
) -> list[ImportShare]:
    """All shares (active + dead) for an owner's management screen."""
    return list(
        (
            await session.execute(
                select(ImportShare)
                .where(ImportShare.workplace_id == workplace_id)
                .order_by(ImportShare.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


def share_is_active(share: ImportShare) -> bool:
    return share.revoked_at is None and share.expires_at > utc_ts()


# ============================================================
# Revoke
# ============================================================

async def revoke_share(session: AsyncSession, share: ImportShare) -> None:
    if share.revoked_at is None:
        share.revoked_at = utc_ts()
        await session.flush()


# ============================================================
# Preview
# ============================================================

async def build_preview(
    session: AsyncSession, share: ImportShare
) -> dict:
    """
    Collect the minimum the importer needs to choose what to copy:
    workplace title, halls with table/layout counts, categories with
    item counts. Lightweight aggregate queries; no full row payloads.
    """
    wp = await session.get(Workplace, share.workplace_id)
    if wp is None:
        # Shouldn't happen — share has FK CASCADE — but guard anyway.
        raise HTTPException(
            status.HTTP_410_GONE, "source workplace no longer exists"
        )

    halls = list(
        (
            await session.execute(
                select(Hall)
                .where(Hall.workplace_id == wp.id)
                .options(
                    selectinload(Hall.tables),
                    selectinload(Hall.layouts),
                )
                .order_by(Hall.position)
            )
        )
        .scalars()
        .all()
    )

    categories = list(
        (
            await session.execute(
                select(MenuCategory)
                .where(MenuCategory.workplace_id == wp.id)
                .options(selectinload(MenuCategory.items))
                .order_by(MenuCategory.position)
            )
        )
        .scalars()
        .all()
    )

    return {
        "source_workplace_id": wp.id,
        "source_workplace_title": wp.title,
        "halls": [
            {
                "id": h.id,
                "name": h.name,
                "tables_count": len(h.tables),
                "layouts_count": len(h.layouts),
            }
            for h in halls
        ],
        "categories": [
            {
                "id": c.id,
                "title": c.title,
                "items_count": len(c.items),
            }
            for c in categories
        ],
    }


# ============================================================
# Apply (the actual copy)
# ============================================================

async def apply_import(
    session: AsyncSession,
    *,
    share: ImportShare,
    target_workplace: Workplace,
    hall_ids: list[str],
    category_ids: list[str],
    replace_halls: bool = False,
    replace_categories: bool = False,
) -> dict:
    """
    Copy the selected halls and categories from the share's source into
    the target workplace. Generates fresh IDs everywhere — old IDs from
    the source never appear in the target.

    Order of operations:
      1. (optional) Delete target's current halls / categories if the
         matching replace_* flag is on. Active orders survive via
         ON DELETE SET NULL — they just lose their table_id /
         menu_item_id attachment.
      2. Halls (and their tables + layouts + positions) come first.
      3. Then categories (and their items).
    Halls and categories are independent — they don't reference each other.

    Halls bring their layouts along automatically. The layout's
    TablePosition rows reference tables by `number` (not id), and we
    preserve those numbers when copying tables, so the relationship
    survives the ID rewrite without any extra bookkeeping.

    Positions are renumbered to land at the end of the target's existing
    lists, so existing items aren't displaced when the user imports
    (or start at 0 if a replace flag wiped the target first).

    Self-import safety: if the target is the same workplace as the share
    source, the replace flags MUST be off — wiping then re-copying from
    the just-wiped rows would leave the workplace empty. The router
    enforces this; we double-check here.
    """
    is_self_import = share.workplace_id == target_workplace.id
    if is_self_import and (replace_halls or replace_categories):
        # Defensive: caller should have caught this. Treat as a no-op
        # for the replace flags rather than wiping everything.
        replace_halls = False
        replace_categories = False

    halls_imported = 0
    tables_imported = 0
    layouts_imported = 0
    categories_imported = 0
    items_imported = 0
    halls_replaced = 0
    categories_replaced = 0

    from sqlalchemy import func, delete

    # ----- Optional: wipe matching existing content first -----
    # Each replace flag is gated on its own list being non-empty. Wiping
    # halls when no hall_ids are selected would mean "delete my halls but
    # don't import any" — the UI doesn't expose that, but we guard against
    # it here in case a client constructs the request directly.
    if replace_halls and hall_ids:
        halls_replaced = (
            await session.scalar(
                select(func.count(Hall.id)).where(
                    Hall.workplace_id == target_workplace.id
                )
            )
        ) or 0
        if halls_replaced > 0:
            await session.execute(
                delete(Hall).where(Hall.workplace_id == target_workplace.id)
            )
            await session.flush()

    if replace_categories and category_ids:
        categories_replaced = (
            await session.scalar(
                select(func.count(MenuCategory.id)).where(
                    MenuCategory.workplace_id == target_workplace.id
                )
            )
        ) or 0
        if categories_replaced > 0:
            await session.execute(
                delete(MenuCategory).where(
                    MenuCategory.workplace_id == target_workplace.id
                )
            )
            await session.flush()

    # ----- Halls -----
    if hall_ids:
        # Compute the next free position in the target workplace once,
        # then increment locally as we add halls. After a replace_existing
        # wipe this will be 0.
        target_hall_max_pos = await session.scalar(
            select(func.coalesce(func.max(Hall.position), -1)).where(
                Hall.workplace_id == target_workplace.id
            )
        )
        next_hall_pos = (target_hall_max_pos or -1) + 1

        # Pull the requested halls with all their dependents in one round trip.
        halls = list(
            (
                await session.execute(
                    select(Hall)
                    .where(
                        Hall.workplace_id == share.workplace_id,
                        Hall.id.in_(hall_ids),
                    )
                    .options(
                        selectinload(Hall.tables),
                        selectinload(Hall.layouts).selectinload(
                            HallLayout.positions
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )

        for src_hall in halls:
            new_hall_id = new_id()
            session.add(
                Hall(
                    id=new_hall_id,
                    workplace_id=target_workplace.id,
                    name=src_hall.name,
                    position=next_hall_pos,
                    width=src_hall.width,
                    height=src_hall.height,
                    scale=src_hall.scale,
                )
            )
            next_hall_pos += 1
            halls_imported += 1

            # Tables: keep number, x/y/size/rotation. Reset order_id and status —
            # we're not copying live order state across workplaces.
            for src_t in src_hall.tables:
                session.add(
                    Table(
                        id=new_id(),
                        hall_id=new_hall_id,
                        order_id=None,
                        number=src_t.number,
                        x=src_t.x,
                        y=src_t.y,
                        width=src_t.width,
                        height=src_t.height,
                        rotation=src_t.rotation,
                        border_radius=src_t.border_radius,
                        status="free",
                    )
                )
                tables_imported += 1

            # Layouts ride with the hall — auto, no separate flag.
            for src_layout in src_hall.layouts:
                new_layout_id = new_id()
                session.add(
                    HallLayout(
                        id=new_layout_id,
                        hall_id=new_hall_id,
                        name=src_layout.name,
                    )
                )
                layouts_imported += 1
                for src_pos in src_layout.positions:
                    session.add(
                        TablePosition(
                            id=new_id(),
                            layout_id=new_layout_id,
                            table_number=src_pos.table_number,
                            x=src_pos.x,
                            y=src_pos.y,
                            width=src_pos.width,
                            height=src_pos.height,
                            rotation=src_pos.rotation,
                            border_radius=src_pos.border_radius,
                        )
                    )

    # ----- Categories + items -----
    if category_ids:
        target_cat_max_pos = await session.scalar(
            select(func.coalesce(func.max(MenuCategory.position), -1)).where(
                MenuCategory.workplace_id == target_workplace.id
            )
        )
        next_cat_pos = (target_cat_max_pos or -1) + 1

        categories = list(
            (
                await session.execute(
                    select(MenuCategory)
                    .where(
                        MenuCategory.workplace_id == share.workplace_id,
                        MenuCategory.id.in_(category_ids),
                    )
                    .options(selectinload(MenuCategory.items))
                )
            )
            .scalars()
            .all()
        )

        for src_cat in categories:
            new_cat_id = new_id()
            session.add(
                MenuCategory(
                    id=new_cat_id,
                    workplace_id=target_workplace.id,
                    title=src_cat.title,
                    position=next_cat_pos,
                    is_active=True,
                )
            )
            next_cat_pos += 1
            categories_imported += 1

            # Items: keep title/description/portion/price. Positions stay
            # relative inside the category — but force is_active=True so
            # a deactivated source item doesn't silently vanish on import.
            for idx, src_item in enumerate(src_cat.items):
                session.add(
                    MenuItem(
                        id=new_id(),
                        category_id=new_cat_id,
                        title=src_item.title,
                        description=src_item.description,
                        portion=src_item.portion,
                        price=src_item.price,
                        position=idx,
                        is_active=True,
                    )
                )
                items_imported += 1

    # Bump usage counter on the share.
    share.import_count += 1

    await session.flush()

    return {
        "halls_imported": halls_imported,
        "tables_imported": tables_imported,
        "layouts_imported": layouts_imported,
        "categories_imported": categories_imported,
        "items_imported": items_imported,
        "halls_replaced": halls_replaced,
        "categories_replaced": categories_replaced,
    }