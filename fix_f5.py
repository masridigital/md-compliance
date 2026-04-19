import re

with open("app/masri/llm_routes.py", "r") as f:
    content = f.read()

# 1. Move evidence generation and mapping to the start of the project loop
new_loop_start = """        for project in projects:
            _update_job_status(tenant_id, "generating_evidence", f"Extracting facts and running mapper for {project.name if hasattr(project, 'name') else project.id}")
            try:
                from app.masri.evidence_generators import generate_all_evidence
                facts_count = generate_all_evidence(db, project, tenant_id)
                if facts_count:
                    logger.info("Generated %d integration facts for project %s", facts_count, project.id)
                from app.masri.rule_mapper import run_mapper
                ev_count = run_mapper(db, project)
                if ev_count:
                    logger.info("Mapped %d pieces of evidence for project %s", ev_count, project.id)
            except Exception as ev_err:
                logger.warning("Evidence generation/mapping failed for project %s: %s", project.id, ev_err)

            controls = []
            for pc in project.controls.all():
                ctrl = pc.control
                for sc in pc.subcontrols:
                    if sc.is_applicable and not sc.verified_at and len(sc.evidence) == 0:
                        controls.append({
                            "project_control_id": pc.id,
                            "subcontrol_id": sc.id,
                            "ref_code": f"{ctrl.ref_code if ctrl else ''} - {sc.title}",
                            "name": sc.title or "",
                            "description": sc.description or "",
                        })
            if not controls:
                continue"""

content = re.sub(
    r'        for project in projects:.*?if not controls:\n                continue',
    lambda m: new_loop_start,
    content,
    flags=re.DOTALL
)

# 2. Update prompts
content = content.replace('"mappings":', '"ai_suggestions":')
content = content.replace('all_mappings = []', 'all_suggestions = []')
content = content.replace('all_mappings, all_risks = _run_chunked_llm(', 'all_suggestions, all_risks = _run_chunked_llm(')
content = content.replace('all_mappings, all_risks, "auto_map",', 'all_suggestions, all_risks, "auto_map",')
content = content.replace('len(all_mappings)', 'len(all_suggestions)')

content = re.sub(
    r'"JSON: \{\\"ai_suggestions\\":\[\{\\"project_control_id\\":\\"ID\\",.*?\\"status\\":\\"compliant\|partial\|non_compliant\\"\}\],',
    lambda m: r'"JSON: {\\"ai_suggestions\\":[{\\"subcontrol_id\\":\\"ID\\",\\"suggestion_text\\":\\"What to do\\",\\"rationale\\":\\"Why\\",\\"suggested_evidence_type\\":\\"Type of evidence\\"}],',
    content,
    flags=re.DOTALL
)

# Replace old Mapping application
old_mapping_apply = r'                    _update_job_status\(tenant_id, "generating_evidence", f"Applying \{len\(all_suggestions\)\} ai_suggestions \+ generating evidence"\).*?_sync_project_progress\(db, project, ProjectControl, ProjectSubControl\)\n                    db\.session\.commit\(\)'
# Note: we used replace above so 'Applying {len(all_mappings)} mappings' became 'Applying {len(all_suggestions)} ai_suggestions'

new_mapping_apply = """                    _update_job_status(tenant_id, "generating_evidence", f"Saving {len(all_suggestions)} AI suggestions")
                    from app.models.project import AiSuggestion
                    for m in all_suggestions:
                        try:
                            sc_id = m.get("subcontrol_id")
                            if sc_id:
                                sugg = AiSuggestion(
                                    project_id=project.id,
                                    subject_type="ProjectSubControl",
                                    subject_id=sc_id,
                                    kind="integration_hint",
                                    payload={
                                        "suggestion_text": m.get("suggestion_text", ""),
                                        "rationale": m.get("rationale", ""),
                                        "suggested_evidence_type": m.get("suggested_evidence_type", "")
                                    },
                                    status="pending"
                                )
                                db.session.add(sugg)
                                total_mapped += 1
                        except Exception as _map_err:
                            logger.warning("AI suggestion save failed: %s", _map_err)

                    # Add risks
                    _SEV = {"critical": "critical", "high": "high", "medium": "moderate", "low": "low"}
                    for r in all_risks:
                        try:
                            title = r.get("title", "")
                            import re as _re
                            title = _re.sub(r'^(Critical|High|Medium|Moderate|Low):\s*', '', title, flags=_re.IGNORECASE).strip()
                            if title:
                                th = RiskRegister._compute_title_hash(title, tenant_id)
                                dup = db.session.execute(
                                    db.select(RiskRegister).filter_by(title_hash=th, tenant_id=tenant_id)
                                ).scalars().first()
                                if dup:
                                    continue
                                risk = RiskRegister(
                                    title=title, title_hash=th,
                                    summary=r.get("summary", ""),
                                    description=r.get("description", ""),
                                    evidence_data=r.get("evidence_data", []),
                                    risk=_SEV.get(r.get("severity", "").lower(), "unknown"),
                                    tenant_id=tenant_id, project_id=project.id,
                                )
                                db.session.add(risk)
                                total_risks += 1
                        except Exception as _risk_err:
                            logger.warning("Risk creation failed for '%s': %s",
                                           r.get("title", "?")[:50], _risk_err)
                                           
                    # We no longer sync progress from LLM edits since LLM doesn't edit them!
                    db.session.commit()"""

content = re.sub(old_mapping_apply, lambda m: new_mapping_apply, content, flags=re.DOTALL)

# Phase 5 cross source mapped IDs block:
content = re.sub(
    r'mapped_ids = \{m\.get\("project_control_id"\) for m in all_suggestions.*?unmapped = \[c for c in controls if c\["project_control_id"\] not in mapped_ids\]',
    lambda m: r'mapped_ids = {m.get("subcontrol_id") for m in all_suggestions}\n                        unmapped = [c for c in controls if c["subcontrol_id"] not in mapped_ids]',
    content,
    flags=re.DOTALL
)

# Remove the bottom generate_all_evidence and run_mapper since they moved
content = re.sub(
    r'                    # Generate automated evidence from integration data\n.*?logger\.warning\("Evidence generation/mapping failed for project %s: %s", project\.id, ev_err\)',
    '',
    content,
    flags=re.DOTALL
)

with open("app/masri/llm_routes.py", "w") as f:
    f.write(content)
print("done")
