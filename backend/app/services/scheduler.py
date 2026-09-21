"""调度器（4.1）：单进程 AsyncIOScheduler，cron 任务与状态。

全部任务经 pipeline.submit_* 原子占位提交（P1-6）：定时任务与手动触发/彼此重叠时，
后到者被拒绝并记 WARNING，不再静默蒸发。
"""
import logging
import zoneinfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.services.pipeline import CrawlPipeline

log = logging.getLogger("papertracker.scheduler")


def start_scheduler(pipeline: CrawlPipeline) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=zoneinfo.ZoneInfo(settings.timezone))
    # 每周一 04:00 增量（misfire_grace_time=86400：容器错峰启动仍补跑一次）
    scheduler.add_job(
        pipeline.submit_weekly,
        CronTrigger(day_of_week="mon", hour=4, minute=0, timezone=settings.timezone),
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
            pipeline.submit_links_backfill,
            CronTrigger(day_of_week="tue", hour=6, minute=30, timezone=settings.timezone),
            id="links_backfill",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=86400,
        )
    # 每月 1 日 06:00：引用数分级刷新（F-022）
    scheduler.add_job(
        pipeline.submit_monthly_metrics,
        CronTrigger(day="1", hour=6, timezone=settings.timezone),
        id="monthly_metrics",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=86400,
    )
    scheduler.start()
    return scheduler
