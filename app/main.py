"""FastAPI 实例、挂载路由与静态文件、启动调度器（Spec1 §2）。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR
from .db import init_db
from .routers import admin, auth, rating, weekly
from .scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    start_scheduler()
    logger.info("AIOneWeek 已启动 —— 浏览器打开 http://127.0.0.1:8000")
    yield
    shutdown_scheduler()


app = FastAPI(title="AIOneWeek", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(weekly.router)
app.include_router(rating.router)
app.include_router(admin.router)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "admin.html")
