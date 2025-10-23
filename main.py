from contextlib import asynccontextmanager

from fastapi import FastAPI, APIRouter, HTTPException

from fastapi.middleware.cors import CORSMiddleware

from models import init_db

import reqs as rq

@asynccontextmanager
async def lifespan(app:FastAPI):
    await init_db()
    yield
    print('Bot is ready')



app = FastAPI(title='To Do App', lifespan=lifespan)
router = APIRouter(prefix="/api/users")
# Кибербезопасность
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://waiternote-52ff2.web.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@router.get("/{tg_id}")
async def get_user(tg_id:int):
    user_info = await rq.get_user_info_by_tg_id(tg_id)
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")
    return user_info

@router.post("/")
async def add_user(user_data: rq.UserCreate):
    user_info = await rq.add_new_user(user_data)
    return user_info

@router.patch("/{tg_id}/update")
async def update_user(tg_id:int, update_data:rq.UserUpdate):
    updated_user = await rq.update_user_info(tg_id, update_data)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return updated_user

#menu
@router.get("/{tg_id}/menu")
async def get_user_menu(tg_id:int):
    user_menu = await rq.get_user_menu_with_items(tg_id)
    if not user_menu:
        raise HTTPException(status_code=404, detail="Menu not found")
    return user_menu

@router.post("/{tg_id}/menu/create")
async def user_menu_create(tg_id: int, create_data: rq.MenuCategoryCreate):
    created_menu = await rq.create_new_category(tg_id, create_data)
    return created_menu

@router.patch("/menu/{category_id}/update")
async def user_menu_update(category_id:int,update_data:rq.MenuCategoryUpdate):
    updated_menu = await rq.menu_update(category_id,update_data)
    if not updated_menu:
        return HTTPException(status_code=404, detail="Error to update")
    return updated_menu

@router.delete("/menu/{category_id}/delete")
async def user_menu_delete(category_id:int):
    deleted_menu = await rq.delete_category(category_id)
    if not deleted_menu:
        return HTTPException(status_code=404, detail="Error to delete category")
    return HTTPException(status_code=200, detail="DELETED SUCCESSFULY")

@router.post("/menu/items/create")
async def user_menu_item_create(create_data:rq.MenuItemCreate):
    created_item = await rq.create_new_item(create_data)
    return created_item

@router.patch("/menu/items/{item_id}/update")
async def user_menu_item_update(item_id:int, update_data:rq.MenuItemUpdate):
    updated_item = await rq.menu_item_update(item_id, update_data)
    return updated_item

@router.delete("/menu/items/{item_id}/delete")
async def user_menu_item_delete(item_id:int):
    deleted = await rq.delete_item(item_id)
    return HTTPException(status_code=200, detail="DELETED SUCCESSFULY")

#SHIFT
@router.get("/{tg_id}/shifts/active_shift")
async def user_active_shift(tg_id:int):
    active_shift = await rq.get_active_shift(tg_id)
    return active_shift

@router.post("/{tg_id}/shifts/create")
async def user_create_shift(tg_id: int, shift_data: rq.WorkShiftCreate):
    created_shift = await rq.create_worksfhift(tg_id, shift_data)
    return created_shift

@router.delete("/shifts/{s_id}/delete")
async def user_delete_shift(s_id:int):
    deleted_shift = await rq.delete_workshift(s_id)
    return deleted_shift

@router.patch("/shifts/{s_id}/update")
async def user_update_shift(s_id:int, update_data:rq.WorkShiftUpdate):
    updated_shift = await rq.work_shift_update(s_id, update_data)
    return updated_shift


#HALL
@router.get("/{tg_id}/map_info")
async def user_map_info(tg_id:int):
    map_info = await rq.get_map_info(tg_id)
    if not map_info:
        raise HTTPException(status_code=404, detail="Map_info not found")
    return map_info

@router.patch("/hall/{h_id}/update")
async def user_hall_update(h_id: int, update_data: rq.HallUpdate):
    updated = await rq.hall_update(h_id, update_data)
    if not updated:
        return HTTPException(status_code = 404, detail="Not updated")
    return updated

@router.post("/{tg_id}/map_info/hall/create")
async def user_hall_create(tg_id:int, create_data: rq.HallCreate):
    created_hall = await rq.create_hall(tg_id, create_data)
    return created_hall

@router.delete("/hall/{h_id}/delete")
async def user_hall_delete(h_id:int):
    deleted = await rq.delete_hall(h_id)
    return deleted


#TABLE
@router.post("/{h_id}/table/create")
async def user_table_create(h_id:int, create_data:rq.TableCreate):
    table = await rq.create_table(h_id, create_data)
    return table

@router.patch("/table/{t_id}/update")
async def user_table_update(t_id:int, update_data: rq.TableUpdate):
    pass

@router.delete("/table/{t_id}/delete")
async def user_table_delete(t_id:int):
    pass

    

app.include_router(router)