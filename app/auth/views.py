import logging
from urllib.parse import urlparse

from flask import (
    request,
    flash,
    redirect,
    url_for,
    render_template,
    abort,
)
from flask_login import current_user, logout_user
from app.utils.decorators import custom_login, login_required, is_logged_in
from app.utils.authorizer import Authorizer
from app import db, limiter
from . import auth
from app.models import *
from app.email import send_email
from app.utils import misc
from app.auth.flows import UserFlow


def _safe_next(next_url):
    """Return next_url only if it is a safe relative path (no external redirect).

    Blocks protocol-relative URLs (//evil.com), backslash-relative URLs
    (\\evil.com), and any URL with a scheme or netloc.
    """
    if not next_url:
        return url_for("main.home")
    # Block protocol-relative and backslash URLs
    stripped = next_url.strip()
    if stripped.startswith(("//", "\\", "/\\")):
        return url_for("main.home")
    parsed = urlparse(stripped)
    if parsed.scheme or parsed.netloc:
        return url_for("main.home")
    # Must start with / to be a valid relative path
    if not stripped.startswith("/"):
        return url_for("main.home")
    return stripped


@auth.route("/login", methods=["GET"])
@is_logged_in
def get_login():
    return render_template("auth/login.html")


@auth.route("/login", methods=["POST"])
@limiter.limit("10 per minute; 50 per hour")
@is_logged_in
def post_login():
    next_page = _safe_next(request.args.get("next"))
    return UserFlow(
        request.form, "login", "local", next_page=next_page
    ).handle_flow()


@auth.route("/logout")
@auth.route("/auth/logout")
def logout():
    """Logout must NEVER fail — always redirect to login page."""
    try:
        from app.models import Logs
        if current_user and current_user.is_authenticated:
            try:
                Logs.add(
                    message=f"{current_user.email} logged out",
                    action="LOGOUT",
                    namespace="auth",
                    user_id=current_user.id,
                )
            except Exception:
                pass
    except Exception:
        pass

    try:
        logout_user()
    except Exception:
        pass

    try:
        from flask import session
        session.clear()
    except Exception:
        pass

    try:
        flash("You are logged out", "success")
    except Exception:
        pass

    try:
        return redirect(url_for("auth.get_login"))
    except Exception:
        return redirect("/login")


@auth.route("/verify-2fa", methods=["GET"])
def get_verify_totp():
    from flask import session
    if not session.get("_totp_user_id"):
        return redirect(url_for("auth.get_login"))
    return render_template("auth/verify_totp.html")


@auth.route("/verify-2fa", methods=["POST"])
@limiter.limit("10 per minute")
def verify_totp():
    from flask import session
    from datetime import datetime, timezone

    user_id = session.get("_totp_user_id")
    if not user_id:
        return redirect(url_for("auth.get_login"))

    # Enforce 5-minute expiration on TOTP challenge
    totp_created = session.get("_totp_created_at")
    if totp_created:
        try:
            created_dt = datetime.fromisoformat(totp_created)
            if (datetime.now(timezone.utc) - created_dt).total_seconds() > 300:
                session.pop("_totp_user_id", None)
                session.pop("_totp_next", None)
                session.pop("_totp_created_at", None)
                session.pop("_totp_attempts", None)
                flash("Verification session expired. Please log in again.", "error")
                return redirect(url_for("auth.get_login"))
        except (ValueError, TypeError):
            pass

    # Enforce max 5 attempts
    attempts = session.get("_totp_attempts", 0)
    if attempts >= 5:
        session.pop("_totp_user_id", None)
        session.pop("_totp_next", None)
        session.pop("_totp_created_at", None)
        session.pop("_totp_attempts", None)
        flash("Too many failed attempts. Please log in again.", "error")
        return redirect(url_for("auth.get_login"))

    user = db.session.get(User, user_id)
    if not user:
        session.pop("_totp_user_id", None)
        flash("Invalid session", "error")
        return redirect(url_for("auth.get_login"))

    code = request.form.get("code", "").strip()
    if not code or not user.verify_totp(code):
        session["_totp_attempts"] = attempts + 1
        flash("Invalid verification code", "error")
        return redirect(url_for("auth.get_verify_totp"))

    # TOTP verified — complete login
    next_page = _safe_next(session.pop("_totp_next", None))
    session.pop("_totp_user_id", None)
    session.pop("_totp_created_at", None)
    session.pop("_totp_attempts", None)
    custom_login(user)
    return redirect(next_page)


@auth.route("/confirm-email", methods=["GET"])
@login_required
def confirm_email():
    if current_user.email_confirmed_at:
        flash("User is already confirmed.")
        return redirect(url_for("main.home"))
    return render_template(
        "auth/confirm_email.html", email_configured=current_app.is_email_configured
    )


@auth.route("/login/tenants/<string:tid>", methods=["GET", "POST"])
@is_logged_in
def login_with_magic_link(tid):
    next_page = _safe_next(request.args.get("next"))
    if current_user.is_authenticated:
        return redirect(next_page)

    if not current_app.is_email_configured:
        flash("Email is not configured", "warning")
        abort(404)
    if not (tenant := db.session.get(Tenant, tid)):
        abort(404)
    if not tenant.magic_link_login:
        flash("Feature is not enabled", "warning")
        abort(404)
    if request.method == "POST":
        email = request.form["email"]
        if not (user := User.find_by_email(email)):
            flash("Invalid email", "warning")
            tenant.add_log(message=f"invalid email for {email}", level="warning")
            return redirect(url_for("auth.login_with_magic_link", tid=tid))
        if not user.is_active:
            flash("User is inactive", "warning")
            tenant.add_log(
                message=f"inactive user tried to login:{email}",
                level="warning",
            )
            return redirect(url_for("auth.login_with_magic_link", tid=tid))
        # send email with login
        token = user.generate_magic_link(tid)
        link = f"{current_app.config['HOST_NAME']}magic-login/{token}"
        title = f"{current_app.config['APP_NAME']}: Login Request"
        content = f"You have requested a login via email. If you did not request a magic link, please ignore. Otherwise, please click the button below to login."
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
                button_label="Login",
            ),
        )
        tenant.add_log(message=f"magic link login request to {email}")
        flash("Please check your email for the login information")
    return render_template("auth/magic-login.html", tid=tid)


@auth.route("/magic-login/<string:token>", methods=["GET"])
@is_logged_in
def validate_magic_link(token):
    next_page = _safe_next(request.args.get("next"))
    if not (vtoken := User.verify_magic_token(token)):
        flash("Token is invalid", "warning")
        return redirect(url_for("auth.get_login"))
    if not (user := db.session.get(User, vtoken.get("user_id"))):
        flash("Invalid user id", "warning")
        return redirect(url_for("auth.get_login"))
    if not (tenant := db.session.get(Tenant, vtoken.get("tenant_id"))):
        flash("Invalid tenant id", "warning")
        return redirect(url_for("auth.get_login"))
    if user.id == tenant.owner_id or user.has_tenant(tenant):
        Logs.add(message=f"{user.email} logged in via magic link", user_id=user.id)
        # If user has TOTP 2FA enabled, require verification before full login
        if getattr(user, 'totp_enabled', False):
            from datetime import datetime, timezone
            session["_totp_user_id"] = user.id
            session["_totp_next"] = next_page
            session["_totp_created_at"] = datetime.now(timezone.utc).isoformat()
            session["_totp_attempts"] = 0
            return redirect(url_for("auth.verify_totp"))
        flash("Welcome")
        custom_login(user)
        return redirect(next_page)
    flash("User can not access tenant", "warning")
    return redirect(url_for("auth.get_login"))


@auth.route("/accept", methods=["GET"])
@is_logged_in
def get_accept():
    """
    GET endpoint for a user accepting invitations
    """
    if not (result := User.verify_invite_token(request.args.get("token"))):
        abort(403, "Invalid or expired invite token")

    if not (user := User.find_by_email(result.get("email"))):
        abort(403, "Invalid token: email not found")

    # If user has already logged in, we show them the login page, otherwise
    # we will show them the accept page (register)
    result["login_count"] = user.login_count
    if user.login_count > 0:
        return redirect(
            url_for(
                "auth.get_login", email=result.get("email"), tenant=result.get("tenant")
            )
        )

    return render_template(
        "auth/accept.html", data=result, token=request.args.get("token")
    )


@auth.route("/accept", methods=["POST"])
@is_logged_in
def post_accept():
    """
    POST endpoint for a user accepting invitations
    """
    next_page = _safe_next(request.args.get("next"))
    attributes = {"token": request.args.get("token")}
    return UserFlow(
        user_info=request.form,
        flow_type="accept",
        provider="local",
        next_page=next_page,
    ).handle_flow(attributes)


@auth.route("/reset-password", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour")
def reset_password_request():
    next_page = _safe_next(request.args.get("next"))
    internal = request.args.get("internal")
    if current_user.is_authenticated and not internal:
        return redirect(next_page)

    if not current_app.is_email_configured:
        flash("Email is not configured. Please contact your admin.", "warning")
        return redirect(url_for("main.home"))

    if request.method == "POST":
        email = request.form.get("email")
        if not (user := User.find_by_email(email)):
            flash("Email sent, check your mail")
            return redirect(url_for("auth.reset_password_request"))
        Logs.add(
            message=f"{email} requested a password reset",
            level="warning",
            user_id=user.id,
        )
        token = user.generate_auth_token()
        link = f"{current_app.config['HOST_NAME']}reset-password/{token}"
        title = "Password reset"
        content = f"You have requested a password reset. If you did not request a reset, please ignore. Otherwise, click the button below to continue."
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
                button_label="Reset",
            ),
        )
        flash("Email sent, check your mail")
        return redirect(url_for("auth.get_login"))
    return render_template("auth/reset_password_request.html")


@auth.route("/reset-password/<string:token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    if not (user := User.verify_auth_token(token)):
        Logs.add(
            message="invalid or missing token for password reset",
            level="warning",
            user_id=None,
        )
        flash("Missing or invalid token", "warning")
        return redirect(url_for("auth.reset_password_request"))
    if request.method == "POST":
        password = request.form.get("password")
        password2 = request.form.get("password2")
        if not misc.perform_pwd_checks(password, password_two=password2):
            flash("Password did not pass checks", "warning")
            return redirect(url_for("auth.reset_password", token=token))
        user.set_password(password, set_pwd_change=True)
        db.session.commit()
        flash("Password reset! Please login with your new password", "success")
        Logs.add(
            message=f"{user.email} reset their password",
            level="warning",
            user_id=user.id,
        )
        return redirect(url_for("auth.get_login"))
    return render_template("auth/reset_password.html", token=token)


@auth.route("/set-password", methods=["GET"])
@login_required
def set_password():
    """
    When a user must set or change their password
    """
    return render_template("auth/set_password.html")


@auth.route("/register", methods=["GET"])
@is_logged_in
def get_register():

    if not current_app.is_self_registration_enabled:
        abort(403, "Self-service registration is disabled")

    return render_template(
        "auth/register.html",
        registration_enabled=current_app.is_self_registration_enabled,
    )


@auth.route("/register", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour")
def post_register():
    """
    POST endpoint for registering new users
    """
    attributes = {"token": request.args.get("token") or request.form.get("token")}
    return UserFlow(request.form, "register", "local").handle_flow(attributes)


@auth.route("/get-started", methods=["GET"])
@login_required
def get_started():
    return render_template("auth/get_started.html")


@auth.route("/get-started", methods=["POST"])
@login_required
def post_get_started():
    """
    Endpoint for creating new tenants after a user registers
    """
    result = Authorizer(current_user).can_user_create_tenants()
    if not (tenant_name := request.form.get("tenant")):
        abort(400, "Tenant name is required")
    try:
        tenant = Tenant.create(
            current_user,
            tenant_name,
            current_user.email,
            init_data=True,
        )
    except Exception as e:
        abort(400, str(e))
    flash("Created tenant")
    return redirect(url_for("main.home"))


# ── First-run setup (no admin exists yet) ────────────────────────────────────

def _setup_required():
    """Return True if no admin user exists yet (first-run state)."""
    try:
        admin = db.session.execute(
            db.select(User).filter(User.super == True)  # noqa: E712
        ).scalars().first()
        return admin is None
    except Exception:
        return False


@auth.route("/setup", methods=["GET"])
def get_setup():
    """Show the first-time admin setup page."""
    if not _setup_required():
        return redirect(url_for("auth.get_login"))
    return render_template("auth/setup.html")


@auth.route("/setup", methods=["POST"])
@limiter.limit("3 per minute")
def post_setup():
    """Create the first admin user and default tenant.

    Uses a PostgreSQL advisory lock to prevent race conditions where
    concurrent requests could both pass the _setup_required() check
    and create duplicate admin accounts.
    """
    if not _setup_required():
        return redirect(url_for("auth.get_login"))

    email = (request.form.get("email") or "").strip()
    password = request.form.get("password", "")
    company = (request.form.get("company") or "").strip() or "My Organization"

    if not email or "@" not in email:
        flash("Please enter a valid email address.", "error")
        return render_template("auth/setup.html")
    if not misc.perform_pwd_checks(password):
        flash("Password must be at least 12 characters.", "error")
        return render_template("auth/setup.html")

    try:
        # Advisory lock prevents race condition: only one request can
        # create the admin at a time.  Lock ID 12345678 is arbitrary
        # but fixed — all setup attempts contend on the same lock.
        from sqlalchemy import text
        db.session.execute(text("SELECT pg_advisory_xact_lock(12345678)"))

        # Re-check inside the lock — another request may have won the race
        if not _setup_required():
            db.session.rollback()
            return redirect(url_for("auth.get_login"))

        user = User.add(
            email,
            password=password,
            confirmed=True,
            built_in=True,
            super=True,
            require_pwd_change=False,
            return_user_object=True,
        )
        Tenant.create(user, company, email, is_default=True, init_data=True)
        db.session.commit()

        from flask import current_app
        current_app._setup_checked = True

        custom_login(user)
        flash("Welcome! Your admin account has been created.", "success")
        return redirect(url_for("main.home"))
    except Exception as e:
        db.session.rollback()
        logging.getLogger(__name__).exception("First-run setup failed")
        flash("Setup failed. Please check the logs and try again.", "error")
        return render_template("auth/setup.html")
