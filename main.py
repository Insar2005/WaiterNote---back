from contextlib import asynccontextmanager
from sqlalchemy import select, update, delete, func
from fastapi import FastAPI, APIRouter, HTTPException
from sqlalchemy.orm import selectinload, with_loader_criteria
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from models import engine, init_db, User, Hall, Table, Shift, Order, MenuCategory, MenuItem, OrderItem, async_session

import reqs as schem

@asynccontextmanager
async def lifespan(app:FastAPI):
    await init_db()
    print('Bot is ready')
    yield
    
    print("🛑 Отключаемся от БД...")
    await engine.dispose() 

app = FastAPI(title='To Do App', lifespan=lifespan)
router = APIRouter(prefix="/api/users")
# Кибербезопасность
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://waiternote-52ff2.web.app", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@router.get("/{tg_id}")
async def get_user_data(tg_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(User)
            .options(
                selectinload(User.shifts).selectinload(Shift.orders),
                selectinload(User.halls).selectinload(Hall.tables),
                selectinload(User.menu).selectinload(MenuCategory.items),
                with_loader_criteria(Shift, lambda cls: cls.is_closed == False)
            )
            .where(User.tg_id == tg_id)
        )
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return schem.UserResponse.model_validate(user)
    
@router.patch("/{user_id}")
async def update_user(user_id: int, user: schem.UserUpdate):
    async with async_session() as session:
        db_user = await session.scalar(select(User).where(User.id == user_id))
        if not db_user:
            raise HTTPException(status_code=404, detail="User not found")

        for field, value in user.model_dump(exclude_unset=True).items():
            setattr(db_user, field, value)

        await session.commit()
        return {"success": True}

@router.post("/create")
async def create_user(user: schem.UserCreate):
    async with async_session() as session:
        db_user = User(
            tg_id=user.tg_id,
            username=user.username,
            language=user.language,
            place_work_title=user.place_work_title,
            timezone=user.timezone,
            currency=user.currency,
            service_percent=user.service_percent,
            shift_type=user.shift_type,
            pay_for_shift=user.pay_for_shift
        )
        session.add(db_user)
        await session.commit()
        await session.refresh(db_user)
        result = await session.execute(
            select(User)
            .options(
                selectinload(User.shifts).selectinload(Shift.orders),
                selectinload(User.halls).selectinload(Hall.tables),
                selectinload(User.menu).selectinload(MenuCategory.items),
                with_loader_criteria(Shift, lambda cls: cls.is_closed == False)
            )
            .where(User.id == db_user.id)
        )
        return schem.UserResponse.model_validate(result.scalars().first())

@router.post("/{user_id}/shift/create")
async def create_shift(shift: schem.ShiftCreate, user_id: int):
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        # Создаём смену
        db_shift = Shift(
            user_id=user_id,
            start_time=shift.start_time,
            is_closed=shift.is_closed,
            place_work_title=user.place_work_title,
            currency=user.currency,
            service_percent=user.service_percent,
            shift_type=user.shift_type,
            pay_for_shift=user.pay_for_shift
        )
        session.add(db_shift)
        await session.commit()
        await session.refresh(db_shift)

        # Загружаем смену с заказами и позициями
        result = await session.execute(
            select(Shift)
            .options(selectinload(Shift.orders).selectinload(Order.items))
            .where(Shift.id == db_shift.id)
        )

        shift_with_orders = result.scalars().first()
        return schem.ShiftResponse.model_validate(shift_with_orders)

@router.get("/shifts")
async def get_shifts_by_timestamp(min: datetime, max: datetime):
    async with async_session() as session:
        result = await session.execute(
            select(Shift)
            .where(
                Shift.is_closed.is_(True),
                Shift.start_time >= min,
                Shift.end_time <= max
            )
            .order_by(Shift.start_time.desc())
        )
        shifts = result.scalars().all()
        return [schem.ShiftResponse.model_validate(shift) for shift in shifts]

@router.patch("/{shift_id}")
async def update_shift(shift_id: int, shift: schem.ShiftUpdate):
    async with async_session() as session:
        db_shift = await session.scalar(select(Shift).where(Shift.id == shift_id))
        if not db_shift:
            raise HTTPException(status_code=404, detail="Shift not found")

        for field, value in shift.model_dump(exclude_unset=True).items():
            setattr(db_shift, field, value)

        await session.commit()
        return {"success": True}

@router.delete("/{shift_id}")
async def delete_shift(shift_id: int):
    async with async_session() as session:
        db_shift = await session.scalar(select(Shift).where(Shift.id == shift_id))
        if not db_shift:
            raise HTTPException(status_code=404, detail="Shift not found")

        await session.delete(db_shift)
        await session.commit()

        return {"success": True}

@router.post("/{shift_id}/orders")
async def create_order(order: schem.OrderCreate, shift_id: int):
    async with async_session() as session:
        # Проверяем, существует ли смена
        
        # Создаем заказ без items
        db_order = Order(
            shift_id=shift_id,
            table_id=order.table_id,
            table_number=order.table_number,
            hall_name=order.hall_name,
            comments=order.comments,
            total_price=order.total_price,
            
        )
        session.add(db_order)
        await session.flush()  # чтобы получить db_order.id до commit

        # Добавляем позиции заказа
        for item in order.items:
            db_item = OrderItem(
                order_id=db_order.id,
                menu_item_id=item.menu_item_id,
                title=item.title,
                quantity=item.quantity,
                price=item.price,
                comment=item.comment
            )
            session.add(db_item)

        await session.commit()
        await session.refresh(db_order)

        # Загружаем заказ вместе с items
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == db_order.id)
        )
        created_order = result.scalars().first()

        return schem.OrderResponse.model_validate(created_order)
    
@router.patch("/orders/{order_id}")
async def update_order(order_id: int, data: schem.OrderUpdate):
    async with async_session() as session:
        db_order = await session.scalar(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        )
        if not db_order:
            raise HTTPException(status_code=404, detail="Order not found")

        # --- Обновляем только переданные поля заказа ---
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(db_order, field, value)

        # --- Если нужно обновить items ---
        if hasattr(data, "items") and data.items is not None:
            # Удаляем старые позиции
            await session.execute(delete(OrderItem).where(OrderItem.order_id == db_order.id))

            # Добавляем новые
            total_price = 0
            for item in data.items:
                new_item = OrderItem(
                    order_id=db_order.id,
                    menu_item_id=item.menu_item_id,
                    title=item.title,
                    quantity=item.quantity,
                    price=item.price,
                    comment=item.comment,
                )
                
                session.add(new_item)

            

        # --- Сохраняем изменения ---
        await session.commit()
        return {"success": True}

@router.delete("/orders/{order_id}")
async def delete_order(order_id: int):
    async with async_session() as session:
        db_order = await session.scalar(select(Order).where(Order.id == order_id))
        if not db_order:
            raise HTTPException(status_code=404, detail="Order not found")

        await session.delete(db_order)
        await session.commit()

        return {"success": True}

@router.post("/{user_id}/halls")
async def create_hall(hall: schem.HallCreate, user_id: int):
    async with async_session() as session:
        
        # Создаём зал
        db_hall = Hall(
            user_id=user_id,
            name=hall.name,
            position=hall.position
        )
        session.add(db_hall)
        await session.commit()
        await session.refresh(db_hall)

        # Подгружаем зал вместе с его столами
        result = await session.execute(
            select(Hall)
            .options(selectinload(Hall.tables))
            .where(Hall.id == db_hall.id)
        )
        hall_with_tables = result.scalars().first()

        return schem.HallResponse.model_validate(hall_with_tables)

@router.patch("/halls/{hall_id}")
async def update_hall(hall_id: int, hall: schem.HallUpdate):
    async with async_session() as session:
        db_hall = await session.scalar(select(Hall).where(Hall.id == hall_id))
        if not db_hall:
            raise HTTPException(status_code=404, detail="Hall not found")

        for field, value in hall.model_dump(exclude_unset=True).items():
            setattr(db_hall, field, value)

        await session.commit()
        
        return {"success": True}
    
@router.delete("/halls/{hall_id}")
async def delete_hall(hall_id: int):
    async with async_session() as session:
        db_hall = await session.scalar(select(Hall).where(Hall.id == hall_id))
        if not db_hall:
            raise HTTPException(status_code=404, detail="Hall not found")

        await session.delete(db_hall)
        await session.commit()

        return {"success": True}
@router.post("/{hall_id}/tables")
async def create_table(table: schem.TableCreate, hall_id: int):
    async with async_session() as session:
        
        db_table = Table(
            hall_id=hall_id,
            number=table.number,
            x=table.x,
            y=table.y,
            width=table.width,
            height=table.height,
            rotation=table.rotation,
            border_radius=table.border_radius,
            status=table.status
        )
        session.add(db_table)
        await session.commit()
        await session.refresh(db_table)
        result = await session.execute(
            select(Table)
            .where(Table.id == db_table.id)
        )
        return schem.TableResponse.model_validate(result.scalars().first())

@router.patch("/tables/{table_id}")
async def update_table(table_id: int, table: schem.TableUpdate):
    async with async_session() as session:
        db_table = await session.scalar(select(Table).where(Table.id == table_id))
        if not db_table:
            raise HTTPException(status_code=404, detail="Table not found")

        for field, value in table.model_dump(exclude_unset=True).items():
            setattr(db_table, field, value)

        await session.commit()
        
        return {"success": True}

@router.delete("/tables/{table_id}")
async def delete_table(table_id: int):
    async with async_session() as session:
        db_table = await session.scalar(select(Table).where(Table.id == table_id))
        if not db_table:
            raise HTTPException(status_code=404, detail="Table not found")

        await session.delete(db_table)
        await session.commit()

        return {"success": True}

@router.post("/{user_id}/menu")
async def create_menu_category(category: schem.MenuCategoryCreate, user_id: int):
    async with async_session() as session:
        db_category = MenuCategory(user_id=user_id, title=category.title, position=category.position)
        session.add(db_category)
        await session.commit()
        await session.refresh(db_category)
        result = await session.execute(
            select(MenuCategory).options(selectinload(MenuCategory.items))
            .where(MenuCategory.id == db_category.id)
        )
        return schem.MenuCategoryResponse.model_validate(result.scalars().first())
    
@router.patch("/menu/{category_id}")
async def update_menu_category(category_id: int, category: schem.MenuCategoryUpdate):
    async with async_session() as session:
        db_category = await session.scalar(select(MenuCategory).where(MenuCategory.id == category_id))
        if not db_category:
            raise HTTPException(status_code=404, detail="Category not found")

        for field, value in category.model_dump(exclude_unset=True).items():
            setattr(db_category, field, value)

        await session.commit()
        
        return {"success": True}

@router.delete("/menu/{category_id}")
async def delete_menu_category(category_id: int):
    async with async_session() as session:
        db_category = await session.scalar(select(MenuCategory).where(MenuCategory.id == category_id))
        if not db_category:
            raise HTTPException(status_code=404, detail="Category not found")

        await session.delete(db_category)
        await session.commit()

        return {"success": True}

@router.post("/{category_id}/items")
async def create_menu_item(item: schem.MenuItemCreate, category_id: int):
    async with async_session() as session:
        result = await session.execute(select(MenuCategory).where(MenuCategory.id == category_id))
        category = result.scalars().first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        db_item = MenuItem(
            category_id=category.id,
            title=item.title,
            description=item.description,
            portion=item.portion,
            price=item.price,
            position=item.position)
        session.add(db_item)
        await session.commit()
        await session.refresh(db_item)
        result = await session.execute(
            select(MenuItem)
            .where(MenuItem.id == db_item.id)
        )
        return schem.MenuItemResponse.model_validate(result.scalars().first())

@router.patch("/items/{item_id}")
async def update_menu_item(item_id: int, item: schem.MenuItemUpdate):
    async with async_session() as session:
        db_item = await session.scalar(select(MenuItem).where(MenuItem.id == item_id))
        if not db_item:
            raise HTTPException(status_code=404, detail="Menu item not found")

        for field, value in item.model_dump(exclude_unset=True).items():
            setattr(db_item, field, value)

        await session.commit()
        
        return {"success": True}
    
@router.delete("/items/{item_id}")
async def delete_menu_item(item_id: int):
    async with async_session() as session:
        db_item = await session.scalar(select(MenuItem).where(MenuItem.id == item_id))
        if not db_item:
            raise HTTPException(status_code=404, detail="Menu item not found")

        await session.delete(db_item)
        await session.commit()
        
        return {"success": True}

app.include_router(router)