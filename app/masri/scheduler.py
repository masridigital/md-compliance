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
        self._schedule_recurring(
            name="auto_update_check",
            interval_seconds=3600,
            func=self._task_auto_update,
        )
        self._schedule_recurring(
            name="integration_data_refresh",
            interval_seconds=86400,  # 24 hours
            func=self._task_integration_refresh,
        )
        self._schedule_recurring(
            name="model_recommendations",
            interval_seconds=604800,  # 7 days
            func=self._task_model_recommendations,
        )
        self._schedule_recurring(
            name="integration_data_backup",
            interval_seconds=86400,  # 24 hours
            func=self._task_backup_integration_data,
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
            # Remove the current (now-fired) timer from the list before rescheduling
            self._timers[:] = [t for t in self._timers if t.is_alive()]
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
                from app import db

                tenants = db.session.execute(db.select(Tenant)).scalars().all()
                total_sent = 0

                for tenant in tenants:
                    try:
                        from app.masri.notification_engine import NotificationEngine
                        engine = NotificationEngine()
                        sent = engine.check_and_send_due_reminders(tenant_id=tenant.id)
                        total_sent += (sent or 0)
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

                tenants = db.session.execute(db.select(Tenant)).scalars().all()
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
        from app import db

        drift_items = []

        # Find stale controls
        projects = db.session.execute(db.select(Project).filter_by(tenant_id=tenant_id)).scalars().all()
        for project in projects:
            stale_controls = (
                db.session.execute(
                    db.select(ProjectControl)
                    .filter_by(project_id=project.id)
                    .filter(
                        (ProjectControl.date_updated < threshold)
                        | (ProjectControl.date_updated.is_(None))
                    )
                ).scalars().all()
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

            engine = NotificationEngine()
            summary = f"{len(drift_items)} compliance items need attention"
            details = "\n".join(
                f"- {item['type']}: {item.get('project_name', 'N/A')}"
                for item in drift_items[:10]
            )
            if len(drift_items) > 10:
                details += f"\n... and {len(drift_items) - 10} more"

            engine.send(
                event_type="drift_alert",
                tenant_id=tenant_id,
                data={
                    "summary": summary,
                    "details": details,
                    "drift_count": len(drift_items),
                },
                priority="high",
            )
        except Exception:
            logger.exception("Failed to send drift notification for tenant %s", tenant_id)


    def _send_update_notification(self, subject, body, is_pre=True):
        """Send email notification about updates to all admin users."""
        if not self._app:
            return
        try:
            from app.models import User
            from app import db
            from app.email import send_email

            admins = db.session.execute(
                db.select(User).filter_by(super=True, is_active=True)
            ).scalars().all()

            app_name = self._app.config.get("APP_NAME", "MD Compliance")
            for admin in admins:
                try:
                    send_email(
                        to=admin.email,
                        subject=f"{app_name} — {subject}",
                        template="update_notification",
                        content=body,
                        subject_line=subject,
                    )
                except Exception:
                    logger.debug("Could not send update email to %s", admin.email)
        except Exception:
            logger.debug("Update email notification skipped (email may not be configured)")

    def _task_auto_update(self):
        """Check for and optionally apply updates based on schedule config."""
        if not self._app:
            return

        with self._app.app_context():
            try:
                from app.masri.update_manager import UpdateManager

                schedule = UpdateManager.get_schedule()
                if not schedule.get("enabled"):
                    return

                # Check frequency — only run at configured intervals
                frequency = schedule.get("frequency", "daily")
                freq_hours = {"hourly": 1, "daily": 24, "weekly": 168}.get(frequency, 24)

                last_check = schedule.get("last_check")
                if last_check:
                    from datetime import datetime, timedelta
                    try:
                        last_dt = datetime.fromisoformat(last_check)
                        if datetime.utcnow() - last_dt < timedelta(hours=freq_hours):
                            return  # Not time yet
                    except (ValueError, TypeError):
                        pass

                # Run check
                status = UpdateManager.check()
                logger.info("Auto-update check: %d commits behind", status.get("commits_behind", 0))

                # Update last check time
                import json
                from app.models import ConfigStore
                sched_data = json.loads(ConfigStore.find("auto_update_schedule").value or "{}")
                sched_data["last_check"] = datetime.utcnow().isoformat()
                sched_data["last_result"] = {
                    "available": status.get("available"),
                    "commits_behind": status.get("commits_behind", 0),
                }
                ConfigStore.upsert("auto_update_schedule", json.dumps(sched_data))

                # Notify about available updates
                if status.get("available"):
                    self._send_update_notification(
                        f"{status.get('commits_behind')} update(s) available",
                        "Check the System page to review and apply.",
                        is_pre=True,
                    )

                # Auto-apply if configured
                if schedule.get("auto_apply") and status.get("available"):
                    logger.info("Auto-applying %d pending update(s)", status.get("commits_behind"))

                    # Pre-apply notification
                    self._send_update_notification(
                        "Platform update starting now",
                        f"Applying {status.get('commits_behind')} update(s). The app will restart and all users will be logged out.",
                        is_pre=True,
                    )

                    result = UpdateManager.apply()
                    if result.get("success"):
                        from app.models import Logs
                        Logs.add(
                            message=f"Auto-update applied: {status.get('commits_behind')} commits",
                            action="PUT",
                            namespace="system",
                        )
                        self._send_update_notification(
                            "Platform update completed",
                            f"Successfully applied {status.get('commits_behind')} update(s). All users have been logged out.",
                            is_pre=False,
                        )
                    else:
                        logger.error("Auto-update failed: %s", result.get("message"))
                        self._send_update_notification(
                            "Platform update FAILED",
                            f"Error: {result.get('message')}. Manual intervention may be required.",
                            is_pre=False,
                        )

            except Exception:
                logger.exception("Auto-update task failed")


    def _task_backup_integration_data(self):
        """Daily: backup all tenant integration data to configured storage provider."""
        if not self._app:
            return
        with self._app.app_context():
            try:
                import json
                from app import db
                from app.models import ConfigStore, Tenant

                tenants = db.session.execute(db.select(Tenant)).scalars().all()
                backed_up = 0
                for tenant in tenants:
                    try:
                        record = ConfigStore.find(f"tenant_integration_data_{tenant.id}")
                        if not record or not record.value:
                            continue
                        # Store backup via storage router
                        try:
                            from app.masri.storage_router import store_file
                            backup_name = f"integration_backup_{tenant.id}_{datetime.utcnow().strftime('%Y%m%d')}.json"
                            store_file(
                                file_data=record.value.encode("utf-8"),
                                file_name=backup_name,
                                folder=f"backups/integration/{tenant.id}",
                                role="backups",
                                tenant_id=tenant.id,
                            )
                            backed_up += 1
                        except Exception:
                            pass
                    except Exception:
                        pass
                if backed_up:
                    logger.info("Integration data backed up for %d tenant(s)", backed_up)
            except Exception:
                logger.exception("Integration data backup failed")

    def _task_model_recommendations(self):
        """Weekly: research and update AI model recommendations for each tier."""
        if not self._app:
            return
        try:
            from app.masri.model_recommender import refresh_model_recommendations
            refresh_model_recommendations(self._app)
        except Exception:
            logger.exception("Model recommendation task failed")

    def _task_integration_refresh(self):
        """Daily refresh: re-pull Telivy + Microsoft data for all mapped tenants."""
        if not self._app:
            return

        with self._app.app_context():
            try:
                import json
                from app import db
                from app.models import ConfigStore

                # 1. Refresh Telivy data for all mapped tenants
                mapping_record = ConfigStore.find("telivy_scan_mappings")
                tenant_scans = {}
                if mapping_record and mapping_record.value:
                    all_mappings = json.loads(mapping_record.value)
                    for item_id, mapping in all_mappings.items():
                        tid = mapping if isinstance(mapping, str) else mapping.get("tenant_id", "") if isinstance(mapping, dict) else ""
                        scan_type = mapping.get("type", "scan") if isinstance(mapping, dict) else "scan"
                        if tid:
                            tenant_scans.setdefault(tid, []).append({"id": item_id, "type": scan_type})

                # Get Telivy client
                api_key = None
                try:
                    result = db.session.execute(
                        db.text("SELECT config_enc FROM settings_storage WHERE provider = 'telivy' LIMIT 1")
                    ).scalar()
                    if result:
                        from app.masri.settings_service import decrypt_value
                        config = json.loads(decrypt_value(result))
                        api_key = config.get("api_key")
                except Exception:
                    pass

                # Get Microsoft client
                ms_client = None
                try:
                    from app.masri.new_models import SettingsEntra
                    entra_cfg = db.session.execute(
                        db.select(SettingsEntra).filter_by(tenant_id=None)
                    ).scalars().first()
                    if entra_cfg and entra_cfg.is_fully_configured():
                        from app.masri.entra_integration import EntraIntegration
                        creds = entra_cfg.get_credentials()
                        ms_client = EntraIntegration(
                            tenant_id=creds["entra_tenant_id"],
                            client_id=creds["client_id"],
                            client_secret=creds["client_secret"],
                        )
                except Exception:
                    pass

                # Get all unique tenant_ids (from mappings + any with cached data)
                all_tenant_ids = set(tenant_scans.keys())
                # Also refresh Microsoft data for tenants with existing cached data
                try:
                    from app.models import Tenant
                    tenants = db.session.execute(db.select(Tenant)).scalars().all()
                    for t in tenants:
                        record = ConfigStore.find(f"tenant_integration_data_{t.id}")
                        if record and record.value and "microsoft" in record.value:
                            all_tenant_ids.add(t.id)
                except Exception:
                    pass

                refreshed = 0
                for tenant_id in all_tenant_ids:
                    try:
                        existing = {}
                        record = ConfigStore.find(f"tenant_integration_data_{tenant_id}")
                        if record and record.value:
                            existing = json.loads(record.value)

                        # Refresh Telivy
                        if api_key and tenant_id in tenant_scans:
                            from app.masri.telivy_integration import TelivyIntegration
                            client = TelivyIntegration(api_key=api_key)
                            telivy_data = {}
                            for scan_info in tenant_scans[tenant_id][:3]:
                                scan_id = scan_info["id"]
                                try:
                                    if scan_info.get("type") == "assessment":
                                        assessment = client.get_risk_assessment(scan_id)
                                        if assessment:
                                            telivy_data["assessment"] = assessment
                                    else:
                                        scan_detail = client.get_external_scan(scan_id)
                                        if scan_detail:
                                            telivy_data["scan"] = scan_detail
                                        findings = client.get_external_scan_findings(scan_id)
                                        if findings:
                                            telivy_data["findings"] = findings[:30] if isinstance(findings, list) else []
                                except Exception:
                                    pass
                            if telivy_data:
                                existing["telivy"] = telivy_data

                        # Refresh Microsoft data (cached, no live calls on page load)
                        if ms_client:
                            try:
                                ms_data = ms_client.collect_all_security_data()
                                if ms_data:
                                    existing["microsoft"] = ms_data
                            except Exception:
                                pass

                        existing["_updated"] = datetime.utcnow().isoformat()
                        ConfigStore.upsert(
                            f"tenant_integration_data_{tenant_id}",
                            json.dumps(existing, default=str)[:35000000],
                        )
                        refreshed += 1
                    except Exception:
                        logger.exception("Integration refresh failed for tenant %s", tenant_id)

                if refreshed:
                    logger.info("Integration data refreshed for %d tenant(s)", refreshed)

            except Exception:
                logger.exception("Integration refresh task failed")


# Module-level singleton
masri_scheduler = MasriScheduler()
