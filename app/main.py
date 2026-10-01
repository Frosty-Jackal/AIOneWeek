"""FastAPI 实例、挂载路由与静态文件（Spec1 §2）。

Spec3 §3.4 删除了每日 08:50 的定时采集：窗口改成「不含今天后」，定时采到的
当天数据谁也看不到，进窗口时反而只是当天前 8 小时的残缺快照。采集入口只剩
两个 —— 用户点「查看当周」时的缺口补采，以及管理端的手动采集。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR
from .db import init_db
from .routers import admin, auth, rating, weekly

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info("AIOneWeek 已启动 —— 浏览器打开 http://127.0.0.1:8000")
    yield
    # 无后台任务需要收尾（Spec3 §3.4 删掉了调度器）


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
