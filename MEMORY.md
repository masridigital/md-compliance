# MD Compliance — Session Memory

Last updated: 2026-04-07

## Current Phase: C (Product Roadmap)

### Completed (All Sessions)

**Phase A (Architecture Hardening) — ALL 7 STEPS COMPLETE:**
- Step 1: Decoupled integrations with `run_mode` (telivy_only | microsoft_only | ninjaone_only | defensx_only | full)
- Step 2: Job stage tracking (`_update_job_status()`), 15 min poll timeout, chunk progress in UI
- Step 3: `prompt_adapters.py` — 7 model-family adapters (Claude, DeepSeek, Llama, Kimi, Gemma, Qwen, Default)
- Step 4: Adapters wired into `LLMService.chat()` + chunk size in `_run_chunked_llm`
- Step 5: Update manager Docker safety
- Step 6: Redis-backed log viewer (LPUSH/LTRIM, in-memory fallback, worker ID)
- Step 7: Storage provider hardening

**Phase B (Technical Debt):**
- B1: PDF report generation (WeasyPrint pipeline) — DONE 2026-04-05
- B3: CI/CD pipeline — `.github/workflows/ci.yml` + `deploy.yml` — DONE 2026-04-06
- B4: PCI DSS v4.0 — 43 controls, 223 subcontrols + v3.1 deprecation support — DONE 2026-04-07

**Phase C (Product Roadmap):**
- C1: Automated evidence generators (13 generators: 6 Microsoft, 3 Telivy, 3 NinjaOne, 2 DefensX) — DONE 2026-04-07
- C4: GDPR, CCPA/CPRA, ABA Model Rules, HITRUST CSF frameworks — DONE 2026-04-07

**Integration Pipeline — ALL 4 INTEGRATIONS FULLY WIRED:**
- Telivy: Phase 1 LLM analysis + 3 evidence generators
- Microsoft Entra: Phase 2 LLM analysis + 6 evidence generators
- NinjaOne: Phase 3 LLM analysis + 3 evidence generators
- DefensX: Phase 4 LLM analysis + 2 evidence generators
- Phase 5: Cross-source analysis with dynamic source listing
- `_compress_for_llm`: All 4 integrations
- Daily scheduler refresh includes all 4 integrations
- UI cards on `view_project.html` integrations tab

**Other:**
- First-run web UI setup (admin creation moved from setup.sh)
- Celery scheduler app (`celery_app.py`) created
- Framework deprecation migration (0006)
- `tests/test_prompt_adapters.py` (21 tests)

### Remaining Work (Priority Order)
1. **C2**: Continuous monitoring (webhook receivers, config baselines, drift detection)
3. **C3**: Employee training module
4. **C5**: Cross-framework control mapping (populate `Control.mapping` field)
5. **C6**: Trust portal (client-facing compliance status page)
