"""APScheduler 每日 08:50 采集任务（Spec1 §8）。

随 FastAPI 启动，不使用系统 cron / Windows 计划任务。
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .collector import collect, today_str

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def job_daily_collect() -> None:
    """对当天日期执行一次采集。异常必须吞掉，不得让调度器崩溃。"""
    day = today_str()
    try:
        run = collect(day)
        logger.info("定时采集 %s 完成，status=%s items=%d", day, run.status, run.item_count)
    except Exception:  # noqa: BLE001 —— 调度器线程必须存活
        logger.exception("定时采集 %s 异常", day)


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        job_daily_collect,
        CronTrigger(hour=8, minute=50),
        id="daily_collect",
        misfire_grace_time=3600,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    logger.info("调度器已启动：每日 08:50 采集")
    _scheduler = scheduler
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
