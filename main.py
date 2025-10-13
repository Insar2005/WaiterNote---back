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
    allow_origins = ["*"], 
    allow_credentials = True,
    allow_methods = ["*"],
    allow_headers=["*"],
)

@router.get("/{tg_id}")
async def get_user(tg_id:int):
    user_info = await rq.get_user_info_by_tg_id(tg_id)
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")
    return user_info
    

app.include_router(router)