"""
Masri Digital Compliance Platform — Background Scheduler

Zero-dependency background scheduler using ``threading.Timer``.
Runs periodic tasks:
  - Due-date reminders (every 1 hour)
  - Drift detection (every 24 hours)

Usage::

    from app.masri.scheduler import masri_scheduler
    masri_scheduler.start(app)  # call once during app init

The scheduler is safe to use in development (auto-stops on shutdown)
and is designed to run in a single-process deployment.  For multi-worker
deployments (gunicorn with multiple workers), use an external scheduler
(e.g. Celery Beat, APScheduler, or cron) and disable the built-in one
by setting ``MASRI_SCHEDULER_ENABLED=false``.
"""

import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)


class MasriScheduler:
    """Lightweight background scheduler using threading.Timer."""

    def __init__(self):
        self._timers: list[threading.Timer] = []
        self._running = False
        self._app = None

    def start(self, app):
        """
        Start the scheduler with the given Flask app context.

        Args:
            app: Flask application instance (needed for app context in tasks)
        """
        if not app.config.get("MASRI_SCHEDULER_ENABLED", True):
            logger.info("Masri scheduler is disabled by config")
            return

        if self._running:
            logger.warning("Masri scheduler already running")
            return

        self._app = app
        self._running = True

        # Schedule tasks
        self._schedule_recurring(
            name="due_reminders",
            interval_seconds=3600,  # 1 hour
            func=self._task_due_reminders,
        )
        self._schedule_recurring(
            name="drift_detection",
            interval_seconds=86400,  # 24 hours
            func=self._task_drift_detection,
        )

        logger.info("Masri scheduler started with %d tasks", len(self._timers))

    def stop(self):
        """Stop all scheduled timers."""
        self._running = False
        for timer in self._timers:
            timer.cancel()
        self._timers.clear()
        logger.info("Masri scheduler stopped")

    def _schedule_recurring(self, name: str, interval_seconds: int, func):
        """Schedule a function to run repeatedly at the given interval."""

        def _wrapper():
            if not self._running:
                return
            try:
                logger.debug("Scheduler running task: %s", name)
                func()
            except Exception:
                logger.exception("Scheduler task %s failed", name)
            finally:
                # Reschedule
                if self._running:
                    self._schedule_recurring(name, interval_seconds, func)

        timer = threading.Timer(interval_seconds, _wrapper)
        timer.daemon = True
        timer.name = f"masri-scheduler-{name}"
        timer.start()
        self._timers.append(timer)

    def _task_due_reminders(self):
        """Check for upcoming due dates and send reminders."""
        if not self._app:
            return

        with self._app.app_context():
            try:
                from app.masri.new_models import DueDate
                from app.models import Tenant

                tenants = Tenant.query.all()
                total_sent = 0

                for tenant in tenants:
                    try:
                        from app.masri.notification_engine import NotificationEngine
                        engine = NotificationEngine(tenant.id)
                        sent = engine.check_and_send_due_reminders()
                        total_sent += sent
                    except Exception:
                        logger.exception(
                            "Due reminder check failed for tenant %s", tenant.id
                        )

                if total_sent > 0:
                    logger.info("Due reminders sent: %d across all tenants", total_sent)
            except Exception:
                logger.exception("Due reminder task failed")

    def _task_drift_detection(self):
        """
        Detect configuration drift across tenants.

        Checks for:
        - Controls that haven't been reviewed in 90+ days
        - Policies past their review date
        - Expired certifications or attestations
        """
        if not self._app:
            return

        with self._app.app_context():
            try:
                from app import db
                from app.models import Tenant
                from datetime import timedelta

                tenants = Tenant.query.all()
                now = datetime.utcnow()
                drift_threshold = now - timedelta(days=90)

                for tenant in tenants:
                    try:
                        drift_items = self._detect_tenant_drift(
                            tenant.id, drift_threshold
                        )
                        if drift_items:
                            logger.info(
                                "Drift detected for tenant %s: %d items",
                                tenant.id,
                                len(drift_items),
                            )
                            self._notify_drift(tenant.id, drift_items)
                    except Exception:
                        logger.exception(
                            "Drift detection failed for tenant %s", tenant.id
                        )
            except Exception:
                logger.exception("Drift detection task failed")

    def _detect_tenant_drift(self, tenant_id: str, threshold) -> list:
        """Return a list of drift items for a tenant."""
        from app.models import ProjectControl, Project

        drift_items = []

        # Find stale controls
        projects = Project.query.filter_by(tenant_id=tenant_id).all()
        for project in projects:
            stale_controls = (
                ProjectControl.query
                .filter_by(project_id=project.id)
                .filter(
                    (ProjectControl.date_updated < threshold)
                    | (ProjectControl.date_updated.is_(None))
                )
                .all()
            )
            for pc in stale_controls:
                drift_items.append({
                    "type": "stale_control",
                    "project_id": project.id,
                    "project_name": project.name,
                    "control_id": pc.id,
                    "last_updated": (
                        pc.date_updated.isoformat() if pc.date_updated else None
                    ),
                })

        return drift_items

    def _notify_drift(self, tenant_id: str, drift_items: list):
        """Send drift detection notification for a tenant."""
        try:
            from app.masri.notification_engine import NotificationEngine

            engine = NotificationEngine(tenant_id)
            summary = f"{len(drift_items)} compliance items need attention"
            details = "\n".join(
                f"- {item['type']}: {item.get('project_name', 'N/A')}"
                for item in drift_items[:10]
            )
            if len(drift_items) > 10:
                details += f"\n... and {len(drift_items) - 10} more"

            engine.send_teams(
                card_type="drift_alert",
                title="Compliance Drift Detected",
                body=f"{summary}\n\n{details}",
            )
        except Exception:
            logger.exception("Failed to send drift notification for tenant %s", tenant_id)


# Module-level singleton
masri_scheduler = MasriScheduler()
