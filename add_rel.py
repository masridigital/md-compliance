import re

with open("app/models/project.py", "r") as f:
    text = f.read()

# Add relationship string right after evidence
rel_str = """    evidence = db.relationship(
        "ProjectEvidence",
        secondary="evidence_association",
        lazy="select",
        backref=db.backref("project_subcontrols", lazy="dynamic"),
    )

    ai_suggestions = db.relationship(
        "AiSuggestion",
        primaryjoin="and_(foreign(ProjectSubControl.id) == AiSuggestion.subject_id, AiSuggestion.subject_type == 'ProjectSubControl')",
        lazy="select",
        order_by="AiSuggestion.created_at.desc()"
    )"""

old_rel = """    evidence = db.relationship(
        "ProjectEvidence",
        secondary="evidence_association",
        lazy="select",
        backref=db.backref("project_subcontrols", lazy="dynamic"),
    )"""

if old_rel in text:
    text = text.replace(old_rel, rel_str)
    with open("app/models/project.py", "w") as f:
        f.write(text)
    print("Added relationship!")
else:
    print("Could not find old_rel")
