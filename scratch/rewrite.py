import json

with open("app/masri/llm_routes.py", "r") as f:
    text = f.read()

# Swap F3/F4 to the top
old_loop_start = """        for project in projects:
            controls = []
            for pc in project.controls.all():
                ctrl = pc.control
                if ctrl:
                    controls.append({
                        "project_control_id": pc.id,
                        "ref_code": ctrl.ref_code or "",
                        "name": ctrl.name or "",
                        "description": ctrl.description or "",
                    })
            if not controls:
                continue"""

new_loop_start = """        for project in projects:
            # Phase F3 & F4: Generate facts and map deterministically before LLM
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
                    # ONLY send subcontrols to LLM if they are applicable, unverified, and have NO mapped evidence from Stage 3
                    if sc.is_applicable and not sc.verified_at and not sc.evidence.count():
                        controls.append({
                            "project_control_id": pc.id,
                            "subcontrol_id": sc.id,
                            "ref_code": f"{ctrl.ref_code if ctrl else ''} - {sc.title}",
                            "name": sc.title or "",
                            "description": sc.description or "",
                        })
            if not controls:
                continue"""

text = text.replace(old_loop_start, new_loop_start)

# Globally rename all_mappings to all_suggestions
text = text.replace('all_mappings', 'all_suggestions')

# String replacements for JSON keys in the prompts
text = text.replace('{"mappings":', '{"ai_suggestions":')
text = text.replace('{\\"mappings\\":', '{\\"ai_suggestions\\":')
text = text.replace('project_control_id', 'subcontrol_id') # Change the expected output variable
text = text.replace('status":"compliant|partial|non_compliant"', 'suggested_evidence_type":"[type of evidence required]"}')

# Fix prompt notes to suggestion_text and rationale
text = text.replace('"notes":"Telivy: [finding name] - [grade/count/severity]. [What this means]",', '"suggestion_text":"Telivy: [finding]","rationale":"[detailed reasoning]",')
text = text.replace('"notes":"Microsoft: [data point with numbers]. [What this means for compliance]",', '"suggestion_text":"Microsoft: [finding]","rationale":"[detailed reasoning]",')
text = text.replace('"notes":"NinjaOne finding: [specific data point]",', '"suggestion_text":"NinjaOne: [finding]","rationale":"[detailed reasoning]",')
text = text.replace('"notes":"DefensX finding: [specific data point]",', '"suggestion_text":"DefensX: [finding]","rationale":"[detailed reasoning]",')
text = text.replace('"notes":"Cross-source: [Source A] shows [X] + [Source B] shows [Y] = [conclusion]",', '"suggestion_text":"Cross-source: [finding]","rationale":"[detailed reasoning]",')


new_apply = """                    _update_job_status(tenant_id, "generating_evidence", f"Processing {len(all_suggestions)} LLM AI suggestions")
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
                            logger.warning("AI suggestion saving failed for subcontrol %s: %s", m.get("subcontrol_id", "?"), _map_err)

                    # Add risks"""

start_str = '                    _update_job_status(tenant_id, "generating_evidence", f"Applying {len(all_suggestions)} mappings + generating evidence")'
start_idx = text.find(start_str)
end_str = '                    # Add risks'
end_idx = text.find(end_str, start_idx)

if start_idx != -1 and end_idx != -1:
    text = text[:start_idx] + new_apply + text[end_idx + len(end_str):]
else:
    print("Failed to find mapping apply block!")

# Finally, remove the F3 and F4 block at the bottom
end_old_f3_f4 = """                    _update_job_status(tenant_id, "syncing_progress", f"Syncing progress for {project.name if hasattr(project, 'name') else project.id}")
                    # Sync ALL subcontrol progress for this project
                    _sync_project_progress(db, project, ProjectControl, ProjectSubControl)
                    db.session.commit()

                    # Generate automated evidence from integration data
                    _update_job_status(tenant_id, "generating_evidence", f"Generating facts for {project.name if hasattr(project, 'name') else project.id}")
                    try:
                        from app.masri.evidence_generators import generate_all_evidence
                        facts_count = generate_all_evidence(db, project, tenant_id)
                        if facts_count:
                            logger.info("Generated %d integration facts for project %s", facts_count, project.id)
                            
                        # Run Stage 3 - Rule-Based Mapper
                        from app.masri.rule_mapper import run_mapper
                        ev_count = run_mapper(db, project)
                        if ev_count:
                            logger.info("Mapped %d pieces of evidence for project %s", ev_count, project.id)
                            
                    except Exception as ev_err:
                        logger.warning("Evidence generation/mapping failed for project %s: %s", project.id, ev_err)"""

end_new = """                    # DB Session Commit (progress sync is automatic via continuous monitor)
                    db.session.commit()"""

text = text.replace(end_old_f3_f4, end_new)


with open("app/masri/llm_routes.py", "w") as f:
    f.write(text)
print("File rewritten successfully")
