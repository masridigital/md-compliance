"""
Celery application factory for MD Compliance background tasks.

Uses Redis DB 1 as broker (DB 0 is rate limiting).
Falls back gracefully — if Celery/Redis is unavailable, the
MasriScheduler in scheduler.py uses threading.Timer instead.

Usage (only when celery is installed and Docker profile enabled):
    celery -A app.masri.celery_app:celery worker --loglevel=info
    celery -A app.masri.celery_app:celery beat --loglevel=info
"""

import logging

logger = logging.getLogger(__name__)

# Graceful import — celery may not be installed
try:
    from celery import Celery
    _CELERY_INSTALLED = True
except ImportError:
    _CELERY_INSTALLED = False

# Only create the Celery app and tasks if celery is installed
celery = None
_flask_app = None

if _CELERY_INSTALLED:
    celery = Celery("md_compliance")
    celery.conf.update(
        broker_url="redis://redis:6379/1",
        result_backend="redis://redis:6379/1",
        timezone="UTC",
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        beat_schedule={
            "due-reminders": {
                "task": "app.masri.celery_app.task_due_reminders",
                "schedule": 3600.0,
            },
            "drift-detection": {
                "task": "app.masri.celery_app.task_drift_detection",
                "schedule": 86400.0,
            },
            "auto-update-check": {
                "task": "app.masri.celery_app.task_auto_update",
                "schedule": 3600.0,
            },
            "integration-refresh": {
                "task": "app.masri.celery_app.task_integration_refresh",
                "schedule": 86400.0,
            },
            "model-recommendations": {
                "task": "app.masri.celery_app.task_model_recommendations",
                "schedule": 604800.0,
            },
            "backup-integration-data": {
                "task": "app.masri.celery_app.task_backup_integration_data",
                "schedule": 86400.0,
            },
        },
    )


def init_celery(app):
    """Configure Celery from Flask app config and bind Flask context."""
    global _flask_app
    if not _CELERY_INSTALLED or celery is None:
        return

    _flask_app = app

    # Ensure the scheduler singleton has the app reference in Celery worker processes
    try:
        from app.masri.scheduler import masri_scheduler
        if not masri_scheduler._app:
            masri_scheduler._app = app
    except Exception:
        pass

    broker = app.config.get("CELERY_BROKER_URL", "redis://redis:6379/1")
    backend = app.config.get("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

    celery.conf.update(broker_url=broker, result_backend=backend)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with _flask_app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    logger.info("Celery configured with broker: %s", broker)


def _get_scheduler():
    """Get the MasriScheduler singleton for accessing task methods."""
    from app.masri.scheduler import masri_scheduler
    return masri_scheduler


def _safe_task(task_func):
    """Execute a scheduler task with proper DB session management."""
    from app import db
    try:
        db.session.remove()
    except Exception:
        pass
    try:
        task_func()
    finally:
        try:
            db.session.remove()
        except Exception:
            pass


def is_celery_available():
    """Check if Celery workers are running and reachable."""
    if not _CELERY_INSTALLED or celery is None:
        return False
    try:
        result = celery.control.ping(timeout=2.0)
        return bool(result)
    except Exception:
        return False


# Task definitions — only created when celery is installed
if _CELERY_INSTALLED:

    @celery.task(name="app.masri.celery_app.task_due_reminders", bind=True, max_retries=2)
    def task_due_reminders(self):
        _safe_task(_get_scheduler()._task_due_reminders)

    @celery.task(name="app.masri.celery_app.task_drift_detection", bind=True, max_retries=2)
    def task_drift_detection(self):
        _safe_task(_get_scheduler()._task_drift_detection)

    @celery.task(name="app.masri.celery_app.task_auto_update", bind=True, max_retries=2)
    def task_auto_update(self):
        _safe_task(_get_scheduler()._task_auto_update)

    @celery.task(name="app.masri.celery_app.task_integration_refresh", bind=True, max_retries=2)
    def task_integration_refresh(self):
        _safe_task(_get_scheduler()._task_integration_refresh)

    @celery.task(name="app.masri.celery_app.task_model_recommendations", bind=True, max_retries=1)
    def task_model_recommendations(self):
        _safe_task(_get_scheduler()._task_model_recommendations)

    @celery.task(name="app.masri.celery_app.task_backup_integration_data", bind=True, max_retries=2)
    def task_backup_integration_data(self):
        _safe_task(_get_scheduler()._task_backup_integration_data)
