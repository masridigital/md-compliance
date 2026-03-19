"""
Masri Digital Compliance Platform — Notification API Routes

Exposes notification management and testing endpoints:
  - POST /api/v1/notifications/test-teams    — Send test Teams notification
  - POST /api/v1/notifications/test-email    — Send test email notification
  - POST /api/v1/notifications/send          — Send arbitrary notification
  - GET  /api/v1/notifications/logs          — Retrieve notification logs
  - POST /api/v1/notifications/check-reminders — Trigger due-date reminder check

Blueprint: ``notification_bp`` at url_prefix ``/api/v1/notifications``
"""

import logging

from flask import Blueprint, jsonify, request, abort
from flask_login import current_user
from app.utils.decorators import login_required
from app import limiter
from app.masri.schemas import (
    validate_payload,
    TestTeamsSchema,
    TestEmailSchema,
    SendNotificationSchema,
    CheckRemindersSchema,
)

logger = logging.getLogger(__name__)

notification_bp = Blueprint(
    "notification_bp", __name__, url_prefix="/api/v1/notifications"
)


@notification_bp.route("/test-teams", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def test_teams():
    """
    POST /api/v1/notifications/test-teams

    Request body:
        { "tenant_id": <str>, "webhook_url": <str, optional> }

    Sends a test Microsoft Teams adaptive card notification.
    """
    data, err = validate_payload(TestTeamsSchema, request.get_json(silent=True))
    if err:
        return err
    tenant_id = data.get("tenant_id")
    webhook_url = data.get("webhook_url")

    try:
        from app.masri.notification_engine import NotificationEngine

        engine = NotificationEngine(tenant_id)
        result = engine.send_teams(
            card_type="test",
            title="Test Notification",
            body="This is a test notification from Masri Digital Compliance Platform.",
            webhook_url_override=webhook_url,
        )
        return jsonify({"success": True, "result": result})
    except Exception as e:
        logger.exception("Test Teams notification failed")
        return jsonify({"error": str(e)}), 500


@notification_bp.route("/test-email", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def test_email():
    """
    POST /api/v1/notifications/test-email

    Request body:
        { "tenant_id": <str>, "recipient": <str> }

    Sends a test email notification.
    """
    data, err = validate_payload(TestEmailSchema, request.get_json(silent=True))
    if err:
        return err
    tenant_id = data.get("tenant_id")
    recipient = data.get("recipient")

    try:
        from app.masri.notification_engine import NotificationEngine

        engine = NotificationEngine(tenant_id)
        result = engine.send_email(
            to=recipient,
            subject="Test Notification — Masri Digital",
            body="This is a test email from Masri Digital Compliance Platform.",
        )
        return jsonify({"success": True, "result": result})
    except Exception as e:
        logger.exception("Test email notification failed")
        return jsonify({"error": str(e)}), 500


@notification_bp.route("/send", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def send_notification():
    """
    POST /api/v1/notifications/send

    Request body:
        {
            "tenant_id": <str>,
            "channel": "teams" | "email" | "slack" | "sms",
            "subject": <str>,
            "body": <str>,
            "recipient": <str, required for email/sms>,
            "card_type": <str, optional, for teams>
        }

    Sends a notification through the specified channel.
    """
    data, err = validate_payload(SendNotificationSchema, request.get_json(silent=True))
    if err:
        return err
    tenant_id = data.get("tenant_id")
    channel = data.get("channel", "")
    subject = data.get("subject", "Notification")
    body = data.get("body", "")
    recipient = data.get("recipient")
    card_type = data.get("card_type", "general")

    try:
        from app.masri.notification_engine import NotificationEngine

        engine = NotificationEngine(tenant_id)

        if channel == "teams":
            result = engine.send_teams(
                card_type=card_type,
                title=subject,
                body=body,
            )
        elif channel == "email":
            if not recipient:
                return jsonify({"error": "recipient is required for email"}), 400
            result = engine.send_email(
                to=recipient,
                subject=subject,
                body=body,
            )
        elif channel == "slack":
            result = engine.send_slack(
                message=f"*{subject}*\n{body}",
            )
        elif channel == "sms":
            if not recipient:
                return jsonify({"error": "recipient is required for sms"}), 400
            result = engine.send_sms(
                to=recipient,
                message=f"{subject}: {body}",
            )

        return jsonify({"success": True, "channel": channel, "result": result})
    except Exception as e:
        logger.exception("Send notification failed for channel %s", channel)
        return jsonify({"error": str(e)}), 500


@notification_bp.route("/logs", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def notification_logs():
    """
    GET /api/v1/notifications/logs?tenant_id=<id>&limit=50&offset=0

    Returns notification log entries for the tenant.
    """
    tenant_id = request.args.get("tenant_id")
    if not tenant_id:
        return jsonify({"error": "tenant_id query parameter is required"}), 400

    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    try:
        from app.masri.new_models import NotificationLog

        query = (
            NotificationLog.query
            .filter_by(tenant_id=tenant_id)
            .order_by(NotificationLog.date_created.desc())
            .offset(offset)
            .limit(limit)
        )
        logs = query.all()

        return jsonify({
            "tenant_id": tenant_id,
            "logs": [log.as_dict() for log in logs],
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        logger.exception("Notification logs fetch failed")
        return jsonify({"error": "Failed to retrieve logs"}), 500


@notification_bp.route("/check-reminders", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def check_reminders():
    """
    POST /api/v1/notifications/check-reminders

    Request body:
        { "tenant_id": <str> }

    Manually triggers a due-date reminder check for the tenant.
    """
    data, err = validate_payload(CheckRemindersSchema, request.get_json(silent=True))
    if err:
        return err
    tenant_id = data.get("tenant_id")

    try:
        from app.masri.notification_engine import NotificationEngine

        engine = NotificationEngine(tenant_id)
        sent_count = engine.check_and_send_due_reminders()

        return jsonify({
            "success": True,
            "tenant_id": tenant_id,
            "reminders_sent": sent_count,
        })
    except Exception as e:
        logger.exception("Reminder check failed for tenant %s", tenant_id)
        return jsonify({"error": str(e)}), 500
