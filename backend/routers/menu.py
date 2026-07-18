from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select, func, update as sql_update
from sqlalchemy.orm import selectinload

from models import MenuCategory, MenuItem, Workplace, WorkplaceMember
from deps import SessionDep, CurrentUser, WorkplaceDep
from schemas.menu import (
    MenuCategoryCreate, MenuCategoryUpdate, MenuCategoryOut,
    MenuItemCreate, MenuItemUpdate, MenuItemOut,
)
from schemas.common import ReorderRequest


# ===== Access helpers =====

async def get_category_for_user(
    category_id: Annotated[str, Path()],
    user: CurrentUser,
    session: SessionDep,
) -> MenuCategory:
    stmt = (
        select(MenuCategory)
        .join(Workplace, Workplace.id == MenuCategory.workplace_id)
        .join(WorkplaceMember, WorkplaceMember.workplace_id == Workplace.id)
        .where(
            MenuCategory.id == category_id,
            WorkplaceMember.user_id == user.id,
        )
    )
    result = await session.execute(stmt)
    cat = result.scalar_one_or_none()
    if cat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "category not found or access denied")
    return cat


CategoryDep = Annotated[MenuCategory, Depends(get_category_for_user)]


async def get_item_for_user(
    item_id: Annotated[str, Path()],
    user: CurrentUser,
    session: SessionDep,
) -> MenuItem:
    stmt = (
        select(MenuItem)
        .join(MenuCategory, MenuCategory.id == MenuItem.category_id)
        .join(Workplace, Workplace.id == MenuCategory.workplace_id)
        .join(WorkplaceMember, WorkplaceMember.workplace_id == Workplace.id)
        .where(
            MenuItem.id == item_id,
            WorkplaceMember.user_id == user.id,
        )
    )
    result = await session.execute(stmt)
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "menu item not found or access denied")
    return item


ItemDep = Annotated[MenuItem, Depends(get_item_for_user)]


# ===== Routers =====

# Tree-load + create live under workplace; single-entity ops standalone
cat_under_wp = APIRouter(prefix="/workplaces/{workplace_id}/menu", tags=["menu"])
cat_router = APIRouter(prefix="/menu/categories", tags=["menu"])
item_under_cat = APIRouter(prefix="/menu/categories/{category_id}/items", tags=["menu"])
item_router = APIRouter(prefix="/menu/items", tags=["menu"])


# ===== Category endpoints =====

@cat_under_wp.get("", response_model=list[MenuCategoryOut])
async def get_menu(
    workplace: WorkplaceDep,
    session: SessionDep,
    active_only: bool = False,
):
    """
    Load full menu tree: categories with their items.

    - active_only=False (default): everything, for the menu editor
    - active_only=True: only is_active=True at both levels, for OrderBuilder
    """
    stmt = (
        select(MenuCategory)
        .where(MenuCategory.workplace_id == workplace.id)
        .options(selectinload(MenuCategory.items))
        .order_by(MenuCategory.position)
    )
    if active_only:
        stmt = stmt.where(MenuCategory.is_active.is_(True))

    result = await session.execute(stmt)
    categories = list(result.scalars().all())

    if active_only:
        # filter items in-memory (selectinload loads them all)
        for cat in categories:
            cat.items = [i for i in cat.items if i.is_active]

    # ensure items inside each category are sorted by position
    for cat in categories:
        cat.items.sort(key=lambda i: i.position)

    return categories



async def _validate_parent(
    session,
    *,
    workplace_id: str,
    category_id: str | None,
    parent_id: str | None,
) -> None:
    """Проверка parent_id перед записью: родитель существует, принадлежит
    тому же заведению, не сама категория и не её потомок (иначе цикл —
    обе ветки исчезают из дерева на клиенте)."""
    if parent_id is None:
        return
    if category_id is not None and parent_id == category_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "category cannot be its own parent"
        )
    parent = await session.get(MenuCategory, parent_id)
    if parent is None or parent.workplace_id != workplace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "parent category not found")
    # подъём по цепочке родителей: если встретили category_id — цикл
    if category_id is not None:
        seen: set[str] = set()
        cursor = parent
        while cursor is not None and cursor.parent_id is not None:
            if cursor.parent_id == category_id:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "cannot move category into its own subtree",
                )
            if cursor.parent_id in seen:
                break  # уже существующий цикл в данных — не зависаем
            seen.add(cursor.parent_id)
            cursor = await session.get(MenuCategory, cursor.parent_id)


@cat_under_wp.post("/categories", response_model=MenuCategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    body: MenuCategoryCreate,
    workplace: WorkplaceDep,
    session: SessionDep,
):
    existing = await session.get(MenuCategory, body.id)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "category id already exists")

    await _validate_parent(
        session,
        workplace_id=workplace.id,
        category_id=None,
        parent_id=body.parent_id,
    )

    # position считается среди siblings одного родителя, чтобы новая
    # подкатегория падала в конец списка внутри своего parent.
    max_pos = await session.scalar(
        select(func.coalesce(func.max(MenuCategory.position), -1))
        .where(
            MenuCategory.workplace_id == workplace.id,
            MenuCategory.parent_id.is_(body.parent_id)
            if body.parent_id is None
            else MenuCategory.parent_id == body.parent_id,
        )
    )

    cat = MenuCategory(
        id=body.id,
        workplace_id=workplace.id,
        title=body.title,
        parent_id=body.parent_id,
        position=max_pos + 1,
    )
    session.add(cat)
    await session.commit()
    await session.refresh(cat, attribute_names=["items"])
    return cat


@cat_router.patch("/{category_id}", response_model=MenuCategoryOut)
async def update_category(
    body: MenuCategoryUpdate,
    cat: CategoryDep,
    session: SessionDep,
):
    patch = body.model_dump(exclude_unset=True)
    if "parent_id" in patch:
        await _validate_parent(
            session,
            workplace_id=cat.workplace_id,
            category_id=cat.id,
            parent_id=patch["parent_id"],
        )
    for k, v in patch.items():
        setattr(cat, k, v)
    await session.commit()
    await session.refresh(cat, attribute_names=["items"])
    cat.items.sort(key=lambda i: i.position)
    return cat


@cat_router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    cat: CategoryDep,
    session: SessionDep,
):
    """Cascades to items. OrderItem.menu_item_id becomes NULL via FK SET NULL,
    but title/price snapshots in OrderItem preserve history."""
    await session.delete(cat)
    await session.commit()


@cat_under_wp.post("/categories/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_categories(
    body: ReorderRequest,
    workplace: WorkplaceDep,
    session: SessionDep,
):
    result = await session.execute(
        select(MenuCategory.id).where(
            MenuCategory.workplace_id == workplace.id,
            MenuCategory.id.in_(body.ids),
        )
    )
    valid_ids = {r[0] for r in result.all()}

    for position, cat_id in enumerate(body.ids):
        if cat_id in valid_ids:
            await session.execute(
                sql_update(MenuCategory)
                .where(MenuCategory.id == cat_id)
                .values(position=position)
            )
    await session.commit()


# ===== Item endpoints =====

@item_under_cat.post("", response_model=MenuItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(
    body: MenuItemCreate,
    cat: CategoryDep,
    session: SessionDep,
):
    existing = await session.get(MenuItem, body.id)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "item id already exists")

    max_pos = await session.scalar(
        select(func.coalesce(func.max(MenuItem.position), -1))
        .where(MenuItem.category_id == cat.id)
    )

    item = MenuItem(
        id=body.id,
        category_id=cat.id,
        title=body.title,
        description=body.description,
        portion=body.portion,
        price=body.price,
        comment_chips=body.comment_chips,
        position=max_pos + 1,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@item_router.patch("/{item_id}", response_model=MenuItemOut)
async def update_item(
    body: MenuItemUpdate,
    item: ItemDep,
    user: CurrentUser,
    session: SessionDep,
):
    patch = body.model_dump(exclude_unset=True)

    # If moving to another category, verify target belongs to same workplace
    if "category_id" in patch and patch["category_id"] != item.category_id:
        new_cat_id = patch["category_id"]
        # Get target category and verify access
        stmt = (
            select(MenuCategory)
            .join(Workplace, Workplace.id == MenuCategory.workplace_id)
            .join(WorkplaceMember, WorkplaceMember.workplace_id == Workplace.id)
            .where(
                MenuCategory.id == new_cat_id,
                WorkplaceMember.user_id == user.id,
            )
        )
        new_cat = (await session.execute(stmt)).scalar_one_or_none()
        if new_cat is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "target category not found or access denied",
            )

        # Verify it's the same workplace (cross-workplace moves not allowed)
        current_cat = await session.get(MenuCategory, item.category_id)
        if current_cat is None or current_cat.workplace_id != new_cat.workplace_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "cannot move item to a category in another workplace",
            )

        # Recompute position at the end of target category
        max_pos = await session.scalar(
            select(func.coalesce(func.max(MenuItem.position), -1))
            .where(MenuItem.category_id == new_cat_id)
        )
        patch["position"] = max_pos + 1

    for k, v in patch.items():
        setattr(item, k, v)

    await session.commit()
    await session.refresh(item)
    return item


@item_router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item: ItemDep,
    session: SessionDep,
):
    await session.delete(item)
    await session.commit()


@item_under_cat.post("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_items(
    body: ReorderRequest,
    cat: CategoryDep,
    session: SessionDep,
):
    result = await session.execute(
        select(MenuItem.id).where(
            MenuItem.category_id == cat.id,
            MenuItem.id.in_(body.ids),
        )
    )
    valid_ids = {r[0] for r in result.all()}

    for position, item_id in enumerate(body.ids):
        if item_id in valid_ids:
            await session.execute(
                sql_update(MenuItem)
                .where(MenuItem.id == item_id)
                .values(position=position)
            )
    await session.commit()