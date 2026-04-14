"""app.models.assessment — Assessment domain models."""

from app import db
from app.utils.mixin_models import QueryMixin, DateMixin
from app.masri.settings_service import EncryptedText
from flask import current_app, abort
from sqlalchemy import func
from sqlalchemy.orm import validates
from datetime import datetime
from string import Formatter
from random import randrange
from typing import List
import shortuuid
import secrets
import json
import arrow


class Form(db.Model, QueryMixin):
    __tablename__ = "forms"
    __table_args__ = (db.UniqueConstraint("name", "tenant_id"),)
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String())
    sections = db.relationship(
        "FormSection",
        backref="form",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    assessment_id = db.Column(db.String)
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}

        # If not attached to an assessment, it's a template
        data["is_template"] = True
        if self.assessment_id:
            data["is_template"] = False

        data["sections"] = []
        for section in self.sections.all():
            data["sections"].append(section.as_dict())

        if assessment := db.session.execute(db.select(Assessment).filter(Assessment.form_id == self.id)).scalars().first():
            data["assessment_name"] = assessment.name
            data["assessment_id"] = assessment.id
        return data

    def get_section(self, title):
        return self.sections.filter(
            func.lower(FormSection.title) == func.lower(title)
        ).first()

    def get_section_by_id(self, id):
        return self.sections.filter(func.lower(FormSection.id) == id).first()

    def get_items(self, edit_mode=None, flatten=False):
        """
        edit_mode: return all items, even disabled ones
        flatten: return only the items, otherwise return the items as a list in the section
        """
        items = []
        for section in self.sections.all():
            section_data = section.as_dict(edit_mode=edit_mode)
            if edit_mode or section_data["questions"]:
                if flatten:
                    for record in section_data.get("items"):
                        items.append(record)
                else:
                    items.append(section_data)
        return items

    def create_section(self, title, order=1):
        if not order:
            if latest_item := self.sections.order_by(FormSection.order.desc()).first():
                order = latest_item.order
            else:
                order = 1
        section = FormSection(title=title, order=order)
        self.sections.append(section)
        db.session.commit()
        return section



class AssessmentGuest(db.Model):
    __tablename__ = "assessment_guests"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    assessment_id = db.Column(
        db.String, db.ForeignKey("assessments.id"), nullable=False
    )
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)



class FormItemMessage(db.Model, QueryMixin):
    __tablename__ = "form_item_messages"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    text = db.Column(db.String(), nullable=False)
    owner_id = db.Column(db.String(), db.ForeignKey("users.id"))
    is_vendor = db.Column(db.Boolean, default=False)
    item_id = db.Column(db.String, db.ForeignKey("form_items.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["author"] = db.session.get(User, self.owner_id).email
        return data



class FormItem(db.Model, QueryMixin, DateMixin):
    __tablename__ = "form_items"
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    review_status = db.Column(db.String(), nullable=False, default="info_required")
    data_type = db.Column(db.String(), nullable=False, default="text")
    order = db.Column(db.Integer, nullable=False)
    editable = db.Column(db.Boolean, default=True)
    disabled = db.Column(db.Boolean, default=True)
    applicable = db.Column(db.Boolean, default=True)
    score = db.Column(db.Integer, default=1)
    critical = db.Column(db.Boolean, default=False)
    attributes = db.Column(db.JSON(), default={})
    messages = db.relationship(
        "FormItemMessage",
        backref="item",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    response = db.Column(db.String)

    # TODO - Not implemented... see app.utils.misc.apply_rule
    rule = db.Column(db.JSON(), default={})
    rule_action = db.Column(db.String)

    # Used when status == 'info_required'
    info_required = db.Column(db.String)
    additional_response = db.Column(db.String)  # provided by vendor

    # Used when status == 'remediation_required'
    remediation_gap = db.Column(db.String)
    remediation_due_date = db.Column(db.DateTime)
    remediation_risk = db.Column(db.String, default="unknown")
    remediation_vendor_plan = db.Column(db.String)  # provided by vendor
    remediation_vendor_agreed = db.Column(db.Boolean)  # provided by vendor
    remediation_complete = db.Column(db.Boolean, default=False)
    remediation_complete_from_vendor = db.Column(db.Boolean, default=False)
    remediation_plan_required = db.Column(db.Boolean, default=False)
    # remediation_required_before_approval = db.Column(db.Boolean, default=False)

    # Used when status == 'complete'
    complete_notes = db.Column(db.String)

    responder_id = db.Column(db.String(), db.ForeignKey("users.id"))
    section_id = db.Column(db.String, db.ForeignKey("form_sections.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_REVIEW_STATUS = [
        "pending",
        "info_required",
        "complete",
    ]
    VALID_REMEDIATION_RISK = ["unknown", "low", "moderate", "high"]

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["section"] = self.section.title
        messages = self.messages.all()
        data["messages"] = [message.as_dict() for message in messages]
        status = self.get_status()
        data["status"] = status
        data["get_review_description"] = self.get_review_description()
        data["vendor_answered"] = False
        if status == "answered":
            data["vendor_answered"] = True

        data["has_messages"] = False
        if len(data["messages"]) > 0:
            data["has_messages"] = True
        data["remediation_plan_complete"] = self.has_vendor_completed_remediation_plan()
        if self.remediation_due_date:
            data["remediation_due_date"] = self.simple_date(self.remediation_due_date)
        data["remediation_status"] = self.get_remediation_status()

        data["days_until_remediation_due_date"] = self.days_until_remediation_due_date()
        data["remediation_past_due"] = False
        data["remediation_due_date_upcoming"] = False

        if self.remediation_plan_required:
            if data["days_until_remediation_due_date"] <= 0:
                data["remediation_past_due"] = True
            if data["days_until_remediation_due_date"] <= 14:
                data["remediation_due_date_upcoming"] = True

        return data

    def days_until_remediation_due_date(self, humanize=False):
        if not self.remediation_due_date:
            return 0
        due_date = arrow.get(self.remediation_due_date).format("YYYY-MM-DD")
        if humanize:
            return arrow.get(due_date).humanize(granularity=["day"])
        return (arrow.get(due_date).date() - arrow.utcnow().date()).days

    def update_review_status(self, status):
        if status not in self.VALID_REVIEW_STATUS:
            abort(422, f"Invalid status: {status}")

        if status == self.review_status:
            abort(422, f"Status is already set to: {status}")

    def has_vendor_completed_remediation_plan(self):
        """
        Checks whether the vendor has filled out AND agreed to the remediation plan
        """
        if self.remediation_vendor_agreed and self.remediation_vendor_plan:
            return True

        return False

    def get_review_description(self):
        mapping = {
            "pending": "Waiting on completion from respondent",
            "info_required": "Requires more information from respondent",
            "remediation_required": "Requires remediation from the vendor",
            "complete": "Completed",
        }
        if self.remediation_plan_required:
            mapping["info_required"] = (
                "Requires more information (remediation plan) from respondent"
            )

        return mapping.get(self.review_status)

    def get_remediation_status(self):
        if self.remediation_plan_required is False:
            return "Remediation is not required"

        if self.remediation_vendor_agreed is None:
            return "Vendor has not responded"

        if self.remediation_vendor_agreed is False:
            return "Vendor has disagreed"

        if self.remediation_complete:
            return "Remediation is complete"

        if self.remediation_complete_from_vendor is False:
            return "Vendor has not completed the remediation"

        if self.remediation_complete_from_vendor is True:
            return "Vendor has completed the remediation however the InfoSec team has not responded."

        return "Unknown status"

    def create_message(self, text, owner, is_vendor=False):
        if not text:
            abort(422, "Text is required")

        if owner.has_role_for_tenant(self.section.form.tenant, "vendor"):
            is_vendor = True

        message = FormItemMessage(text=text, owner_id=owner.id, is_vendor=is_vendor)
        self.messages.append(message)
        db.session.commit()
        return message

    def get_status(self):
        if self.disabled:
            return "disabled"
        # if self.satisfied:
        #     return "satisfied"
        if not self.applicable:
            return "not applicable"
        if not self.response:
            return "unanswered"
        if self.response:
            return "answered"
        return "unknown"

    @validates("review_status")
    def _validate_review_status(self, key, value):
        if value not in self.VALID_REVIEW_STATUS:
            raise ValueError(f"Invalid review status: {value}")
        return value

    @validates("remediation_risk")
    def _validate_remediation_risk(self, key, value):
        if value not in self.VALID_REMEDIATION_RISK:
            raise ValueError(f"Invalid risk value: {value}")
        return value

    @validates("remediation_vendor_agreed")
    def _validate_remediation_vendor_agreed(self, key, value):
        if value is True and not self.remediation_vendor_plan:
            abort(422, "Remediation plan must be completed")
        return value

    @staticmethod
    def default_attributes():
        return {
            "placeholder": "Please complete",
            "label": "Please insert your question here",
            "required": True,
        }

    def update(
        self, section=None, attributes={}, disabled=None, critical=None, score=None
    ):
        # set attributes
        if attributes:
            if not isinstance(attributes, dict):
                abort(422)
            default_attributes = FormItem.default_attributes()
            attributes.update(
                {
                    key: value
                    for key, value in default_attributes.items()
                    if key not in attributes
                }
            )
            self.attributes = attributes

        if section:
            if found_section := self.section.form.get_section(section):
                self.section_id = found_section.id
        if disabled is not None:
            self.disabled = disabled
        if critical is not None:
            self.critical = critical
        if score is not None:
            self.score = int(score)
        db.session.commit()
        return self



class FormSection(db.Model, QueryMixin):
    __tablename__ = "form_sections"
    __table_args__ = (db.UniqueConstraint("title", "form_id"),)

    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    title = db.Column(db.String(), nullable=False, default="general")
    status = db.Column(db.String(), nullable=False, default="not_started")
    order = db.Column(db.Integer, nullable=False)
    items = db.relationship(
        "FormItem",
        backref="section",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    form_id = db.Column(db.String, db.ForeignKey("forms.id"), nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def as_dict(self, edit_mode=True):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["disabled"] = 0
        data["responses"] = 0
        items = []
        for item in self.items.all():
            if not edit_mode and item.disabled:
                continue
            if item.disabled:
                data["disabled"] += 1
            if item.response:
                data["responses"] += 1
            items.append(item.as_dict())
        data["questions"] = len(items)
        data["items"] = items
        return data

    @validates("title")
    def _validate_title(self, key, title):
        if not title:
            raise ValueError("Invalid title")
        return title.lower()

    def update(self, title):
        if not title:
            abort(422, "Title is required")
        if self.title.lower() == "general":
            abort(422, "The 'general' section must not be updated")
        if self.form.get_section(title):
            abort(422, f"Title already exists:{title}")
        self.title = title.lower()
        db.session.commit()
        return self

    def create_item(self, **kwargs):
        data_type = kwargs.get("data_type")
        if data_type not in ["text", "select", "file_input", "checkbox"]:
            abort(422)

        order = kwargs.get("order")
        if not order:
            if latest_item := self.items.order_by(FormItem.order.desc()).first():
                order = latest_item.order
            else:
                order = 1
        kwargs["order"] = order
        item = FormItem(**kwargs)
        if not kwargs.get("attributes"):
            item.attributes = FormItem.default_attributes()
        self.items.append(item)
        db.session.commit()
        return item



class Assessment(db.Model, QueryMixin):
    __tablename__ = "assessments"
    __table_args__ = (db.UniqueConstraint("name", "vendor_id"),)
    id = db.Column(
        db.String,
        primary_key=True,
        default=lambda: str(shortuuid.ShortUUID().random(length=8)).lower(),
        unique=True,
    )
    name = db.Column(db.String(), nullable=False)
    description = db.Column(db.String())
    review_status = db.Column(db.String(), default="new")
    status = db.Column(db.String(), default="pending")
    disabled = db.Column(db.Boolean(), default=False)
    notes = db.Column(db.String())
    guests = db.relationship(
        "AssessmentGuest",
        backref="assessment",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    form_id = db.Column(db.String, db.ForeignKey("forms.id"), nullable=True)
    reviewer_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=True)
    vendor_id = db.Column(db.String, db.ForeignKey("vendors.id"), nullable=True)
    owner_id = db.Column(db.String(), db.ForeignKey("users.id"), nullable=False)
    tenant_id = db.Column(db.String, db.ForeignKey("tenants.id"), nullable=False)
    due_before = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    date_updated = db.Column(db.DateTime, onupdate=datetime.utcnow)

    VALID_REVIEW_STATUS = [
        "new",
        "pending_response",
        "pending_review",
        "complete",
    ]
    VALID_STATUS = ["pending", "approved", "not approved"]

    def as_dict(self):
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        data["guests"] = self.get_available_guests()
        if self.vendor_id:
            data["vendor"] = self.vendor.name
        data["owner"] = db.session.get(User, self.owner_id).email
        data["is_review_complete"] = self.is_review_complete()
        data["is_complete"] = self.is_complete()

        data["due_date_humanize"] = self.days_until_due_date(humanize=True)
        days_until_due_date = self.days_until_due_date()
        data["days_until_due_date"] = days_until_due_date
        data["due_date_upcoming"] = False
        data["past_due"] = False
        data["due_date"] = arrow.get(self.due_before).format("YYYY-MM-DD")
        if days_until_due_date <= 14 and not data["is_review_complete"]:
            data["due_date_upcoming"] = True
        if days_until_due_date <= 0 and not data["is_review_complete"]:
            data["past_due"] = True

        data["assessment_published"] = self.is_assessment_published()
        data["review_description"] = self.get_review_description()
        data["is_vendor_status"] = self.is_vendor_status()

        items = self.get_items(flatten=True)
        (
            total_items,
            total_vendor_answered,
            vendor_answered_percentage,
        ) = self.get_vendor_answered_percentage(items=items)
        data["total_items"] = total_items
        data["total_vendor_answered"] = total_vendor_answered
        data["vendor_answered_percentage"] = vendor_answered_percentage

        data["question_statuses"] = self.get_grouping_for_question_review_status(
            items=items
        )
        data["infosec_review_percentage"] = self.get_question_review_percentage(
            items=items
        )
        data["vendor_review_percentage"] = (
            self.get_question_review_percentage_for_vendor(items=items)
        )
        data["all_questions_complete"] = False
        if data["question_statuses"]["complete"] == total_items:
            data["all_questions_complete"] = True

        return data

    def update_review_status(self, status, send_notification=False, override=False):
        if status not in self.VALID_REVIEW_STATUS:
            abort(422, f"Invalid status: {status}")

        if self.review_status != "new" and status == "new":
            abort(422, "Assessment can not be reset to New")

        if override is False:
            if self.review_status == "pending_response" and status == "pending_review":
                can_change, can_change_response = self.can_vendor_submit_for_review()
                if not can_change:
                    abort(422, can_change_response)

            if self.review_status == "pending_review" and status == "pending_response":
                (
                    can_infosec_change,
                    can_infosec_change_response,
                ) = self.can_infosec_submit_for_response()
                if not can_infosec_change:
                    abort(422, can_infosec_change_response)

        self.review_status = status
        db.session.commit()

        if send_notification:
            self.send_status_update_to_vendor(status=status)
        return True

    def can_infosec_submit_for_response(self):
        if self.get_question_review_percentage() != 100:
            return (False, "InfoSec has not reviewed all of the questions")
        return (True, "InfoSec can submit for response")

    def can_vendor_submit_for_review(self):
        items = self.get_items(flatten=True)
        _total, _answered, _pct = self.get_vendor_answered_percentage(items=items)
        if _pct < 100:
            return (False, "Vendor has incomplete questions")

        incomplete_info_required = 0
        incomplete_remediation_plans = 0
        for item in items:
            if (
                item.get("review_status") == "info_required"
                and item.get("additional_response") is None
            ):
                incomplete_info_required += 1

            if item.get("review_status") == "info_required" and not item.get(
                "remediation_plan_complete"
            ):
                incomplete_remediation_plans += 1

        if incomplete_info_required:
            return (
                False,
                f"Vendor has not provided additional information for {incomplete_info_required} questions",
            )

        if incomplete_remediation_plans:
            return (
                False,
                f"Vendor has not provided remediation plans for {incomplete_remediation_plans} questions",
            )

        return (True, "Vendor can submit for review")

    def get_vendor_answered_percentage(self, items=[]):
        """
        Returns total, total_answered, total_percentage
        """
        if not items:
            items = self.get_items(flatten=True)

        total_items = 0
        total_vendor_answered = 0

        for item in items:
            total_items += 1
            if item.get("vendor_answered"):
                total_vendor_answered += 1
        if total_items == 0:
            return (0, 0, 0)
        return (
            total_items,
            total_vendor_answered,
            round((total_vendor_answered / total_items) * 100),
        )

    def get_grouping_for_question_review_status(self, items=[]):
        """
        Get a grouping of FormItem review_status in dict form
        """
        review_status_count = {
            "pending": 0,
            "info_required": 0,
            # "remediation_required": 0,
            "complete": 0,
        }

        if not items:
            items = self.get_items(flatten=True)

        for item in items:
            status = item["review_status"]
            # if status in ("pending", "info_required") and not item["remediation_plan_complete"]:
            #     status = "remediation_required"
            review_status_count[status] += 1
        return review_status_count

    def get_question_review_percentage(self, items=[]):
        """
        Gets the percentage of questions that are reviewed by infosec
        by adding the remediation_required and complete status
        """
        review_status = self.get_grouping_for_question_review_status(items=items)
        if not review_status:
            return 0
        total_questions = sum(review_status.values())
        pending_questions = review_status.get("pending", 0)
        infosec_status = total_questions - pending_questions
        if not total_questions:
            return 0
        return round((infosec_status / total_questions) * 100)

    def get_question_review_percentage_for_vendor(self, items=[]):
        """
        Gets the percentage of questions that are reviewed by vendor
        by adding the remediation_required and complete status
        """
        review_status = self.get_grouping_for_question_review_status(items=items)
        if not review_status:
            return 0
        total_questions = sum(review_status.values())
        pending_questions = review_status.get("info_required", 0)
        infosec_status = total_questions - pending_questions
        if not total_questions:
            return 0
        return round((infosec_status / total_questions) * 100)

    def is_assessment_published(self):
        if self.review_status in ["pending_response", "pending_review", "complete"]:
            return True
        return False

    def is_vendor_status(self):
        """
        Checks to see if the status is waiting on the infosec team or the vendor
        """
        if self.review_status in [
            "pending_response",
        ]:
            return True
        return False

    def get_review_description(self):
        mapping = {
            "new": "Please edit and publish the assessment",
            "pending_response": "Waiting on completion from respondent",
            "pending_review": "Waiting on InfoSec to review",
            "complete": "Completed",
        }
        return mapping.get(self.review_status)

    def create_section(self, title, order=1):
        form = db.session.get(Form, self.form_id)
        return form.create_section(title, order)

    def get_section(self, title):
        if not self.form_id:
            return None
        form = db.session.get(Form, self.form_id)
        return form.get_section(title)

    def get_items(self, edit_mode=None, flatten=False):
        if not self.form_id:
            return []
        form = db.session.get(Form, self.form_id)
        return form.get_items(edit_mode=edit_mode, flatten=flatten)

    def is_review_complete(self):
        if self.review_status.lower() == "complete":
            return True
        return False

    def is_complete(self):
        if not self.is_review_complete() or self.status == "pending":
            return False
        return True

    def days_until_due_date(self, humanize=False):
        if not self.due_before:
            return 0
        if humanize:
            return arrow.get(self.due_before).humanize(granularity=["day"])
        return (arrow.get(self.due_before).date() - arrow.utcnow().date()).days

    @validates("status")
    def _validate_status(self, key, value):
        if value.lower() not in self.VALID_STATUS:
            raise ValueError(f"Invalid status: {value}")
        return value.lower()

    @validates("review_status")
    def _validate_review_status(self, key, value):
        if (
            self.review_status == "pending_response"
            and value.lower() == "pending_review"
        ):
            if self.get_vendor_answered_percentage()[2] != 100:
                raise ValueError(
                    "All questions must be answered before moving to pending_review"
                )

        if value.lower() not in self.VALID_REVIEW_STATUS:
            raise ValueError(f"Invalid review status: {value}")

        return value.lower()

    def send_status_update_to_vendor(self, status):
        link = "{}{}".format(current_app.config["HOST_NAME"], "assessments")
        title = f"{current_app.config['APP_NAME']}: Form Status Update"
        content = f"Your assessment has changed status to: {status}. Please click the button below to view"
        send_email(
            title,
            recipients=[self.vendor.contact_email],
            text_body=render_template(
                "email/basic_template.txt",
                title=title,
                content=content,
                button_link=link,
            ),
            html_body=render_template(
                "email/basic_template.html",
                title=title,
                content=content,
                button_link=link,
            ),
        )
        return True

    def send_invite(self, email):
        link = "{}{}".format(current_app.config["HOST_NAME"], "assessments")
        title = f"{current_app.config['APP_NAME']}: Vendor Assessment"
        content = f"You have been invited to {current_app.config['APP_NAME']} for a assessment. Please click the button below to begin."
        send_email(
            title,
            recipients=[email],
            text_body=render_template(
                "email/basic_template.txt",
                title=title,
                content=content,
                button_link=link,
            ),
            html_body=render_template(
                "email/basic_template.html",
                title=title,
                content=content,
                button_link=link,
            ),
        )
        return True

    def send_reminder_email_to_vendor(self):
        guests = [guest.get("email") for guest in self.get_guests()]
        if not guests:
            abort(422, "There are no guests for the assessment")

        link = "{}{}/{}".format(current_app.config["HOST_NAME"], "assessments", self.id)
        title = f"{current_app.config['APP_NAME']}: Please complete the Assessment."
        content = f"Please remember to complete and submit the assessment."
        send_email(
            title,
            recipients=guests,
            text_body=render_template(
                "email/basic_template.txt",
                title=title,
                content=content,
                button_link=link,
            ),
            html_body=render_template(
                "email/basic_template.html",
                title=title,
                content=content,
                button_link=link,
            ),
        )
        return True

    def delete_guests(self, guests=[]):
        if not guests:
            self.guests.delete()
        else:
            if not isinstance(guests, list):
                guests = [guests]
            current_guests = self.guests.all()
            for record in current_guests:
                if record.user.email in guests:
                    db.session.delete(record)
        db.session.commit()
        return True

    def get_available_guests(self):
        """
        Returns a list of all users inside the tenant with the
        vendor role. Users already added as a vendor for this assessment
        will be marked with access:True
        """
        users = []
        for member in self.tenant.members.all():
            user = member.user
            if user is None:
                continue
            record = {"id": user.id, "email": user.email, "access": False}
            if self.can_user_be_added_as_a_guest(user):
                if self.has_guest(user.email):
                    record["access"] = True
                users.append(record)
        return users

    def can_user_be_added_as_a_guest(self, user):
        if self.tenant.has_member_with_role(user, "vendor"):
            return True
        return False

    def has_guest(self, email):
        return email in [x.user.email for x in self.guests.all()]

    def get_guests(self):
        return [{"id": x.user_id, "email": x.user.email} for x in self.guests.all()]

    def add_guest(self, email, send_notification=False):
        current_guest_emails = [x.user.email for x in self.guests.all()]
        if email not in current_guest_emails:
            current_guest_emails.append(email)
        return self.set_guests(
            guests=current_guest_emails, send_notification=send_notification
        )

    def set_guests(self, guests, send_notification=False):
        """
        Set guests for an assessment. If an email is not found
        in the tenant, the user will be invited with the vendor role
        and added to the assessment

        guests: list of emails
        send_notification: send email notification

        """
        guests_to_notify = []
        guests_to_add = []

        current_guests = [x.user_id for x in self.guests.all()]
        self.delete_guests()
        if not isinstance(guests, list):
            guests = [guests]

        for email in guests:
            if user := User.find_by_email(email):
                if self.can_user_be_added_as_a_guest(user) and not self.has_guest(
                    user.email
                ):
                    self.guests.append(AssessmentGuest(user_id=user.id))
                    if user.id not in current_guests and send_notification:
                        guests_to_notify.append(user.email)
            else:
                # Invite user to the tenant
                user = self.tenant.add_member(
                    user_or_email=email,
                    attributes={"roles": ["vendor"]},
                    send_notification=False,
                )
                self.guests.append(AssessmentGuest(user_id=user.get("id")))
                if send_notification:
                    guests_to_notify.append(email)

        db.session.commit()
        for email in guests_to_notify:
            self.send_invite(email)

        for email in guests_to_add:
            self.send_invite(email)
        return True

    def remove_guests(self, guests):
        """
        guests: list of emails
        """
        self.delete_guests(guests)



