"""单进程 AsyncIOScheduler，串行提交元数据、链接维护和引用更新任务。

定时任务与手动任务重叠时，等待已有任务结束，不丢弃该次提交。
"""
import asyncio
import logging
import zoneinfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.services.pipeline import CrawlPipeline

log = logging.getLogger("papertracker.scheduler")


def start_scheduler(pipeline: CrawlPipeline) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=zoneinfo.ZoneInfo(settings.timezone))

    async def submit_when_idle(method):
        while not await method():
            log.warning("Scheduled task %s is waiting for the active collection", method.__name__)
            await pipeline.wait_idle()
            await asyncio.sleep(1)

    # 容器停机期间由启动采集补齐范围；内存调度器不保留停机时的 cron 记录。
    scheduler.add_job(
        submit_when_idle,
        CronTrigger(day_of_week="mon", hour=4, minute=0, timezone=settings.timezone),
        args=[pipeline.submit_weekly],
        id="weekly_crawl",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=86400,
    )
    # 上游预算不足时保留链接维护断点，下一周继续。
    scheduler.add_job(
        submit_when_idle,
        CronTrigger(day_of_week="tue", hour=6, minute=30, timezone=settings.timezone),
        args=[pipeline.submit_links_backfill],
        id="links_backfill",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=86400,
    )
    # 每月 1 日 06:00：引用数分级刷新（F-022）
    scheduler.add_job(
        submit_when_idle,
        CronTrigger(day="1", hour=6, timezone=settings.timezone),
        args=[pipeline.submit_monthly_metrics],
        id="monthly_metrics",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=86400,
    )
    scheduler.start()
    return scheduler
