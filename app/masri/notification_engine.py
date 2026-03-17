"""
Masri Digital Compliance Platform — Notification Engine

Routes notifications to enabled channels (Teams, Email, Slack, SMS, In-App)
based on priority matrix settings. Logs all sends to NotificationLog.
"""

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class NotificationEngine:
    """
    Multi-channel notification dispatcher.

    Usage:
        engine = NotificationEngine()
        results = engine.send(
            event_type="control_overdue",
            tenant_id="abc123",
            data={"control_name": "MFA", "due_date": "2026-01-15", ...},
            priority="high"
        )
    """

    def send(self, event_type: str, tenant_id: str, data: dict,
             priority: str = "medium") -> list:
        """
        Route notification to all enabled channels for this priority level.

        Args:
            event_type: e.g. control_overdue, control_due_soon, wisp_review_due,
                        framework_milestone, security_alert, evidence_uploaded
            tenant_id: scope to a tenant
            data: event-specific payload
            priority: critical / high / medium / low

        Returns:
            list of {channel, status, error} dicts
        """
        channels = self._get_enabled_channels(tenant_id, priority)
        results = []

        for channel_record in channels:
            channel = channel_record.channel
            config = channel_record.get_config()
            status = "sent"
            error = None

            try:
                if channel == "teams_webhook":
                    webhook_url = config.get("webhook_url")
                    if not webhook_url:
                        raise ValueError("Teams webhook URL not configured")
                    card = self.build_teams_card(event_type, data)
                    success = self.send_teams(webhook_url, card)
                    if not success:
                        status = "failed"
                        error = "Teams webhook returned non-200"

                elif channel == "email":
                    recipients = data.get("recipients", [])
                    if not recipients:
                        # Fall back to tenant contact or assigned user
                        if data.get("assigned_user_email"):
                            recipients = [data["assigned_user_email"]]
                    if recipients:
                        subject = self._build_email_subject(event_type, data)
                        html_body = self._build_email_body(event_type, data)
                        success = self.send_email(recipients, subject, html_body)
                        if not success:
                            status = "failed"
                            error = "Email send failed"
                    else:
                        status = "failed"
                        error = "No recipients for email"

                elif channel == "slack_webhook":
                    webhook_url = config.get("webhook_url")
                    if not webhook_url:
                        raise ValueError("Slack webhook URL not configured")
                    success = self.send_slack(webhook_url, event_type, data)
                    if not success:
                        status = "failed"
                        error = "Slack webhook failed"

                elif channel == "sms":
                    phone = data.get("phone") or config.get("default_phone")
                    if phone:
                        success = self.send_sms(config, phone, event_type, data)
                        if not success:
                            status = "failed"
                            error = "SMS send failed"
                    else:
                        status = "failed"
                        error = "No phone number for SMS"

                elif channel == "in_app":
                    # In-app notifications are written as NotificationLog
                    # records; the frontend polls for them.
                    pass

            except Exception as e:
                status = "failed"
                error = str(e)
                logger.exception(f"Notification send failed: channel={channel}, event={event_type}")

            self._log(channel, event_type, tenant_id,
                      {"data": data, "priority": priority}, status, error)
            results.append({"channel": channel, "status": status, "error": error})

        return results

    # ----- Channel senders -----

    def send_teams(self, webhook_url: str, card: dict) -> bool:
        """POST Adaptive Card JSON to Teams webhook. Returns success bool."""
        import requests
        payload = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }]
        }
        try:
            resp = requests.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            return resp.status_code in (200, 202)
        except Exception as e:
            logger.error(f"Teams webhook error: {e}")
            return False

    def send_email(self, recipients: list, subject: str,
                   html_body: str, text_body: str = None) -> bool:
        """Send via Flask-Mail. Returns success bool."""
        try:
            from flask import current_app
            from app import mail
            from flask_mail import Message

            if not current_app.is_email_configured:
                logger.warning("Email not configured, skipping send")
                return False

            msg = Message(
                subject=subject,
                recipients=recipients,
                html=html_body,
                body=text_body or subject,
                sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
            )
            mail.send(msg)
            return True
        except Exception as e:
            logger.error(f"Email send error: {e}")
            return False

    def send_slack(self, webhook_url: str, event_type: str, data: dict) -> bool:
        """POST a formatted message to a Slack Incoming Webhook."""
        import requests
        text = self._build_slack_text(event_type, data)
        try:
            resp = requests.post(
                webhook_url,
                json={"text": text},
                timeout=15,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Slack webhook error: {e}")
            return False

    def send_sms(self, config: dict, phone: str,
                 event_type: str, data: dict) -> bool:
        """Send SMS via Twilio."""
        try:
            from twilio.rest import Client
        except ImportError:
            logger.error("twilio package not installed")
            return False

        try:
            client = Client(config["account_sid"], config["auth_token"])
            body = self._build_sms_text(event_type, data)
            client.messages.create(
                body=body,
                from_=config["from_number"],
                to=phone,
            )
            return True
        except Exception as e:
            logger.error(f"SMS send error: {e}")
            return False

    # ----- Teams Adaptive Card Builder -----

    def build_teams_card(self, event_type: str, data: dict) -> dict:
        """
        Build a Microsoft Teams Adaptive Card v1.4 JSON payload.

        Supported event_types:
        - control_overdue
        - control_due_soon
        - wisp_review_due
        - framework_milestone
        - security_alert
        - evidence_uploaded
        """
        builders = {
            "control_overdue": self._card_control_overdue,
            "control_due_soon": self._card_control_due_soon,
            "wisp_review_due": self._card_wisp_review_due,
            "framework_milestone": self._card_framework_milestone,
            "security_alert": self._card_security_alert,
            "evidence_uploaded": self._card_evidence_uploaded,
        }

        builder = builders.get(event_type, self._card_generic)
        return builder(data)

    def _card_base(self, header_text: str, header_color: str,
                   facts: list, actions: list = None) -> dict:
        """Create base Adaptive Card structure."""
        body = [
            {
                "type": "TextBlock",
                "text": header_text,
                "weight": "Bolder",
                "size": "Medium",
                "color": header_color,
                "wrap": True,
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": k, "value": str(v)} for k, v in facts
                ],
            },
        ]

        card = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": body,
        }

        if actions:
            card["actions"] = actions

        return card

    def _card_control_overdue(self, data: dict) -> dict:
        tenant = data.get("tenant_name", "Unknown")
        return self._card_base(
            header_text=f"\U0001f534 Control Past Due \u2014 {tenant}",
            header_color="Attention",
            facts=[
                ("Control", data.get("control_name", "")),
                ("Framework", data.get("framework_name", "")),
                ("Due Date", data.get("due_date", "")),
                ("Days Overdue", str(data.get("days_overdue", 0))),
                ("Assigned To", data.get("assigned_user", "Unassigned")),
            ],
            actions=[
                {
                    "type": "Action.OpenUrl",
                    "title": "View Control",
                    "url": data.get("control_url", "#"),
                },
            ],
        )

    def _card_control_due_soon(self, data: dict) -> dict:
        days = data.get("days_until_due", "?")
        tenant = data.get("tenant_name", "Unknown")
        return self._card_base(
            header_text=f"\U0001f7e1 Control Due in {days} Days \u2014 {tenant}",
            header_color="Warning",
            facts=[
                ("Control", data.get("control_name", "")),
                ("Framework", data.get("framework_name", "")),
                ("Due Date", data.get("due_date", "")),
                ("Assigned To", data.get("assigned_user", "Unassigned")),
            ],
            actions=[
                {
                    "type": "Action.OpenUrl",
                    "title": "View Control",
                    "url": data.get("control_url", "#"),
                },
            ],
        )

    def _card_wisp_review_due(self, data: dict) -> dict:
        days = data.get("days_until_due", "?")
        return self._card_base(
            header_text=f"\U0001f7e1 WISP Annual Review Due in {days} Days",
            header_color="Warning",
            facts=[
                ("Client", data.get("tenant_name", "")),
                ("WISP Version", str(data.get("wisp_version", ""))),
                ("Last Reviewed", data.get("last_reviewed", "Never")),
                ("Due Date", data.get("due_date", "")),
            ],
            actions=[
                {
                    "type": "Action.OpenUrl",
                    "title": "Open WISP",
                    "url": data.get("wisp_url", "#"),
                },
            ],
        )

    def _card_framework_milestone(self, data: dict) -> dict:
        framework = data.get("framework_name", "")
        pct = data.get("completion_pct", 0)
        return self._card_base(
            header_text=f"\U0001f7e2 Compliance Milestone \u2014 {framework} {pct}% Complete",
            header_color="Good",
            facts=[
                ("Tenant", data.get("tenant_name", "")),
                ("Framework", framework),
                ("Controls Complete", str(data.get("controls_complete", 0))),
                ("Date", data.get("date", str(datetime.utcnow().date()))),
            ],
            actions=[
                {
                    "type": "Action.OpenUrl",
                    "title": "View Framework",
                    "url": data.get("framework_url", "#"),
                },
            ],
        )

    def _card_security_alert(self, data: dict) -> dict:
        tenant = data.get("tenant_name", "Unknown")
        return self._card_base(
            header_text=f"\U0001f6a8 Security Alert \u2014 {tenant}",
            header_color="Attention",
            facts=[
                ("Alert Type", data.get("alert_type", "")),
                ("Description", data.get("description", "")),
                ("User", data.get("user", "")),
                ("IP Address", data.get("ip_address", "")),
                ("Timestamp", data.get("timestamp", str(datetime.utcnow()))),
            ],
            actions=[
                {
                    "type": "Action.OpenUrl",
                    "title": "View Logs",
                    "url": data.get("logs_url", "#"),
                },
            ],
        )

    def _card_evidence_uploaded(self, data: dict) -> dict:
        control = data.get("control_name", "")
        return self._card_base(
            header_text=f"\U0001f4ce Evidence Uploaded \u2014 {control}",
            header_color="Default",
            facts=[
                ("Tenant", data.get("tenant_name", "")),
                ("Control", control),
                ("Uploaded By", data.get("uploaded_by", "")),
                ("File Name", data.get("file_name", "")),
                ("Date", data.get("date", str(datetime.utcnow().date()))),
            ],
            actions=[
                {
                    "type": "Action.OpenUrl",
                    "title": "Review Evidence",
                    "url": data.get("evidence_url", "#"),
                },
            ],
        )

    def _card_generic(self, data: dict) -> dict:
        facts = [(k, str(v)) for k, v in data.items() if k != "event_type"]
        return self._card_base(
            header_text="Notification",
            header_color="Default",
            facts=facts,
        )

    # ----- Scheduled reminder check -----

    def check_and_send_due_reminders(self, tenant_id: str = None):
        """
        Called by scheduled job. For each DueDate with status=pending:
        - 30 days out: send if remind_30d
        - 7 days out: send if remind_7d
        - 1 day out: send if remind_1d
        - Due today: send if remind_on_due
        - Past due: send if remind_when_overdue (once per day max)

        Also sets DueDate.status to 'overdue' for past-due items.
        """
        from app.masri.settings_service import SettingsService
        from app.masri.new_models import DueDate
        from app import db

        query = DueDate.query.filter(DueDate.status.in_(["pending", "overdue"]))
        if tenant_id:
            query = query.filter_by(tenant_id=tenant_id)

        now = datetime.utcnow()

        for dd in query.all():
            days = dd.days_until_due()

            event_type = None
            priority = "medium"

            if days < 0:
                # Past due
                if dd.status != "overdue":
                    dd.status = "overdue"
                if dd.remind_when_overdue:
                    event_type = "control_overdue"
                    priority = "critical"
            elif days == 0:
                if dd.remind_on_due:
                    event_type = "control_due_soon"
                    priority = "high"
            elif days <= 1:
                if dd.remind_1d:
                    event_type = "control_due_soon"
                    priority = "high"
            elif days <= 7:
                if dd.remind_7d:
                    event_type = "control_due_soon"
                    priority = "medium"
            elif 28 <= days <= 32:
                if dd.remind_30d:
                    event_type = "control_due_soon"
                    priority = "low"

            if event_type:
                self.send(
                    event_type=event_type,
                    tenant_id=dd.tenant_id,
                    data={
                        "entity_type": dd.entity_type,
                        "entity_id": dd.entity_id,
                        "due_date": str(dd.due_date.date()),
                        "days_until_due": days,
                        "days_overdue": abs(days) if days < 0 else 0,
                    },
                    priority=priority,
                )

        db.session.commit()

    # ----- Internal helpers -----

    def _get_enabled_channels(self, tenant_id: str, priority: str) -> list:
        """
        Query SettingsNotifications for channels enabled at this priority.
        Checks both platform-level (tenant_id=NULL) and tenant-specific records.
        """
        from app.masri.new_models import SettingsNotifications

        priority_field = f"{priority}_enabled"
        query = SettingsNotifications.query.filter_by(enabled=True).filter(
            (SettingsNotifications.tenant_id == tenant_id) |
            (SettingsNotifications.tenant_id.is_(None))
        )

        results = []
        for record in query.all():
            if getattr(record, priority_field, False):
                results.append(record)
        return results

    def _log(self, channel: str, event_type: str, tenant_id: str,
             payload: dict, status: str, error: str = None):
        """Write a NotificationLog record."""
        from app import db
        from app.masri.new_models import NotificationLog

        log = NotificationLog(
            channel=channel,
            event_type=event_type,
            tenant_id=tenant_id,
            payload_json=json.dumps(payload, default=str),
            status=status,
            error_message=error,
        )
        db.session.add(log)
        db.session.commit()

    def _build_email_subject(self, event_type: str, data: dict) -> str:
        subjects = {
            "control_overdue": f"[Action Required] Control Past Due: {data.get('control_name', '')}",
            "control_due_soon": f"Reminder: Control Due Soon — {data.get('control_name', '')}",
            "wisp_review_due": f"WISP Annual Review Due — {data.get('tenant_name', '')}",
            "framework_milestone": f"Milestone: {data.get('framework_name', '')} {data.get('completion_pct', '')}%",
            "security_alert": f"Security Alert — {data.get('alert_type', '')}",
            "evidence_uploaded": f"Evidence Uploaded: {data.get('file_name', '')}",
        }
        return subjects.get(event_type, f"Notification: {event_type}")

    def _build_email_body(self, event_type: str, data: dict) -> str:
        """Simple HTML email body."""
        items = "".join(
            f"<tr><td style='padding:4px 8px;font-weight:600'>{k}</td>"
            f"<td style='padding:4px 8px'>{v}</td></tr>"
            for k, v in data.items()
            if k not in ("recipients", "phone")
        )
        return f"""
        <div style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto">
            <h2 style="color:#1D1D1F">{event_type.replace('_', ' ').title()}</h2>
            <table style="width:100%;border-collapse:collapse">{items}</table>
            <hr style="border:none;border-top:1px solid #EBEBED;margin:24px 0">
            <p style="color:#6E6E73;font-size:13px">
                Sent by Masri Digital Compliance Platform
            </p>
        </div>
        """

    def _build_slack_text(self, event_type: str, data: dict) -> str:
        title = event_type.replace("_", " ").title()
        lines = [f"*{title}*"]
        for k, v in data.items():
            if k not in ("recipients", "phone"):
                lines.append(f"• {k}: {v}")
        return "\n".join(lines)

    def _build_sms_text(self, event_type: str, data: dict) -> str:
        title = event_type.replace("_", " ").title()
        return f"[Masri Comply] {title}: {data.get('control_name', data.get('tenant_name', ''))}"
