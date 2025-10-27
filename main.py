from contextlib import asynccontextmanager
from sqlalchemy import select, update, delete, func
from fastapi import FastAPI, APIRouter, HTTPException

from fastapi.middleware.cors import CORSMiddleware

from models import init_db, User, Hall, Table, Shift, Order, MenuCategory, MenuItem, OrderItem, async_session

from reqs import UserResponse

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
async def get_user_info_by_tg_id(tg_id: int) -> UserResponse | None:
    async with async_session() as session:
        
            user_info = await session.scalar(
                select(User).where(User.tg_id == tg_id)
            )
            
            return UserResponse.model_validate(user_info) if user_info else HTTPException(status_code=404, detail="User not found")
            
      


app.include_router(router)