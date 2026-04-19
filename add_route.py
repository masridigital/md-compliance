import re

with open("app/api_v1/views.py", "r") as f:
    text = f.read()

route_code = """
@api.route("/projects/<string:pid>/subcontrols/<string:sid>/suggestions/<string:sug_id>", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def handle_ai_suggestion(pid, sid, sug_id):
    result = Authorizer(current_user).can_user_manage_project_subcontrol(sid)
    data = request.get_json() or {}
    action = data.get("action")
    
    from app.models.project import AiSuggestion
    from datetime import datetime
    sugg = db.session.get(AiSuggestion, sug_id)
    if not sugg or sugg.subject_id != sid:
        return jsonify({"message": "Not found"}), 404

    if action == "accept":
        sugg.accepted_at = datetime.utcnow()
        sugg.reviewed_by_id = current_user.id
        # When accepted, the rationale could be pushed to notes or context
        subcontrol = result["extra"]["subcontrol"]
        existing = subcontrol.notes or ""
        subcontrol.notes = f"{existing}\\n\\n[AI Suggestion Accepted]: {sugg.payload.get('suggestion_text', '')}\\nRationale: {sugg.payload.get('rationale', '')}".strip()
    elif action == "dismiss":
        sugg.dismissed_at = datetime.utcnow()
        sugg.reviewed_by_id = current_user.id
        
    db.session.commit()
    return jsonify(sugg.as_dict())
"""

# Append it near the other subcontrol routes
target = "def update_notes_for_subcontrol(pid, sid):"
if target in text:
    idx = text.find(target)
    # find the previous @api.route to reliably insert
    start_idx = text.rfind("@api.route", 0, idx)
    text = text[:start_idx] + route_code + "\n" + text[start_idx:]
    with open("app/api_v1/views.py", "w") as f:
        f.write(text)
    print("Added route!")
else:
    print("Failed to find target")
