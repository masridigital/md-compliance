# MD Compliance — Implementation Plan

## Context
User reports: (1) Telivy scan analysis consistently times out showing "Timed out — check project for results", (2) same for risk assessments, (3) LLM prompts are generic — no model-family adaptation, (4) processing is too slow and should work when logged out. This plan fixes the timeout architecture, adds model-specific prompt adapters, decouples integrations, and hardens supporting systems.

---

## Execution Order (by impact)

| Step | What | Files | Size | Blocks |
|------|------|-------|------|--------|
| 1 | Decouple Telivy from Microsoft | `llm_routes.py`, `integrations.html` | Medium | Nothing |
| 2 | Add job stages + extend poll | `llm_routes.py`, `integrations.html`, `view_project.html` | Large | Step 1 |
| 3 | Create prompt adapter layer | New `prompt_adapters.py`, `llm_service.py` | Large | Nothing |
| 4 | Wire adapters into all prompts | `llm_routes.py`, `risk_profiles.py` | Medium | Step 3 |
| 5 | Fix update manager for Docker | `update_manager.py`, `settings_routes.py` | Small | Nothing |
| 6 | Redis-backed log viewer | `log_buffer.py`, `__init__.py` | Medium | Nothing |
| 7 | Storage provider hardening | `storage_providers.py`, `entra_routes.py` | Small | Nothing |
| 8 | Update CLAUDE.md | `CLAUDE.md` | Small | All above |

---

## Step 1: Decouple Telivy from Microsoft (Quick Win)

**Problem**: Clicking Re-run on a Telivy scan also collects Microsoft data (slow, unnecessary).

**Files**: `app/masri/llm_routes.py` (lines 901-970), `app/templates/integrations.html`

**Changes**:
- Add `run_mode` parameter to `auto_process` endpoint: `telivy_only | microsoft_only | full`
- `_bg_auto_process` checks `run_mode` before each collection block:
  - `run_mode=telivy_only` → skip Microsoft collection (lines 946-964) and risk profiles (lines 967-976)
  - `run_mode=microsoft_only` → skip Telivy collection (lines 916-944)
  - `run_mode=full` → collect both (current behavior)
- Frontend: Re-run on Telivy scan sends `run_mode=telivy_only`
- Frontend: Re-run on Microsoft card sends `run_mode=microsoft_only`
- LLM phases auto-skip: Phase 1 skips if no Telivy data, Phase 2 skips if no Microsoft data, Phase 3 skips if only one source

**Verification**: Re-run Telivy scan, check server logs show no Microsoft API calls, verify completion under 2 minutes

---

## Step 2: Job Stages + Extended Poll Window

**Problem**: Frontend polls 5 min (60×5s), but 100+ controls = 10+ LLM chunks × 30-90s = easily 5+ min. Backend has no stage reporting — just "processing" until done.

**Files**: `app/masri/llm_routes.py`, `app/templates/integrations.html`, `app/templates/view_project.html`

**Changes in backend (`llm_routes.py`)**:
- Add `_update_job_status(tenant_id, stage, detail)` helper that writes to ConfigStore:
  ```json
  {
    "status": "running",
    "stage": "analyzing_phase1",
    "detail": "Processing chunk 3/10 (Telivy)",
    "started_at": "2026-04-01T...",
    "updated_at": "2026-04-01T..."
  }
  ```
- Call `_update_job_status()` at each stage in `_bg_auto_process`:
  - `collecting_telivy` → `collecting_microsoft` → `computing_risk_profiles` → `analyzing_phase1` → `analyzing_phase2` → `analyzing_cross_source` → `generating_evidence` → `syncing_progress` → `done`
- Store chunk progress: "3/10" so frontend can show a progress indicator

**Changes in frontend (`integrations.html`)**:
- Extend poll timeout from 60 to 180 polls (15 minutes)
- Show stage name: "Analyzing Telivy data (3/10)..." instead of just "Processing..."
- Show elapsed time
- Result stored separately from status — poll endpoint returns both

**Changes in project view (`view_project.html`)**:
- "Re-pull & Analyze" button shows stage progress too

**Verification**: Run full analysis on Masri Digital (100+ controls), observe stage progression, verify no timeout within 15 min

---

## Step 3: Create Prompt Adapter Layer

**Problem**: All prompts identical regardless of model. Claude needs strict structure + evidence citation. DeepSeek needs narrow JSON schemas. Kimi handles broad context but needs rigid output. Gemma needs tiny chunks.

**New file**: `app/masri/prompt_adapters.py`

**Adapter classes**:

| Adapter | Model detection | Chunk size | Temperature adj | Prompt strategy |
|---------|----------------|------------|-----------------|-----------------|
| `ClaudeAdapter` | "claude" in model | 15 | Keep or lower | Add XML tags, evidence citations, confidence levels, conservative conclusions |
| `DeepSeekAdapter` | "deepseek" | 8 | 0.1 max | Single objective per call, explicit JSON schema with example |
| `LlamaAdapter` | "llama" or "meta-llama" | 10 | Keep | Emphasize JSON-only output, add "no explanation" instruction |
| `KimiAdapter` | "kimi" or "moonshot" | 12 | Keep | Allow broader context, rigid output contract, explicit field list |
| `GemmaAdapter` | "gemma" | 5 | 0.1 max | Extractive only, no cross-source reasoning, minimal objectives |
| `QwenAdapter` | "qwen" | 10 | Keep | Similar to Llama, good JSON, add structured examples |
| `DefaultAdapter` | fallback | 10 | Keep | Current behavior (no change) |

**Each adapter provides**:
- `adapt_system(prompt, task_type)` — transforms system prompt for model family
- `adapt_chunk_size(default)` — adjusts control batch size
- `adapt_temperature(default)` — adjusts for model capabilities
- `adapt_json_instruction()` — model-specific JSON output instructions
- `adapt_max_tokens(default)` — adjust token limits

**Integration in `llm_service.py`**:
- In `chat()` method, after loading config: `adapter = get_adapter(model_id)`
- Adapt messages before sending to provider
- Log which adapter was used

**Verification**: Run same scan with Together AI (Llama), then Anthropic (Claude), compare output quality and JSON reliability

---

## Step 4: Wire Adapters Into All Prompts

**Files**: `app/masri/llm_routes.py`, `app/masri/risk_profiles.py`, `app/masri/model_recommender.py`

**Prompts to adapt** (10 total):
1. Phase 1: Telivy analysis prompt (`llm_routes.py:1057-1079`)
2. Phase 2: Microsoft analysis prompt (`llm_routes.py:1081-1110`)
3. Phase 3: Cross-source prompt (`llm_routes.py:1112-1141`)
4. Assist-gaps recommendations (`llm_routes.py:571-601`)
5. Risk narratives (`risk_profiles.py:148-171`)
6. Model recommender (`model_recommender.py:358-398`)
7. Control assessment (`llm_service.py:553-592`)
8. Policy drafting (`llm_service.py:595-628`)
9. Gap narrative (`llm_routes.py:132-170`)
10. Risk scoring (`llm_routes.py:200-270`)

**For each prompt**: Pass through `adapter.adapt_system()` before sending, use `adapter.adapt_chunk_size()` for chunked calls, use `adapter.adapt_json_instruction()` for JSON output requests.

**Verification**: Run assist-gaps with Claude, verify structured output with evidence citations. Run auto-map with Llama, verify clean JSON.

---

## Step 5: Update Manager Docker Safety

**Files**: `app/masri/update_manager.py`, `app/masri/settings_routes.py`

**Changes**:
- `UpdateManager.apply()` does ONLY `git pull` (no pip install, no migrate, no SIGHUP)
- Sets flag in ConfigStore: `update_pending=true`
- Returns: "Code updated. Run `docker-compose up -d --build` to apply."
- System page shows banner: "Update pulled — container rebuild required"

**Verification**: Click "Update Now", verify no pip install runs, verify message shown

---

## Step 6: Redis-Backed Log Viewer

**Files**: `app/masri/log_buffer.py`, `app/__init__.py`

**Changes**:
- `BufferHandler.emit()` pushes to Redis LIST `md_compliance:logs` (LPUSH + LTRIM to 500)
- `get_recent_logs()` reads from Redis (LRANGE)
- Keep redaction logic before push
- Fallback to in-memory deque if Redis unavailable
- Add worker ID to each log entry for debugging

**Verification**: Open System page, trigger requests on different endpoints, verify all logs appear regardless of which worker handled the request

---

## Step 7: Storage & Integration Hardening

**File**: `app/masri/storage_providers.py`
- Azure: Add `self.container_client.create_container()` in `__init__` with `try/except ResourceExistsError`
- SharePoint: Validate `site_url` has `/sites/` path before Graph call
- Egnyte: Strip `https://` and `.egnyte.com` from domain input

**File**: `app/masri/entra_routes.py`
- Wrap CSP import loop in `db.session.begin_nested()` savepoint
- Return per-item results: `[{name, status: "created"|"mapped"|"failed", error}]`

**Verification**: Test Azure upload to non-existent container, test Egnyte with full URL input, test CSP import twice (idempotent)

---

## Step 8: Update CLAUDE.md

Add sections:
- Prompt adapter architecture (adapter classes, detection, integration)
- Auto-process run modes (telivy_only, microsoft_only, full)
- Job status model (stages, progress, ConfigStore key)
- Updated prompt strategy per model family (table)
- Global risk dashboard spec (pending feature from earlier session)
- Updated "Things to NEVER Do" rules (#13: never use same prompt for all model families)
