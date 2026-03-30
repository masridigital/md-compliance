"""
Masri Digital Compliance Platform — Package Init

This package contains all Phase 1 Masri extensions:
  - new_models: SQLAlchemy models for settings, branding, WISP, MCP, etc.
  - settings_service: Service layer for settings CRUD + encryption
  - settings_routes: Flask blueprint for /api/v1/settings/*
  - wisp_routes: Flask blueprint for /api/v1/wisp/*
  - mcp_server: Flask blueprint for /mcp/*
  - storage_providers: Multi-provider file storage abstraction
  - notification_engine: Multi-channel notification dispatcher
  - llm_service: Multi-provider LLM abstraction
  - context_processors: Jinja2 context processors (branding, tenant, config)
  - config_additions: Additional config keys (MASRI_CONFIG dict)
"""
