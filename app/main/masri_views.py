"""
Masri Digital Compliance Platform — New View Routes (Phase 1)

Stub routes that register the Flask endpoint names referenced by the
Masri frontend templates.  These are added to the existing ``main``
blueprint so that ``url_for('main.index')``, ``url_for('main.compliance')``,
etc. all resolve correctly.

After merge, this file lives at ``app/main/masri_views.py`` and is
imported by ``app/main/__init__.py``.
"""

from flask import render_template, redirect, url_for, request, jsonify
from . import main
from app.utils.decorators import login_required
from app.utils.authorizer import Authorizer


# ---------------------------------------------------------------------------
# MCP OAuth discovery at root level (Claude expects /.well-known/...)
# ---------------------------------------------------------------------------

@main.route("/.well-known/oauth-authorization-server", methods=["GET"])
def oauth_discovery_root():
    """Root-level OAuth discovery — redirects to MCP server metadata."""
    base = request.host_url.rstrip("/") + "/mcp"
    return jsonify({
        "issuer": base,
        "token_endpoint": base + "/token",
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
        "grant_types_supported": ["client_credentials"],
        "scopes_supported": ["mcp:tools", "mcp:read", "mcp:write"],
        "response_types_supported": [],
        "service_documentation": base + "/docs",
    })
from flask_login import current_user


# ---------------------------------------------------------------------------
# Home / Dashboard
# ---------------------------------------------------------------------------

@main.route("/dashboard", methods=["GET"])
@login_required
def index():
    """Masri home dashboard — aliased as ``main.index``."""
    return render_template("home_masri.html")


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------

@main.route("/compliance", methods=["GET"])
@login_required
def compliance():
    """Compliance controls view."""
    return render_template("compliance_masri.html")


# ---------------------------------------------------------------------------
# Risk  (tenant-scoped, but also a top-level nav link)
# ---------------------------------------------------------------------------

@main.route("/risk", methods=["GET"])
@login_required
def risk():
    """Top-level risk redirect — delegates to tenant-scoped risk view."""
    tenant_id = getattr(current_user, "default_tenant_id", None) or request.args.get("tenant_id")
    if tenant_id:
        return redirect(url_for("main.risks", id=tenant_id))
    return render_template("risk_register.html")


# ---------------------------------------------------------------------------
# WISP
# ---------------------------------------------------------------------------

@main.route("/wisp", methods=["GET"])
@login_required
def wisp():
    """WISP wizard entry point."""
    return render_template("wisp/wizard_masri.html")


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

@main.route("/vendors", methods=["GET"])
@login_required
def vendors():
    """Vendor management list."""
    return render_template("vendors.html")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@main.route("/settings", methods=["GET"])
@login_required
def masri_settings():
    """Settings hub (macOS-style settings page)."""
    return render_template("management/settings_masri.html")


# ---------------------------------------------------------------------------
# Tenant operations
# ---------------------------------------------------------------------------

@main.route("/profile", methods=["GET"])
@login_required
def profile():
    """User profile page — personal info, session timeout, MFA."""
    return render_template("profile.html")


@main.route("/system", methods=["GET"])
@login_required
def system_info():
    """System information and deployment status."""
    from app.utils.authorizer import Authorizer
    Authorizer(current_user).can_user_manage_platform()
    return render_template("system_info.html")


@main.route("/clients", methods=["GET"])
@main.route("/workspace", methods=["GET"])
@login_required
def workspace():
    """Unified clients page — manage clients and projects."""
    return render_template("workspace.html")


@main.route("/tenants/new", methods=["GET"])
@login_required
def new_tenant():
    """Create a new tenant / client."""
    return render_template("new_tenant.html")


@main.route("/tenants/<string:tenant_id>", methods=["GET"])
@login_required
def tenant_detail(tenant_id):
    """View tenant detail page."""
    Authorizer(current_user).can_user_access_tenant(tenant_id)
    return render_template("tenant_detail.html", tenant_id=tenant_id)


@main.route("/tenants/<string:tenant_id>/switch", methods=["GET"])
@login_required
def switch_tenant(tenant_id):
    """Switch the user's active tenant context."""
    Authorizer(current_user).can_user_access_tenant(tenant_id)
    # Store the active tenant in session or user profile
    from flask import session
    session["active_tenant_id"] = tenant_id
    return redirect(url_for("main.index"))


# ---------------------------------------------------------------------------
# Code Review Graph
# ---------------------------------------------------------------------------

@main.route("/code-graph", methods=["GET"])
@login_required
def code_graph():
    """Interactive codebase knowledge graph visualization (admin only)."""
    Authorizer(current_user).can_user_manage_platform()
    return render_template("code_graph.html")


@main.route("/api/v1/code-graph/data", methods=["GET"])
@login_required
def code_graph_data():
    """Return graph data as JSON for the code graph visualization."""
    import sqlite3
    import os

    Authorizer(current_user).can_user_manage_platform()

    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        ".code-review-graph", "graph.db"
    )
    if not os.path.exists(db_path):
        return jsonify({"error": "Graph database not found. Run: code-review-graph build"}), 404

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _strip(path):
        return (path or "").replace(base + "/", "").replace(base, "")

    # Nodes
    nodes = []
    for r in db.execute(
        "SELECT id, kind, name, qualified_name, file_path, line_start, line_end, "
        "language, community_id FROM nodes ORDER BY kind, name"
    ):
        nodes.append({
            "id": r["id"], "kind": r["kind"], "name": r["name"],
            "qn": r["qualified_name"], "file": _strip(r["file_path"]),
            "line_start": r["line_start"], "line_end": r["line_end"],
            "language": r["language"], "community": r["community_id"],
        })

    # Edges
    edges = []
    for r in db.execute(
        "SELECT kind, source_qualified, target_qualified FROM edges"
    ):
        edges.append({
            "kind": r["kind"], "source_qn": r["source_qualified"],
            "target_qn": r["target_qualified"],
            "source_name": (r["source_qualified"] or "").split("::")[-1],
            "target_name": (r["target_qualified"] or "").split("::")[-1],
        })

    # Communities
    communities = []
    for r in db.execute(
        "SELECT name, size, dominant_language FROM communities ORDER BY size DESC"
    ):
        communities.append({
            "name": r["name"], "size": r["size"],
            "language": r["dominant_language"],
        })

    # Dependencies (cross-file calls)
    dependencies = []
    for r in db.execute("""
        SELECT n1.file_path as src, n2.file_path as tgt, COUNT(*) as cnt
        FROM edges e
        JOIN nodes n1 ON e.source_qualified = n1.qualified_name
        JOIN nodes n2 ON e.target_qualified = n2.qualified_name
        WHERE e.kind = 'CALLS' AND n1.file_path != n2.file_path
        GROUP BY src, tgt ORDER BY cnt DESC LIMIT 50
    """):
        dependencies.append({
            "source": _strip(r["src"]), "target": _strip(r["tgt"]),
            "count": r["cnt"],
        })

    # Risks
    risks = []
    for r in db.execute(
        "SELECT qualified_name, risk_score, caller_count, test_coverage, "
        "security_relevant FROM risk_index ORDER BY risk_score DESC LIMIT 50"
    ):
        risks.append({
            "name": _strip(r["qualified_name"]).split("::")[-1] if "::" in r["qualified_name"] else r["qualified_name"],
            "full_name": _strip(r["qualified_name"]),
            "risk": r["risk_score"], "callers": r["caller_count"],
            "coverage": r["test_coverage"], "security": bool(r["security_relevant"]),
        })

    # Flows
    flows = []
    for r in db.execute(
        "SELECT name, criticality, node_count, file_count FROM flows "
        "ORDER BY criticality DESC LIMIT 30"
    ):
        flows.append({
            "name": r["name"], "criticality": r["criticality"],
            "nodes": r["node_count"], "files": r["file_count"],
        })

    # Test coverage per file
    coverage = []
    file_nodes = {}
    for r in db.execute(
        "SELECT file_path, COUNT(*) as cnt FROM nodes "
        "WHERE kind != 'File' GROUP BY file_path ORDER BY cnt DESC"
    ):
        fp = _strip(r["file_path"])
        if "test" not in fp and "migration" not in fp:
            file_nodes[fp] = {"total": r["cnt"], "tested": 0}
    for r in db.execute(
        "SELECT DISTINCT n.file_path FROM edges e "
        "JOIN nodes n ON e.target_qualified = n.qualified_name "
        "WHERE e.kind = 'TESTED_BY'"
    ):
        fp = _strip(r["file_path"])
        if fp in file_nodes:
            file_nodes[fp]["tested"] += 1
    for fp, v in sorted(file_nodes.items(), key=lambda x: x[1]["total"], reverse=True):
        pct = round(v["tested"] / v["total"] * 100) if v["total"] > 0 else 0
        coverage.append({"file": fp, "total": v["total"], "tested": v["tested"], "pct": pct})

    # Stats
    kind_counts = {}
    for r in db.execute("SELECT kind, COUNT(*) as cnt FROM nodes GROUP BY kind"):
        kind_counts[r["kind"]] = r["cnt"]
    lang_count = db.execute("SELECT COUNT(DISTINCT language) FROM nodes").fetchone()[0]
    edge_count = db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    flow_count = db.execute("SELECT COUNT(*) FROM flows").fetchone()[0]

    db.close()

    stats = {
        "nodes": len(nodes), "edges": edge_count,
        "files": kind_counts.get("File", 0),
        "functions": kind_counts.get("Function", 0),
        "classes": kind_counts.get("Class", 0),
        "tests": kind_counts.get("Test", 0),
        "communities": len(communities),
        "flows": flow_count, "languages": lang_count,
    }

    return jsonify({
        "stats": stats, "nodes": nodes, "edges": edges,
        "communities": communities, "dependencies": dependencies,
        "risks": risks, "flows": flows, "coverage": coverage,
    })
