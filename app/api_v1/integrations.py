from flask import (
    jsonify,
    request
)
from . import api
from app.utils.decorators import login_required
from app.utils.integrations import api_get, api_post, api_put, api_delete
from app.utils.authorizer import Authorizer
from flask_login import current_user

# -------------------------
# Integration Endpoints
# -------------------------

@api.route("/integrations", methods=["GET"])
@login_required
def list_integrations():
    response = api_get("integrations")
    return jsonify(response)

@api.route("/integrations/<string:id>", methods=["GET"])
@login_required
def get_integration(id):
    response = api_get(f"integrations/{id}")
    return jsonify(response)

@api.route("/integrations", methods=["POST"])
@login_required
def create_integration():
    data = request.get_json()
    response = api_post(f"integrations", payload=data)
    return jsonify(response)

# -------------------------
# Deployment Endpoints
# -------------------------

@api.route("/tenants/<string:tenant_id>/deployments", methods=["GET"])
@login_required
def list_deployments(tenant_id):
    Authorizer(current_user).can_user_manage_tenant(tenant_id)
    response = api_get(f"tenants/{tenant_id}/deployments")
    return jsonify(response)

@api.route("/tenants/<string:tenant_id>/deployments", methods=["POST"])
@login_required
def create_deployment(tenant_id):
    Authorizer(current_user).can_user_manage_tenant(tenant_id)
    data = request.get_json()
    response = api_post(f"tenants/{tenant_id}/deployments", payload=data)
    return jsonify(response)

@api.route("/tenants/<string:tenant_id>/deployments/<string:deployment_id>", methods=["PUT"])
@login_required
def update_deployment(tenant_id, deployment_id):
    Authorizer(current_user).can_user_manage_tenant(tenant_id)
    data = request.get_json()
    response = api_put(f"tenants/{tenant_id}/deployments/{deployment_id}", data)
    return jsonify(response)

@api.route("/tenants/<string:tenant_id>/deployments/<string:id>", methods=["GET"])
@login_required
def get_deployment(tenant_id, id):
    Authorizer(current_user).can_user_manage_tenant(tenant_id)
    response = api_get(f"tenants/{tenant_id}/deployments/{id}")
    return jsonify(response)

@api.route("/tenants/<string:tenant_id>/deployments/<string:id>", methods=["DELETE"])
@login_required
def delete_deployment(tenant_id, id):
    Authorizer(current_user).can_user_manage_tenant(tenant_id)
    response = api_delete(f"tenants/{tenant_id}/deployments/{id}")
    return jsonify(response)

@api.route("/tenants/<string:tenant_id>/deployments/<string:id>/violations", methods=["GET"])
@login_required
def list_violations_for_deployment(tenant_id, id):
    Authorizer(current_user).can_user_manage_tenant(tenant_id)
    response = api_get(f"tenants/{tenant_id}/deployments/{id}/violations")
    return jsonify(response)

@api.route("/tenants/<string:tenant_id>/deployments/<string:id>/jobs", methods=["GET"])
@login_required
def list_jobs_for_deployment(tenant_id, id):
    Authorizer(current_user).can_user_manage_tenant(tenant_id)
    response = api_get(f"tenants/{tenant_id}/jobs", params={"deployment_id": id})
    return jsonify(response)

@api.route("/tenants/<string:tenant_id>/deployments/<string:deployment_id>/jobs", methods=["POST"])
@login_required
def execute_manual_deployment(tenant_id, deployment_id):
    Authorizer(current_user).can_user_manage_tenant(tenant_id)
    response = api_get(f"tenants/{tenant_id}/deployments/{deployment_id}")
    if response.get("schedule"):
        return jsonify({"message": "deployment is not manual"})
    response = api_post(f"tenants/{tenant_id}/jobs", {"deployment_id": deployment_id})
    return jsonify(response)

# -------------------------
# Job Endpoints
# -------------------------

@api.route("/tenants/<string:tenant_id>/jobs", methods=["GET"])
@login_required
def list_jobs(tenant_id):
    Authorizer(current_user).can_user_manage_tenant(tenant_id)
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    response = api_get(f"tenants/{tenant_id}/jobs?page={page}&per_page={per_page}")
    return jsonify(response)

@api.route("/tenants/<string:tenant_id>/jobs/<string:job_id>", methods=["GET"])
@login_required
def get_job(tenant_id, job_id):
    Authorizer(current_user).can_user_manage_tenant(tenant_id)
    response = api_get(f"tenants/{tenant_id}/jobs/{job_id}")
    return jsonify(response)

# -------------------------
# Violation Endpoints
# -------------------------

@api.route("/tenants/<string:tenant_id>/violations", methods=["GET"])
@login_required
def list_violations(tenant_id):
    Authorizer(current_user).can_user_manage_tenant(tenant_id)
    response = api_get(f"tenants/{tenant_id}/violations")
    return jsonify(response)

# -------------------------
# Init Integrations
# -------------------------

@api.route("/init-integrations", methods=["POST"])
@login_required
def deploy_integrations():
    response = api_post(f"init-integrations")
    return jsonify(response)

# -------------------------
# Project Endpoints
# -------------------------
@api.route("/projects/<string:id>/deployments", methods=["GET"])
@login_required
def get_deployments_for_project(id):
    result = Authorizer(current_user).can_user_edit_project(id)
    tenant_id = result['extra']['project'].tenant.id
    deployments = []
    response = api_get(f"tenants/{tenant_id}/deployments")
    for deployment in response:
        if id in deployment.get("project_ids"):
            deployments.append(deployment)
    return jsonify(deployments)

@api.route("/projects/<string:id>/deployments", methods=["POST"])
@login_required
def update_deployments_for_project(id):
    result = Authorizer(current_user).can_user_edit_project(id)
    data = request.get_json()
    if not data or 'deployment_ids' not in data:
        return jsonify({'message': 'deployment_ids is required'}), 400

    deployment_ids = data['deployment_ids']
    if not isinstance(deployment_ids, list) or len(deployment_ids) == 0:
        return jsonify({'message': 'deployment_ids must be a non-empty list'}), 400

    payload = {"deployment_ids": deployment_ids}
    response = api_post(f"/projects/{id}/deployments", payload=payload)
    return jsonify(response)

@api.route("/projects/<string:id>/deployments", methods=["DELETE"])
@login_required
def delete_deployment_from_project(id):
    result = Authorizer(current_user).can_user_edit_project(id)
    data = request.get_json()
    if not data or 'deployment_ids' not in data:
        return jsonify({'message': 'deployment_ids is required'}), 400

    deployment_ids = data['deployment_ids']
    if not isinstance(deployment_ids, list) or len(deployment_ids) == 0:
        return jsonify({'message': 'deployment_ids must be a non-empty list'}), 400

    payload = {"deployment_ids": deployment_ids}
    response = api_delete(f"/projects/{id}/deployments", payload=payload)
    return jsonify(response)