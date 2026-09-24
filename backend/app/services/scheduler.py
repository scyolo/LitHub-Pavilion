"""调度器（4.1）：单进程 AsyncIOScheduler，cron 任务与状态。

全部任务经 pipeline.submit_* 原子占位提交（P1-6）：定时任务与手动触发/彼此重叠时，
后到者等待已有任务完成并记 WARNING，不丢弃该次提交。
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
    # 每日 05:00 PDF 补下载（仅下载模式注册；链接模式下不注册）
    if settings.pdf_download_enabled:
        scheduler.add_job(
            pipeline.submit_pdf_backlog,
            CronTrigger(hour=5, minute=0, timezone=settings.timezone),
            id="pdf_backlog",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=86400,
        )
    else:
        # 链接模式自愈：每周二 06:30（紧跟周一采集）用 OpenAlex 预算补 oa_url，
        # 预算不足时下周继续，直至覆盖完整（用户要求每周一次，非每日）
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
