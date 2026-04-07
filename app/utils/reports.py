"""
Masri Digital Compliance Platform — PDF Report Generation

Generates compliance reports as PDF using WeasyPrint (HTML → CSS → PDF).
Falls back with a clear error if WeasyPrint is not installed.
"""

from jinja2 import Environment, FileSystemLoader

try:
    from weasyprint import HTML, CSS
    _PDF_ENGINE = "weasyprint"
except (ImportError, OSError):
    HTML = None
    CSS = None
    _PDF_ENGINE = "none"

from flask import current_app
import arrow
import uuid
import os
import logging

logger = logging.getLogger(__name__)


class Report:
    def __init__(self):
        pass

    def base_config(self, project):
        config = current_app.config
        data = {
            "project_name": project.name,
            "app_name": config["APP_NAME"],
            "doc_url": config["DOC_LINK"],
            "console_url": config.get("CONSOLE_LINK", config.get("HOST_NAME", "")),
            "company": project.tenant.name,
            "contact_email": project.tenant.contact_email,
            "date": arrow.now().strftime("%d %B, %Y"),
            "report_title": "Compliance Report",
        }
        return data

    def project_data(self, project):
        return project.as_dict(with_controls=True)

    # Allowed template filenames (prevent path traversal)
    _ALLOWED_HTML = {"report.html"}
    _ALLOWED_CSS = {"report.css"}

    def generate(
        self, project, data=[], html_template="report.html", css_template="report.css"
    ):
        """
        Generate a PDF compliance report for a project.

        Returns the filename of the generated PDF (relative to reports dir).
        """
        if html_template not in self._ALLOWED_HTML:
            raise ValueError(f"Invalid template: {html_template}")
        if css_template not in self._ALLOWED_CSS:
            raise ValueError(f"Invalid CSS template: {css_template}")

        if _PDF_ENGINE == "none":
            raise RuntimeError(
                "PDF generation requires WeasyPrint. "
                "Install with: pip install weasyprint"
            )

        # Ensure reports directory exists
        reports_dir = os.path.join(current_app.root_path, "files", "reports")
        os.makedirs(reports_dir, exist_ok=True)

        # Build template context
        config = self.base_config(project)
        config["data"] = self.project_data(project)

        # Add risk register
        try:
            config["risks"] = [r.as_dict() for r in project.risks.all()]
        except Exception:
            config["risks"] = []

        # Add evidence inventory
        try:
            config["evidence_items"] = [
                {
                    "name": e.name,
                    "group": e.group or "General",
                    "collected_on": e.collected_on.strftime("%Y-%m-%d") if e.collected_on else "N/A",
                }
                for e in project.evidence.all()
            ]
        except Exception:
            config["evidence_items"] = []

        # Add review summary
        try:
            config["review_summary"] = project.review_summary()
        except Exception:
            config["review_summary"] = {}

        # Render HTML from Jinja2 template
        template_dir = os.path.join(current_app.root_path, "templates", "reports")
        env = Environment(loader=FileSystemLoader(template_dir))
        template = env.get_template(html_template)

        filebase = uuid.uuid4().hex
        generated_html = os.path.join(reports_dir, f"{filebase}.html")

        with open(generated_html, "w") as fh:
            fh.write(template.render(**config))

        # Convert HTML → PDF via WeasyPrint
        css_path = os.path.join(current_app.root_path, "static", "css", css_template)
        filepath = os.path.join(reports_dir, f"{filebase}.pdf")

        stylesheets = []
        if os.path.isfile(css_path):
            stylesheets.append(CSS(filename=css_path))

        HTML(filename=generated_html).write_pdf(filepath, stylesheets=stylesheets)
        logger.info("Generated PDF report: %s for project %s", filebase, project.id)

        # Clean up generated HTML
        if os.path.isfile(generated_html):
            os.remove(generated_html)

        return f"{filebase}.pdf"
