# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.0.0] — 2026-06-03

### Added

#### Core Engine
- **Database Introspector** (`src/introspector.py`)
  PRAGMA-based autonomous schema discovery with zero prior knowledge
  of the target database structure — tables, columns, types, PKs, FKs

- **Schema Registry** (`src/schema_registry.py`)
  In-memory schema store built from introspection results;
  provides fast lookups for table/column metadata at runtime

- **SQL Template Generator** (`src/sql_templates.py`)
  Generates pre-validated, parameterized SQL templates at startup
  from the introspected schema — one template set per table

#### Security
- **Zero-Knowledge Validator** (`src/security.py`)
  Enforces template-only SQL execution with parameter type-checking,
  input sanitization, and a complete audit trail of every operation

#### MCP Interface
- **CRUD Generator** (`src/crud_generator.py`)
  Auto-generates 6 MCP tools per discovered table:
  `create`, `read`, `update`, `delete`, `list`, `search`

- **Join Analyzer** (`src/join_analyzer.py`)
  Reads FK relationships via PRAGMA and registers MCP prompts
  explaining how to join each pair of related tables

- **MCP Resources**
  Registered via `server.py`:
  `schema://tables`, `schema://tables/{name}`,
  `security://audit-log`, `security://report`,
  `security://templates`

#### Developer Experience
- Demo legacy e-commerce database seeder (`sample_data/seed_legacy_db.py`)
  Creates 6 tables with FK relationships and sample data via `--seed` flag
- Dual transport: stdio (Claude Desktop) and SSE (network)
- CLI flags: `--db`, `--transport`, `--port`, `--seed`
- Test suite: 4 modules — introspection, CRUD, security, join analysis
- `pyproject.toml` project metadata
- `requirements.txt` dependency pinning