from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from models import init_db
from config import get_settings

from routers import workplaces, me, halls, menu, shifts, orders, notes


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Waiter Note API",
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    if settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(workplaces.router)
    app.include_router(me.router)
    app.include_router(halls.hall_under_wp)
    app.include_router(halls.hall_router)
    app.include_router(halls.table_under_hall)
    app.include_router(halls.table_router)
    app.include_router(menu.cat_under_wp)
    app.include_router(menu.cat_router)
    app.include_router(menu.item_under_cat)
    app.include_router(menu.item_router)
    app.include_router(shifts.shift_under_wp)
    app.include_router(shifts.shift_router)
    app.include_router(orders.order_under_shift)
    app.include_router(orders.order_quick_router)
    app.include_router(orders.order_router)
    app.include_router(notes.router)

    return app


app = create_app()