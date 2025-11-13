from contextlib import asynccontextmanager
from sqlalchemy import select, update, delete
from fastapi import FastAPI, APIRouter, HTTPException, Body
from sqlalchemy.orm import selectinload, with_loader_criteria
from fastapi.middleware.cors import CORSMiddleware
from typing import List
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
                selectinload(User.shifts)
                    .selectinload(Shift.orders)
                    .selectinload(Order.items),
                
                selectinload(User.halls)
                    .selectinload(Hall.tables),
                
                selectinload(User.menu)
                    .selectinload(MenuCategory.items),
                
                # фильтр только к Shifts
                with_loader_criteria(
                    Shift,
                    lambda Shift: Shift.is_closed == False
                )
            )
            .where(User.tg_id == tg_id)
        )

        user = result.scalars().first()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # ⭐ Преобразуем ORM → dict, чтобы исключить lazy-load
        return schem.UserResponse.model_validate(user, from_attributes=True)


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
        await session.refresh(db_user, attribute_names=["shifts", "halls", "menu"])

        return schem.UserResponse.model_validate(db_user, from_attributes=True)

@router.post("/{user_id}/shift/create")
async def create_shift(shift: schem.ShiftCreate, user_id: int):
    async with async_session() as session:
        # user = await session.scalar(select(User).where(User.id == user_id))
        
        # Создаём смену
        db_shift = Shift(
            id = shift.id,
            user_id=user_id,
            start_time=shift.start_time,
            place_work_title=shift.place_work_title,
            currency=shift.currency,
            service_percent=shift.service_percent,
            shift_type=shift.shift_type,
            pay_for_shift=shift.pay_for_shift
        )
        session.add(db_shift)
        await session.commit()
        await session.refresh(db_shift,attribute_names=["orders"])
        
        
       
        return {"id": db_shift.id}
@router.get("/shifts")
async def get_shifts_by_timestamp(min: int, max: int):
    async with async_session() as session:
        result = await session.execute(
            select(Shift)
            .options(
                selectinload(Shift.orders)
                .selectinload(Order.items)  # если нужны items внутри заказов
            )
            .where(
                Shift.is_closed.is_(True),
                Shift.start_time >= min,
                Shift.end_time <= max
            )
            .order_by(Shift.start_time.desc())
        )

        shifts = result.scalars().all()

        return [
            schem.ShiftResponse.model_validate(shift, from_attributes=True)
            for shift in shifts
        ]
@router.patch("/shifts/{shift_id}")
async def update_shift(shift_id: str, shift: schem.ShiftUpdate):
    async with async_session() as session:
        db_shift = await session.scalar(select(Shift).where(Shift.id == shift_id))
        if not db_shift:
            raise HTTPException(status_code=404, detail="Shift not found")

        for field, value in shift.model_dump(exclude_unset=True).items():
            setattr(db_shift, field, value)

        await session.commit()
        return {"success": True}

@router.delete("/shifts/{shift_id}")
async def delete_shift(shift_id: str):
    async with async_session() as session:
        db_shift = await session.scalar(select(Shift).where(Shift.id == shift_id))
        if not db_shift:
            raise HTTPException(status_code=404, detail="Shift not found")

        await session.delete(db_shift)
        await session.commit()

        return {"success": True}

@router.post("/{shift_id}/orders")
async def create_order(order: schem.OrderCreate, shift_id: str):
    async with async_session() as session:
      
        shift = await session.scalar(select(Shift).where(Shift.id == shift_id))
        if not shift:
            raise HTTPException(status_code=404, detail="Shift not found")
        
       
        db_order = Order(
            id=order.id,
            shift_id=shift_id,
            table_id=order.table_id,
            table_number=order.table_number,
            hall_name=order.hall_name,
            comments=order.comments,
            total_price=order.total_price,
        )
        session.add(db_order)
        await session.flush()

        
        for item in order.items:
            db_item = OrderItem(
                id = item.id,
                order_id=db_order.id,
                menu_item_id=item.menu_item_id,
                title=item.title,
                quantity=item.quantity,
                price=item.price,
                comment=item.comment
            )
            session.add(db_item)

        
        await session.execute(
            update(Shift)
            .where(Shift.id == shift_id)
            .values(
                total_cash_register=Shift.total_cash_register + order.total_price,
                order_count=Shift.order_count + 1
            )
        )

        await session.commit()
        
        
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == db_order.id)
        )
        created_order = result.scalars().first()

        return schem.OrderResponse.model_validate(created_order)



@router.patch("/orders/{order_id}")
async def update_order(order_id: str, data: schem.OrderUpdate):
    async with async_session() as session:
        db_order = await session.scalar(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        )

        if not db_order:
            raise HTTPException(status_code=404, detail="Order not found")
        status = "waiting"
        if data.is_done is not None or data.is_paid is not None:
            if data.is_done:
                status = "reserved"
            if data.is_paid:
                status = "occupied"
        await session.execute(
                update(Table)
                .where(Table.id == db_order.table_id)
                .values(
                    status=status
                )
            )
        if data.total_price is not None or data.tips is not None:
            new_total_price = data.total_price if data.total_price is not None else db_order.total_price
            new_tips = data.tips if data.tips is not None else db_order.tips

            await session.execute(
                update(Shift)
                .where(Shift.id == db_order.shift_id)
                .values(
                    total_cash_register=Shift.total_cash_register - db_order.total_price + new_total_price,
                    total_tips=Shift.total_tips - db_order.tips + new_tips
                )
            )
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(db_order, field, value)

        
        if hasattr(data, "items") and data.items is not None:
            
            await session.execute(delete(OrderItem).where(OrderItem.order_id == db_order.id))

            
            
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
async def delete_order(order_id: str):
    async with async_session() as session:
        db_order = await session.scalar(select(Order).where(Order.id == order_id))
        if not db_order:
            raise HTTPException(status_code=404, detail="Order not found")
        await session.execute(
                update(Shift)
                .where(Shift.id == db_order.shift_id)
                .values(
                    total_cash_register=Shift.total_cash_register - db_order.total_price,
                    total_tips=Shift.total_tips - db_order.tips,
                    order_count=Shift.order_count - 1
                )
            )
        await session.delete(db_order)
        await session.commit()

        return {"success": True}

@router.post("/{user_id}/halls")
async def create_hall(hall: schem.HallCreate, user_id: int):
    print(schem.HallCreate.model_validate(hall))
    async with async_session() as session:
        
        # Создаём зал
        db_hall = Hall(
            id = hall.id,
            user_id=user_id,
            name=hall.name,
            position=hall.position
        )
        session.add(db_hall)
        await session.commit()
        await session.refresh(db_hall)

        # Подгружаем зал вместе с его столами
        
        

        return {"id": db_hall.id}

@router.patch("/halls/{hall_id}")
async def update_hall(hall_id: str, hall: schem.HallUpdate):
    async with async_session() as session:
        db_hall = await session.scalar(select(Hall).where(Hall.id == hall_id))
        if not db_hall:
            raise HTTPException(status_code=404, detail="Hall not found")

        for field, value in hall.model_dump(exclude_unset=True).items():
            setattr(db_hall, field, value)

        await session.commit()
        
        return {"success": True}
    
@router.delete("/halls/{hall_id}")
async def delete_hall(hall_id: str):
    async with async_session() as session:
        db_hall = await session.scalar(select(Hall).where(Hall.id == hall_id))
        if not db_hall:
            raise HTTPException(status_code=404, detail="Hall not found")

        await session.delete(db_hall)
        await session.commit()

        return {"success": True}
@router.post("/{hall_id}/tables")
async def create_table(table: schem.TableCreate, hall_id: str):
    async with async_session() as session:
        
        db_table = Table(
            id = table.id,
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
        return {"id": db_table.id}

@router.patch("/tables/{table_id}")
async def update_table(table_id: str, table: schem.TableUpdate):
    async with async_session() as session:
        db_table = await session.scalar(select(Table).where(Table.id == table_id))
        if not db_table:
            raise HTTPException(status_code=404, detail="Table not found")

        for field, value in table.model_dump(exclude_unset=True).items():
            setattr(db_table, field, value)

        await session.commit()
        
        return {"success": True}

@router.delete("/tables/{table_id}")
async def delete_table(table_id: str):
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
        db_category = MenuCategory(id = category.id, user_id=user_id, title=category.title, position=category.position)
        session.add(db_category)
        await session.commit()
        await session.refresh(db_category)
        
        return {"id": db_category.id}
    
@router.patch("/menu/{category_id}")
async def update_menu_category(category_id: str, category: schem.MenuCategoryUpdate):
    async with async_session() as session:
        db_category = await session.scalar(select(MenuCategory).where(MenuCategory.id == category_id))
        if not db_category:
            raise HTTPException(status_code=404, detail="Category not found")

        for field, value in category.model_dump(exclude_unset=True).items():
            setattr(db_category, field, value)

        await session.commit()
        
        return {"success": True}

@router.delete("/menu/{category_id}")
async def delete_menu_category(category_id: str):
    async with async_session() as session:
        db_category = await session.scalar(select(MenuCategory).where(MenuCategory.id == category_id))
        if not db_category:
            raise HTTPException(status_code=404, detail="Category not found")

        await session.delete(db_category)
        await session.commit()

        return {"success": True}

@router.post("/{category_id}/items")
async def create_menu_item(item: schem.MenuItemCreate, category_id: str):
    async with async_session() as session:
        result = await session.execute(select(MenuCategory).where(MenuCategory.id == category_id))
        category = result.scalars().first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        db_item = MenuItem(
            id = item.id,
            category_id=category.id,
            title=item.title,
            description=item.description,
            portion=item.portion,
            price=item.price,
            position=item.position)
        session.add(db_item)
        await session.commit()
        await session.refresh(db_item)
       
        return {"id":db_item.id}

@router.patch("/items/{item_id}")
async def update_menu_item(item_id: str, item: schem.MenuItemUpdate):
    async with async_session() as session:
        db_item = await session.scalar(select(MenuItem).where(MenuItem.id == item_id))
        if not db_item:
            raise HTTPException(status_code=404, detail="Menu item not found")

        for field, value in item.model_dump(exclude_unset=True).items():
            setattr(db_item, field, value)

        await session.commit()
        
        return {"success": True}
    
@router.delete("/items/{item_id}")
async def delete_menu_item(item_id: str):
    async with async_session() as session:
        db_item = await session.scalar(select(MenuItem).where(MenuItem.id == item_id))
        if not db_item:
            raise HTTPException(status_code=404, detail="Menu item not found")

        await session.delete(db_item)
        await session.commit()
        
        return {"success": True}
@router.post("/sync")
async def batch_sync(ops: List[schem.SyncOperation] = Body(...)):
    model_map = {
        "user": User,
        "hall": Hall,
        "table": Table,
        "category": MenuCategory,
        "item": MenuItem,
        "shift": Shift,
        "order": Order,
        "order_item": OrderItem,
    }

    results = []

    async with async_session() as session:
        for op in ops:
            try:
                model = model_map.get(op.entity)
                if not model:
                    raise ValueError(f"Unknown entity: {op.entity}")

                data = op.payload.copy()
                if "user_id" in model.__table__.columns and "user_id" not in data:
                    data["user_id"] = op.user_id

                if op.action == "add":
                    obj = model(**data)
                    session.add(obj)
                    await session.flush()  # отправляем INSERT в БД
                    await session.commit()  # ✅ коммитим отдельную операцию
                    results.append({"txId": op.id, "status": "ok"})

                elif op.action == "update":
                    await session.execute(
                        update(model)
                        .where(model.id == data["id"])
                        .values({k: v for k, v in data.items() if k != "id"})
                    )
                    await session.commit()
                    results.append({"txId": op.id, "status": "ok"})

                elif op.action == "delete":
                    await session.execute(delete(model).where(model.id == data["id"]))
                    await session.commit()
                    results.append({"txId": op.id, "status": "ok"})

            except Exception as e:
                await session.rollback()  # откатываем только текущую операцию
                results.append({
                    "txId": op.id,
                    "status": "error",
                    "entity": op.entity,
                    "action": op.action,
                    "error": str(e)
                })
    print(results)
    return results

# @router.post("/sync")
# async def batch_sync(ops: list[schem.SyncOperation]):
#     results = []
#     print(ops)
#     model_map = {
#         "user": User,
#         "hall": Hall,
#         "table": Table,
#         "category": MenuCategory,
#         "item": MenuItem,
#         "shift": Shift,
#         "order": Order,
#         "order_item": OrderItem,
#     }

#     async with async_session() as session:
#         for op in ops:
#             try:
#                 model = model_map.get(op.entity)
#                 if not model:
#                     raise ValueError(f"Unknown entity: {op.entity}")

#                 # 🟢 CREATE
#                 if op.action == "add":
#                     obj = model(**op.payload, user_id=op.user_id) \
#                         if "user_id" in model.__table__.columns else model(**op.payload)
#                     session.add(obj)
#                     await session.flush()

#                 # 🟡 UPDATE (PATCH)
#                 elif op.action == "update":
#                     db_obj = await session.get(model, op.payload["id"])
#                     if not db_obj:
#                         raise ValueError(f"{op.entity} not found: {op.payload['id']}")

#                     # обновляем только поля, которые реально пришли
#                     for field, value in op.payload.items():
#                         if field != "id" and hasattr(db_obj, field):
#                             setattr(db_obj, field, value)

#                 # 🔴 DELETE
#                 elif op.action == "delete":
#                     await session.execute(
#                         delete(model).where(model.id == op.payload["id"])
#                     )

#                 results.append({"txId": op.id, "status": "ok"})

#             except Exception as e:
#                 results.append({"txId": op.id, "status": "error", "error": str(e)})
#                 await session.rollback()

#         await session.commit()

#     return results

app.include_router(router)