from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from models import init_db

import requests as rq

@asynccontextmanager
async def lifespan(app:FastAPI):
    await init_db()
    print('Bot is ready')



app = FastAPI(title='To Do App', lifespan=lifespan)

# Кибербезопасность
app.add_middleware(
    CORSMiddleware,
    allow_origins = ["*"], 
    allow_credentials = True,
    allow_methods = ["*"],
    allow_headers=["*"],
)
