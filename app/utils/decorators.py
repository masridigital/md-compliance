from functools import wraps
from urllib.parse import urlparse
from flask import request, jsonify, redirect, url_for, flash
from app.models import *
from flask_login import current_user, login_user, logout_user
from app.utils.authorizer import Authorizer


def _safe_next(next_url):
    """Return next_url only if it is a safe relative path (no external redirect)."""
    if not next_url:
        return url_for("main.home")
    stripped = next_url.strip()
    if stripped.startswith(("//", "\\", "/\\")):
        return url_for("main.home")
    parsed = urlparse(stripped)
    if parsed.scheme or parsed.netloc:
        return url_for("main.home")
    if not stripped.startswith("/"):
        return url_for("main.home")
    return stripped


def custom_login(user):
    if isinstance(user, User):
        user.login_count = (user.login_count or 0) + 1
        db.session.commit()
        login_user(user)
        Logs.add(
            message=f"{user.email} logged in",
            action="LOGIN",
            namespace="auth",
            user_id=user.id,
        )


def validate_token_in_header(enc_token):
    user = User.verify_auth_token(enc_token)
    if not user:
        return False
    if not user.is_active:
        return False
    if not user.confirmed:
        return False
    return user


def is_logged_in(f):
    @wraps(f)
    def decorated_function(*args, **kws):
        next_page = request.args.get("next")
        if current_user.is_authenticated:
            flash("You are already logged in", "success")
            return redirect(_safe_next(next_page))
        return f(*args, **kws)

    return decorated_function


def login_required(view_function):
    """This decorator ensures that the current user is logged in.
    Example::
        @route('/member_page')
        @login_required
        def member_page():  # User must be logged in
            ...
    If USER_ENABLE_EMAIL is True and USER_ENABLE_CONFIRM_EMAIL is True,
    this view decorator also ensures that the user has a confirmed email address.
    | Calls unauthorized_view() when the user is not logged in
        or when the user has not confirmed their email address.
    | Calls the decorated view otherwise.
    """

    @wraps(view_function)
    def decorator(*args, **kwargs):
        # Try to authenticate with a token (API login, must have token in HTTP header)
        if token := request.headers.get("token"):
            if not (user := validate_token_in_header(token)):
                return jsonify({"message": "Invalid authentication"}), 401
            custom_login(user)
        else:
            if not current_user.is_authenticated:
                return redirect(url_for("auth.get_login", next=request.full_path))

            if not current_user.is_active:
                logout_user()
                flash("User account is disabled", "warning")
                return redirect(url_for("auth.get_login"))

            # Allow authenticated user to send email confirmation
            if not current_user.email_confirmed_at and request.endpoint not in [
                "auth.post_get_started",
                "auth.get_started",
                "auth.confirm_email",
                "api.send_user_confirmation",
                "api.verify_user_confirmation",
            ]:
                flash("Please confirm your email to continue")
                return redirect(url_for("auth.confirm_email"))

            # Allow authenticated user requiring password change
            # to access specific endpoints to update their password
            if current_user.is_password_change_required() and request.endpoint not in [
                "auth.set_password",
                "api.change_password",
            ]:
                flash("Please set your password to continue")
                return redirect(url_for("auth.set_password"))

        # It's OK to call the view
        return view_function(*args, **kwargs)

    return decorator


def requires_auth(method_name, param=None, inject=None):
    """Authorization decorator that wraps Authorizer checks.

    Replaces the boilerplate pattern::

        result = Authorizer(current_user).can_user_access_project(pid)
        project = result["extra"]["project"]

    With::

        @requires_auth("can_user_access_project", param="pid", inject="project")
        def view_project(pid, project):
            ...

    Args:
        method_name: Name of the Authorizer method (e.g. ``"can_user_access_project"``).
        param: URL parameter name to pass to the auth method. If None, the auth
               method is called with no arguments (e.g. ``can_user_manage_platform``).
        inject: Key from the result's ``extra`` dict to inject as a keyword argument
                to the view function. If None, the full result is injected as ``auth_result``.
    """
    def decorator(view_function):
        @wraps(view_function)
        def wrapper(*args, **kwargs):
            auth = Authorizer(current_user)
            auth_method = getattr(auth, method_name)
            if param:
                result = auth_method(kwargs[param])
            else:
                result = auth_method()
            if inject:
                kwargs[inject] = result["extra"][inject]
            else:
                kwargs["auth_result"] = result
            return view_function(*args, **kwargs)
        return wrapper
    return decorator
