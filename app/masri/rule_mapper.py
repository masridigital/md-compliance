import yaml
import json
import logging
from pathlib import Path
import os

logger = logging.getLogger(__name__)

def run_mapper(db, project):
    """
    Stage 3 — Map.
    Evaluates IntegrationFact rows against fact_patterns YAML for the project's framework.
    Generates ProjectEvidence (status=proposed, kind=integration_artifact) assigned to requirement_slots.
    """
    from app.models import ProjectEvidence, EvidenceAssociation
    from app.models.tenant import IntegrationFact
    
    if not project.framework:
        return 0
        
    fw_name = project.framework.name.lower()
    
    yaml_file = None
    if "soc 2" in fw_name or "soc2" in fw_name:
        yaml_file = "soc2.yaml"
    elif "hipaa" in fw_name:
        yaml_file = "hipaa.yaml"
    elif "nist" in fw_name:
        yaml_file = "nist_800_53.yaml"
        
    if not yaml_file:
        return 0
        
    base_dir = os.path.dirname(os.path.dirname(__file__))
    yaml_path = os.path.join(base_dir, "files", "fact_patterns", yaml_file)
    
    if not os.path.exists(yaml_path):
        return 0
        
    with open(yaml_path, 'r') as f:
        rules_data = yaml.safe_load(f)
        
    rules = rules_data.get("rules", [])
    if not rules:
        return 0
        
    facts = db.session.execute(
        db.select(IntegrationFact).filter_by(tenant_id=project.tenant_id)
    ).scalars().all()
    
    latest_facts = {}
    for f in facts:
        key = (f.source, f.subject)
        if key not in latest_facts or f.collected_at > latest_facts[key].collected_at:
            latest_facts[key] = f
            
    control_map = {}
    for pc in project.controls.all():
        if pc.control and pc.control.ref_code:
            ref = pc.control.ref_code.replace("SOC2-", "")
            if ref not in control_map:
                control_map[ref] = []
            control_map[ref].append(pc)
            
    created_count = 0
    
    for rule in rules:
        ref_code = rule.get("control")
        if ref_code not in control_map:
            continue
            
        source = rule.get("fact_source")
        subject = rule.get("fact_subject")
        fact = latest_facts.get((source, subject))
        
        if not fact:
            continue
            
        try:
            assertion = json.loads(fact.assertion)
        except Exception:
            continue
            
        condition_str = rule.get("condition", "False")
        allowed_globals = {"__builtins__": None}
        allowed_locals = {"assertion": assertion}
        
        try:
            passed = eval(condition_str, allowed_globals, allowed_locals)
        except Exception as e:
            logger.warning(f"Failed to evaluate rule condition '{condition_str}': {e}")
            passed = False
            
        if passed:
            slot = rule.get("requirement_slot")
            ev_name = rule.get("evidence_name")
            desc = rule.get("evidence_description", "")
            rationale = rule.get("rationale", "")
            
            content = f"{desc}\n\nRationale:\n{rationale}\n\nIntegration Fact Details:\nSource: {source}\nSubject: {subject}\nData: {fact.assertion}\nCollected At: {fact.collected_at}"
            
            existing_ev = db.session.execute(
                db.select(ProjectEvidence).filter_by(
                    project_id=project.id,
                    integration_fingerprint=fact.fingerprint,
                    name=ev_name
                )
            ).scalars().first()
            
            if not existing_ev:
                ev = ProjectEvidence(
                    project_id=project.id,
                    tenant_id=project.tenant_id,
                    name=ev_name,
                    description=desc,
                    content=content,
                    kind="integration_artifact",
                    status="proposed",
                    source=f"{source}:{subject}",
                    integration_fingerprint=fact.fingerprint
                )
                db.session.add(ev)
                db.session.flush()
                
                for pc in control_map[ref_code]:
                    for sc in pc.subcontrols:
                        if sc.is_applicable:
                            assoc = EvidenceAssociation(
                                evidence_id=ev.id,
                                control_id=sc.id,
                                requirement_slot=slot
                            )
                            db.session.add(assoc)
                            
                created_count += 1
        else:
            # Stage 6 - Drift Degradation
            # If the rule fails now, but there's accepted evidence from this source, we must demote it.
            existing_evs = db.session.execute(
                db.select(ProjectEvidence).filter_by(
                    project_id=project.id,
                    source=f"{source}:{subject}",
                    kind="integration_artifact",
                    status="accepted"
                )
            ).scalars().all()
            
            for ex in existing_evs:
                ex.status = "proposed"
                ex.rejection_reason = f"System detected drift. Previous fact no longer holds. New data: {fact.assertion} (Collected At: {fact.collected_at}). Rule failed."
                logger.warning(f"Drift detected for subcontrols on {ref_code}. Demoted evidence {ex.id} to proposed.")
                
                # Drop verified state on connected subcontrols
                assocs = db.session.execute(
                    db.select(EvidenceAssociation).filter_by(evidence_id=ex.id)
                ).scalars().all()
                
                for assoc in assocs:
                    from app.models.project import ProjectSubControl
                    sc = db.session.get(ProjectSubControl, assoc.control_id)
                    if sc and sc.verified_at:
                        sc.verified_at = None
                        sc.verified_by_id = None
                        sc.verification_note = (sc.verification_note or "") + f"\n\n[System] Drift detected on {fact.collected_at}, automatically unverifying subcontrol."
                
    db.session.commit()
    return created_count
