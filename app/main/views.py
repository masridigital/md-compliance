from flask import (
    send_from_directory,
)
from . import main
from app.utils.decorators import *
from app.utils.authorizer import Authorizer


@main.route("/", methods=["GET"])
@login_required
def home():
    return render_template("home.html")

@main.route("/integrations", methods=["GET"])
@login_required
def integrations():
    return render_template("integrations.html")

@main.route("/projects/<string:pid>/reports/<path:filename>", methods=["GET"])
@login_required
def download_report(pid, filename):
    result = Authorizer(current_user).can_user_access_project(pid)
    return send_from_directory(
        directory=current_app.config["UPLOAD_FOLDER"], path=filename, as_attachment=True
    )


@main.route("/frameworks", methods=["GET"])
@login_required
def frameworks():
    return render_template("frameworks.html")

@main.route("/violations", methods=["GET"])
@login_required
def violations():
    return render_template("violations.html")


@main.route("/tenants/<string:id>/risk", methods=["GET"])
@login_required
def risks(id):
    Authorizer(current_user).can_user_access_risk_module(id)
    return render_template("risk_register.html")

@main.route("/tenants/<string:id>/policy-center", methods=["GET"])
@login_required
def view_policy_center(id):
    Authorizer(current_user).can_user_access_tenant(id)
    policy_id = request.args.get("policy-id")
    return render_template("pc.html", tenant_id=id, policy_id=policy_id)


@main.route("/projects", methods=["GET"])
@login_required
def projects():
    return render_template("projects.html")


@main.route("/projects/<string:pid>", methods=["GET"])
@login_required
def view_project(pid):
    result = Authorizer(current_user).can_user_access_project(pid)
    return render_template("view_project.html", project=result["extra"]["project"])


@main.route("/projects/<string:pid>/controls/<string:cid>", methods=["GET"])
@login_required
def view_control_in_project(pid, cid):
    result = Authorizer(current_user).can_user_read_project_control(cid)
    return render_template(
        "view_control_in_project.html",
        project=result["extra"]["control"].project,
        project_control=result["extra"]["control"],
    )


@main.route("/projects/<string:id>/policy-center", methods=["GET"])
@login_required
def view_policy_center_for_project(id):
    result = Authorizer(current_user).can_user_read_project(id)
    policy_id = request.args.get("policy-id")
    return render_template(
        "policy_center.html", project=result["extra"]["project"], policy_id=policy_id
    )
