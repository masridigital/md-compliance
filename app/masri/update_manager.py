"""
Masri Digital Compliance Platform — Update Manager

Provides update checking, applying, and scheduling for the platform.
Runs git operations to check for new commits on the remote. In Docker
deployments, apply() only does git pull — container rebuild is required
to activate changes (no pip install, no migration, no SIGHUP).

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

# Security: only allow these exact commands — no user input ever enters subprocess
_ALLOWED_GIT_COMMANDS = {
    "fetch": ["git", "fetch", "origin", "main"],
    "pull": ["git", "pull", "origin", "main"],
    "status": ["git", "status", "--porcelain"],
    "rev_parse_head": ["git", "rev-parse", "--short", "HEAD"],
    "rev_parse_remote": ["git", "rev-parse", "--short", "origin/main"],
    "rev_list": ["git", "rev-list", "--count", "HEAD..origin/main"],
    "log": ["git", "log", "--oneline", "HEAD..origin/main", "--max-count=20"],
}


def _run_safe(cmd_name: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a pre-approved command only. Prevents command injection."""
    if cmd_name not in _ALLOWED_GIT_COMMANDS:
        raise ValueError(f"Command not allowed: {cmd_name}")
    return subprocess.run(
        _ALLOWED_GIT_COMMANDS[cmd_name],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


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
            git_check = _run_safe("status", timeout=10)
            if git_check.returncode != 0:
                return {"error": "Not a git repository or git not available", "available": False}

            # Fetch latest from remote without merging
            fetch = _run_safe("fetch", timeout=30)
            if fetch.returncode != 0:
                return {"error": "Git fetch failed", "available": False}

            # Get current HEAD
            current = _run_safe("rev_parse_head", timeout=10).stdout.strip()

            # Get remote HEAD
            remote = _run_safe("rev_parse_remote", timeout=10).stdout.strip()

            # Count commits behind
            behind_output = _run_safe("rev_list", timeout=10).stdout.strip()
            commits_behind = int(behind_output) if behind_output.isdigit() else 0

            # Get commit messages for pending updates
            changes = []
            if commits_behind > 0:
                log_output = _run_safe("log", timeout=10).stdout.strip()
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
        Apply pending updates: git pull only (Docker-safe).

        In Docker deployments, pip install / migrations / SIGHUP are
        handled by the container rebuild. This method only pulls code
        and sets a flag so the UI can show a "rebuild required" banner.

        Returns:
            dict with keys: success (bool), message, rebuild_required
        """
        try:
            # 1. Git pull (uses pre-approved command only)
            pull_result = _run_safe("pull", timeout=60)
            if pull_result.returncode != 0:
                return {
                    "success": False,
                    "message": "Git pull failed",
                    "details": pull_result.stderr,
                }

            # 2. Mark update as pending — UI shows "rebuild required" banner
            try:
                from app.models import ConfigStore
                ConfigStore.upsert("update_pending", json.dumps({
                    "pending": True,
                    "pulled_at": datetime.utcnow().isoformat(),
                    "commits": pull_result.stdout[:500],
                }))
            except Exception:
                pass

            logger.info("Update git pull: %s", pull_result.stdout[:300])

            return {
                "success": True,
                "message": "Code updated. Run `docker-compose up -d --build` to apply.",
                "rebuild_required": True,
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
