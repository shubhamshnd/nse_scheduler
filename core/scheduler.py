"""
scheduler.py — APScheduler integration.
Reads job schedules from config.yaml and runs pipeline tasks at configured times.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron         import CronTrigger
import pytz

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler = None


def _make_job_fn(task_list: list, cfg_path: str):
    def job_fn():
        from core.config_loader import load_config
        from pathlib import Path
        cfg = load_config(Path(cfg_path))
        from core.pipeline import run_tasks
        logger.info(f"Scheduled job triggered: {task_list}")
        run_tasks(task_list, cfg)
    return job_fn


def init_scheduler(cfg: dict, config_path: str) -> BackgroundScheduler:
    global _scheduler

    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)

    tz_name = cfg["schedule"].get("timezone", "Asia/Kolkata")
    tz      = pytz.timezone(tz_name)

    _scheduler = BackgroundScheduler(timezone=tz)

    if cfg["schedule"].get("enabled", True):
        for job in cfg["schedule"].get("jobs", []):
            name     = job["name"]
            time_str = job["time"]
            tasks    = job["tasks"]
            hour, minute = time_str.split(":")

            _scheduler.add_job(
                _make_job_fn(tasks, config_path),
                trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
                id=name,
                name=name,
                replace_existing=True,
                misfire_grace_time=300,
            )
            logger.info(f"Scheduled job '{name}' at {time_str} {tz_name}: {tasks}")

    _scheduler.start()
    logger.info("Scheduler started.")
    return _scheduler


def get_scheduler() -> BackgroundScheduler:
    return _scheduler


def list_jobs(scheduler: BackgroundScheduler) -> list:
    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            "id":       job.id,
            "name":     job.name,
            "next_run": next_run.strftime("%Y-%m-%d %H:%M %Z") if next_run else "paused",
        })
    return jobs


def reload_schedule(cfg: dict, config_path: str):
    global _scheduler
    if _scheduler and _scheduler.running:
        for job in _scheduler.get_jobs():
            job.remove()
        logger.info("Cleared all scheduled jobs for reload.")
        tz_name = cfg["schedule"].get("timezone", "Asia/Kolkata")
        tz      = pytz.timezone(tz_name)
        if cfg["schedule"].get("enabled", True):
            for job in cfg["schedule"].get("jobs", []):
                name     = job["name"]
                time_str = job["time"]
                tasks    = job["tasks"]
                hour, minute = time_str.split(":")
                _scheduler.add_job(
                    _make_job_fn(tasks, config_path),
                    trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
                    id=name, name=name, replace_existing=True, misfire_grace_time=300,
                )
                logger.info(f"Re-scheduled '{name}' at {time_str}")
