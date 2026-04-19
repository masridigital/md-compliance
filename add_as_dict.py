import re

with open("app/models/project.py", "r") as f:
    text = f.read()

new_as_dict = """    dismissed_at = db.Column(db.DateTime, nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=True)
    status = db.Column(db.String, default="pending")  # pending, accepted, dismissed

    def as_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "kind": self.kind,
            "payload": dict(self.payload) if self.payload else {},
            "confidence": self.confidence,
            "status": getattr(self, "status", "pending"),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "dismissed_at": self.dismissed_at.isoformat() if self.dismissed_at else None,
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
            "reviewed_by_id": self.reviewed_by_id
        }"""

old_str = """    dismissed_at = db.Column(db.DateTime, nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=True)"""

if old_str in text:
    # replace only first occurrence to avoid messing up
    text = text.replace(old_str, new_as_dict, 1)
    with open("app/models/project.py", "w") as f:
        f.write(text)
    print("Added AiSuggestion.as_dict()")
else:
    print("Could not find old_str")
