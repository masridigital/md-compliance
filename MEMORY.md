# MD Compliance — Session Memory

Last updated: 2026-04-06

## Current Phase: B/C (Technical Debt + Product Roadmap)

### Completed This Session (2026-04-06)

**Phase A (Architecture Hardening) — ALL 7 STEPS COMPLETE:**
- Step 1: Decoupled integrations with `run_mode` (telivy_only | microsoft_only | ninjaone_only | defensx_only | full)
- Step 2: Job stage tracking (`_update_job_status()`), 15 min poll timeout, chunk progress in UI
- Step 3: `prompt_adapters.py` — 7 model-family adapters (Claude, DeepSeek, Llama, Kimi, Gemma, Qwen, Default)
- Step 4: Adapters wired into `LLMService.chat()` + chunk size in `_run_chunked_llm`
- Step 6: Redis-backed log viewer (LPUSH/LTRIM, in-memory fallback, worker ID)

**Phase B (Technical Debt):**
- B3: CI/CD pipeline — `.github/workflows/ci.yml` + `deploy.yml`
- B4: PCI DSS v4.0 — pending (agent timed out on large file generation)

**Integration Pipeline — NinjaOne + DefensX FULLY WIRED:**
- Data collection in `_bg_auto_process` with credential validation guards
- LLM Phase 3 (NinjaOne: patches, AV, encryption, devices)
- LLM Phase 4 (DefensX: web filtering, shadow AI, credential events)
- Phase 5: Cross-source analysis with dynamic source listing
- `_compress_for_llm`: NinjaOne + DefensX sections
- Daily scheduler refresh includes all 4 integrations
- UI cards on `view_project.html` integrations tab (devices, patches, AV, threats, resilience score, shadow AI)
- API endpoint `integration-data` returns NinjaOne + DefensX from ConfigStore cache

**Bug Fixes:**
- 3 NameError bugs: `_json` used out of scope in `assist_gaps_status`, `auto_process_status`, `get_integration_data`
- Evidence labels: generic "Integration" instead of hardcoded "Telivy"
- Empty credential guards on NinjaOne + DefensX collection
- `scan_type` allowlist validation

**Tests + Docs:**
- `tests/test_prompt_adapters.py` (21 passing tests)
- MEMORY.md + PHASES.md created
- CLAUDE.md fully updated

### Git Log (This Session)
```
5f3c675 Add NinjaOne + DefensX UI cards to project integrations tab
680832a Update docs: B4 PCI v4.0 still pending
5653ad0 Fix evidence source labels
5abb7b8 Update MEMORY.md
e7791a6 Fix NameError bugs: _json used out of scope in 3 endpoints
7471078 Extend run_mode to support ninjaone_only and defensx_only
0b54781 Phase A/B: Redis log viewer, CI/CD, NinjaOne+DefensX LLM phases
3907ea9 Complete Phase A Steps 1-4: decouple integrations, job stages, prompt adapters
```

### Remaining Work (Priority Order)
1. **B4**: PCI DSS v4.0 framework JSON (needs manual creation — agent timed out)
2. **B2**: Migrate scheduler from threading.Timer to Celery/Redis
3. NinjaOne + DefensX re-run buttons on view_project.html
4. Phase C1: Automated evidence collection from existing data
5. Phase C4: Additional compliance frameworks (GDPR, CCPA, ABA, HITRUST)
