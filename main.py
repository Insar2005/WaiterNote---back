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
    allow_origins=["https://waiternote-f724a.web.app"],
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
# @router.get("/{tg_id}")
# async def get_user(tg_id: int):
#     # тестовая заглушка
#     if tg_id == 821395808:
#         return {"id": tg_id, "username": "cf_clearance"}
#     raise HTTPException(status_code=404, detail="User not found")

# # ✅ вручную разрешаем preflight OPTIONS (чтобы точно не блокировалось)
# @router.options("/{tg_id}")
# async def options_user(tg_id: int):
#     return JSONResponse(
#         content={},
#         headers={
#             "Access-Control-Allow-Origin": "https://waiternote-f724a.web.app",
#             "Access-Control-Allow-Methods": "GET, OPTIONS",
#             "Access-Control-Allow-Headers": "Content-Type, Authorization",
#         },
#     )

    

app.include_router(router)