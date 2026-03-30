"""
Masri Digital Compliance Platform — Update Manager

Provides update checking, applying, and scheduling for the platform.
Runs git operations to check for new commits on the remote, and can
apply updates by pulling, installing dependencies, and restarting.

Usage:
    from app.masri.update_manager import UpdateManager
    status = UpdateManager.check()
    result = UpdateManager.apply()
"""

import logging
import subprocess
import os
import json
import time
from datetime import datetime

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class UpdateManager:
    """Handles checking for and applying platform updates."""

    @staticmethod
    def check() -> dict:
        """
        Check if updates are available by fetching from remote.

        Returns:
            dict with keys: available (bool), current_commit, remote_commit,
                            commits_behind (int), changes (list of commit msgs)
        """
        try:
            # Verify git is available and we're in a repo
            git_check = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=_PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if git_check.returncode != 0:
                return {"error": "Not a git repository or git not available", "available": False}

            # Fetch latest from remote without merging
            fetch = subprocess.run(
                ["git", "fetch", "origin", "main"],
                cwd=_PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if fetch.returncode != 0:
                return {"error": f"Git fetch failed: {fetch.stderr.strip()}", "available": False}

            # Get current HEAD
            current = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=_PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()

            # Get remote HEAD
            remote = subprocess.run(
                ["git", "rev-parse", "--short", "origin/main"],
                cwd=_PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()

            # Count commits behind
            behind_output = subprocess.run(
                ["git", "rev-list", "--count", "HEAD..origin/main"],
                cwd=_PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            commits_behind = int(behind_output) if behind_output.isdigit() else 0

            # Get commit messages for pending updates
            changes = []
            if commits_behind > 0:
                log_output = subprocess.run(
                    ["git", "log", "--oneline", "HEAD..origin/main", "--max-count=20"],
                    cwd=_PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10,
                ).stdout.strip()
                if log_output:
                    changes = log_output.split("\n")

            # Get current version from config
            version = "unknown"
            try:
                from flask import current_app
                version = current_app.config.get("VERSION", "unknown")
            except Exception:
                pass

            return {
                "available": commits_behind > 0,
                "current_commit": current,
                "remote_commit": remote,
                "commits_behind": commits_behind,
                "changes": changes,
                "version": version,
                "checked_at": datetime.utcnow().isoformat(),
            }
        except subprocess.TimeoutExpired:
            return {"error": "Update check timed out", "available": False}
        except Exception as e:
            logger.exception("Update check failed")
            return {"error": str(e), "available": False}

    @staticmethod
    def apply() -> dict:
        """
        Apply pending updates: git pull + pip install + signal restart.

        Returns:
            dict with keys: success (bool), message, details
        """
        try:
            # 1. Git pull
            pull_result = subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=_PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if pull_result.returncode != 0:
                return {
                    "success": False,
                    "message": "Git pull failed",
                    "details": pull_result.stderr,
                }

            # 2. Install any new dependencies
            pip_result = subprocess.run(
                ["pip", "install", "-r", "requirements.txt", "--quiet"],
                cwd=_PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=120,
            )

            # 3. Run database migrations
            migrate_result = subprocess.run(
                ["python", "-c", """
import os
from app import create_app, db
from flask_migrate import upgrade
app = create_app(os.getenv('FLASK_CONFIG') or 'default')
with app.app_context():
    upgrade()
"""],
                cwd=_PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=60,
            )

            # 4. Signal Gunicorn to gracefully reload workers
            # This reloads the code without dropping connections
            import signal
            try:
                # Find gunicorn master PID
                pid_result = subprocess.run(
                    ["pgrep", "-f", "gunicorn.*flask_app"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if pid_result.stdout.strip():
                    master_pid = int(pid_result.stdout.strip().split("\n")[0])
                    os.kill(master_pid, signal.SIGHUP)
                    restart_msg = f"Gunicorn reloading (PID {master_pid})"
                else:
                    restart_msg = "No Gunicorn process found — restart manually"
            except Exception as e:
                restart_msg = f"Could not signal restart: {e}"

            # 5. Invalidate all sessions by writing a new update stamp
            try:
                from app.models import ConfigStore
                ConfigStore.upsert("last_update_stamp", str(int(time.time())))
            except Exception:
                pass

            return {
                "success": True,
                "message": "Update applied successfully",
                "git_output": pull_result.stdout[:500],
                "pip_output": "Dependencies updated" if pip_result.returncode == 0 else pip_result.stderr[:300],
                "migration_output": "Migrations applied" if migrate_result.returncode == 0 else migrate_result.stderr[:300],
                "restart": restart_msg,
                "applied_at": datetime.utcnow().isoformat(),
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "Update timed out"}
        except Exception as e:
            logger.exception("Update apply failed")
            return {"success": False, "message": str(e)}

    @staticmethod
    def get_schedule() -> dict:
        """Get the current auto-update schedule from the config store."""
        try:
            from app.models import ConfigStore
            record = ConfigStore.find("auto_update_schedule")
            if record and record.value:
                return json.loads(record.value)
        except Exception:
            pass
        return {"enabled": False, "frequency": "daily", "auto_apply": False}

    @staticmethod
    def set_schedule(enabled: bool, frequency: str = "daily", auto_apply: bool = False) -> dict:
        """
        Set the auto-update schedule.

        Args:
            enabled: Whether auto-checking is on
            frequency: "hourly", "daily", "weekly"
            auto_apply: If True, automatically apply updates (not just check)
        """
        from app.models import ConfigStore
        schedule = {
            "enabled": enabled,
            "frequency": frequency,
            "auto_apply": auto_apply,
            "updated_at": datetime.utcnow().isoformat(),
        }
        ConfigStore.upsert("auto_update_schedule", json.dumps(schedule))
        return schedule
