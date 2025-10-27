from contextlib import asynccontextmanager
from sqlalchemy import select, update, delete, func
from fastapi import FastAPI, APIRouter, HTTPException
from sqlalchemy.orm import selectinload
from fastapi.middleware.cors import CORSMiddleware

from models import init_db, User, Hall, Table, Shift, Order, MenuCategory, MenuItem, OrderItem, async_session

from reqs import UserResponse, UserCreate, UserUpdate

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
    allow_origins=["https://waiternote-52ff2.web.app", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@router.get("/{tg_id}")
async def get_user_info_by_tg_id(tg_id: int) -> UserResponse | None:
    async with async_session() as session:
        user_info = await session.scalar(
            select(User).where(User.tg_id == tg_id)
        )

        if not user_info:
            raise HTTPException(status_code=404, detail="User not found")

        return UserResponse.model_validate(user_info)
    
@router.patch("/{user_id}/update")
async def update_user_info_by_user_id(user_id: int, user_data: UserUpdate) -> UserResponse:
    async with async_session() as session:
        user_info = await session.scalar(
            select(User).where(User.id == user_id)
        )

        if not user_info:
            raise HTTPException(status_code=404, detail="User not found")

        for field, value in user_data.model_dump(exclude_unset=True).items():
            setattr(user_info, field, value)

        session.add(user_info)
        await session.commit()
        await session.refresh(user_info)

        return UserResponse.model_validate(user_info)
@router.get("/{tg_id}/data")
async def get_menu_halls_activeshift_by_tg_id(tg_id: int):
    async with async_session() as session:
        user_info = await session.scalar(
            select(User).where(User.tg_id == tg_id)
        )

        if not user_info:
            raise HTTPException(status_code=404, detail="User not found")

        active_shift = await session.scalar(
            select(Shift).where(Shift.user_id == user_info.id, Shift.is_closed == False).options(selectinload(Shift.orders))
        )

        halls = await session.scalars(
            select(Hall).where(Hall.user_id == user_info.id).options(selectinload(Hall.tables))
        )
        halls_list = halls.all()
        menu = await session.scalars(
            select(MenuCategory).where(MenuCategory.user_id == user_info.id).options(selectinload(MenuCategory.items))
        )

        return {
            
            "active_shift": active_shift,
            "halls": halls_list,
            "menu": menu.all()
        }

@router.post("/{tg_id}")
async def create_user(tg_id: int, user_data: UserCreate) -> UserResponse:
    async with async_session() as session:
        new_user = User(
            tg_id=tg_id,
            username=user_data.username,
            place_work_title=user_data.place_work_title,
            language=user_data.language,
            timezone=user_data.timezone,
            currency=user_data.currency,
            
            shift_type=user_data.shift_type,
            pay_for_shift=user_data.pay_for_shift
        )
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)
        return UserResponse.model_validate(new_user)

app.include_router(router)