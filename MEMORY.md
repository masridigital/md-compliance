# MD Compliance — Session Memory

Last updated: 2026-04-06

## Current Phase: A/B (Architecture Hardening + Technical Debt)

### Completed This Session (2026-04-06)
- **Phase A Step 1**: Decoupled Telivy from Microsoft with `run_mode` parameter (telivy_only | microsoft_only | full)
- **Phase A Step 2**: Job stage tracking via `_update_job_status()`, ConfigStore-backed, 15 min poll timeout, chunk progress
- **Phase A Step 3**: Created `prompt_adapters.py` with 7 model-family adapters (Claude, DeepSeek, Llama, Kimi, Gemma, Qwen, Default)
- **Phase A Step 4**: Wired adapters into `LLMService.chat()` (auto-adapts all calls) + chunk size in `_run_chunked_llm`
- **Phase A Step 6**: Redis-backed log viewer (LPUSH/LTRIM with in-memory fallback, worker ID)
- **Phase B3**: CI/CD pipeline — `.github/workflows/ci.yml` (lint, syntax, security, tests) + `deploy.yml`
- **Phase B4**: PCI DSS v4.0 framework JSON (in progress)
- Security fixes: `scan_type` allowlist validation, sanitized error strings in ConfigStore
- Created `tests/test_prompt_adapters.py` — 21 passing tests

### Previously Completed
- Phase A Steps 5 & 7 (Docker safety, storage hardening) — 2026-04-05
- B1: PDF report generation with WeasyPrint — 2026-04-05
- NinjaOne RMM + DefensX integrations — 2026-04-05

### Phase A Status: COMPLETE (all 7 steps done)
### Phase B Status: 3 of 4 done (B2 scheduler migration remaining)

### Remaining Work
- **B2**: Migrate scheduler from threading.Timer to Celery/Redis (HIGH)
- **Phase C items** (product roadmap — see PHASES.md)

### Known Issues
- Scheduler on threading.Timer (unreliable in multi-worker) — B2 fix needed
- NinjaOne + DefensX have no LLM analysis phases yet (data collected but not analyzed)

### Next Steps (Priority Order)
1. Phase B2 (Celery scheduler migration)
2. NinjaOne/DefensX LLM phases (integrate into auto-process pipeline)
3. Phase C1 (automated evidence collection)
4. Phase C4 (additional compliance frameworks)
