# MD Compliance — Session Memory

Last updated: 2026-04-06

## Current Phase: B (Technical Debt) — nearly complete

### Completed This Session (2026-04-06)

**Phase A (Architecture Hardening) — ALL COMPLETE:**
- Step 1: Decoupled integrations with `run_mode` parameter (telivy_only | microsoft_only | ninjaone_only | defensx_only | full)
- Step 2: Job stage tracking (`_update_job_status()`), ConfigStore-backed, 15 min poll timeout, chunk progress in UI
- Step 3: Created `prompt_adapters.py` with 7 model-family adapters (Claude, DeepSeek, Llama, Kimi, Gemma, Qwen, Default)
- Step 4: Wired adapters into `LLMService.chat()` (auto-adapts all calls) + chunk size adaptation in `_run_chunked_llm`
- Step 6: Redis-backed log viewer (LPUSH/LTRIM with in-memory fallback, worker ID for multi-worker attribution)

**Phase B (Technical Debt):**
- B3: CI/CD pipeline — `.github/workflows/ci.yml` (ruff lint, bandit security scan, syntax check, pytest) + `deploy.yml` (Docker build)
- B4: PCI DSS v4.0 framework JSON (in progress via agent)

**Integration Pipeline:**
- NinjaOne RMM + DefensX fully wired into `_bg_auto_process` pipeline
- LLM Phase 3 (NinjaOne: patches, AV, encryption, devices) + Phase 4 (DefensX: web filtering, shadow AI, credential events)
- Phase 5: Cross-source analysis updated to dynamically list all active sources
- `_compress_for_llm`: NinjaOne + DefensX sections added
- Daily scheduler refresh now includes NinjaOne + DefensX data pull
- Credential validation guards added (skip API calls if empty credentials)

**Tests + Docs:**
- Created `tests/test_prompt_adapters.py` (21 passing tests)
- Created MEMORY.md + PHASES.md session tracking files
- CLAUDE.md updated with all completions

**Security Fixes:**
- `scan_type` allowlist validation
- Sanitized error strings in ConfigStore (no raw exception details)
- Empty credential guards on NinjaOne + DefensX collection

### Previously Completed
- Phase A Steps 5 & 7 (Docker safety, storage hardening) — 2026-04-05
- B1: PDF report generation with WeasyPrint — 2026-04-05
- NinjaOne RMM + DefensX integration clients — 2026-04-05

### Remaining Work
- **B2**: Migrate scheduler from threading.Timer to Celery/Redis (HIGH)
- **B4**: PCI DSS v4.0 framework (agent working on it)
- NinjaOne + DefensX UI cards on `view_project.html` integrations tab
- **Phase C items** (product roadmap — see PHASES.md)

### Git Log (This Session)
```
7471078 Extend run_mode to support ninjaone_only and defensx_only
0b54781 Phase A/B: Redis log viewer, CI/CD, NinjaOne+DefensX LLM phases
3907ea9 Complete Phase A Steps 1-4: decouple integrations, job stages, prompt adapters
```
