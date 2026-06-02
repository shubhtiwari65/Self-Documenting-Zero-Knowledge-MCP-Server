# Technical Approach — Self-Documenting Zero-Knowledge MCP Server

## Problem Statement

Build an MCP server that:
1. Autonomously scans an undocumented legacy database
2. Generates CRUD tools for every table
3. Creates prompts explaining how to join tables
4. Enforces Zero-Knowledge security by restricting the LLM to pre-validated SQL templates only

## Approach Overview

The server follows a **pipeline architecture** where each phase builds on the previous one:

```
Database → Introspection → Schema Registry → Template Generation → Security Layer → MCP Tools/Prompts
```

This design ensures complete separation of concerns: the introspector knows nothing about MCP, the template engine knows nothing about security enforcement, and the CRUD generator knows nothing about SQL — it only works with template IDs.

## Tools & Frameworks

### Core Framework: MCP Python SDK (`mcp` with FastMCP)

**Why**: FastMCP is the official high-level API for building MCP servers in Python. It provides:
- Decorator-based tool/prompt/resource registration (`@mcp.tool()`, `@mcp.prompt()`, `@mcp.resource()`)
- Built-in transport handling (stdio for Claude Desktop, SSE for network)
- Automatic JSON schema generation for tool parameters
- MCP Inspector integration for testing

**Alternative considered**: Building a raw JSON-RPC server. Rejected because FastMCP handles all protocol details and is the recommended approach per the MCP specification.

### Database: SQLite (via Python's `sqlite3`)

**Why**: 
- Zero configuration — perfect for demonstrating against an "undocumented legacy" database
- Built-in Python support — no external database server needed
- Full PRAGMA introspection support for autonomous schema discovery
- Portable — the entire database is a single file
- Foreign key support (with `PRAGMA foreign_keys = ON`)

**Alternative considered**: PostgreSQL. While more realistic for production, it would require external setup and configuration, adding friction to evaluation. The architecture is database-agnostic and could be adapted.

### Schema Discovery: SQLite PRAGMA Statements

**Why**: PRAGMAs are the native introspection mechanism for SQLite:
- `PRAGMA table_info()` — Column names, types, nullability, defaults, primary keys
- `PRAGMA foreign_key_list()` — Foreign key relationships
- `PRAGMA index_list()` / `PRAGMA index_info()` — Index metadata
- `sqlite_master` — Table enumeration

**Alternative considered**: SQLAlchemy's `automap` or `inspect()`. Rejected because it adds a heavy ORM dependency when we only need schema metadata, and using raw PRAGMAs better demonstrates the "zero-knowledge" concept — the server truly starts with no prior knowledge.

### Validation: Pydantic

**Why**: Used for structured data validation and type checking of parameters. Lightweight and integrates naturally with the MCP SDK.

## Key Design Decisions

### 1. Template-Based Security (Zero-Knowledge)

The core security innovation is that **no raw SQL ever reaches the database**. Instead:

1. At startup, the server generates all valid SQL templates from the introspected schema
2. Each template is a parameterized query with `?` placeholders
3. Templates are stored in a registry with unique IDs
4. The LLM can only reference template IDs and provide typed parameters
5. The security validator verifies the template exists, checks parameter types, sanitizes values, then executes

This means even if the LLM is compromised or manipulated, it cannot construct arbitrary SQL — it can only invoke pre-approved operations.

### 2. Defense-in-Depth Input Sanitization

Even though parameterized queries prevent SQL injection by design, the security layer includes a defense-in-depth blocklist that checks parameter values for dangerous patterns (e.g., `UNION SELECT`, `DROP TABLE`, SQL comments). This provides an extra safety net against novel attack vectors.

### 3. Dynamic Tool Registration

Tools are registered dynamically at startup using Python closures. Each tool function captures its table name and template ID, then delegates to the security validator. This means:
- Adding a table to the database = automatic new tools on next restart
- No code changes needed to support new schemas
- The server truly self-documents

### 4. Relationship Detection

The join analyzer goes beyond simple FK enumeration:
- **One-to-Many**: Detected from direct FK relationships (e.g., orders → customers)
- **Many-to-Many**: Detected by identifying junction tables (tables with 2+ FKs and few own columns, e.g., order_items connecting orders ↔ products)
- Human-readable prompts explain each relationship with example SQL

### 5. Audit Logging

Every database operation is recorded in an in-memory audit log with:
- Timestamp, template ID, operation type, table name
- Parameters used (for debugging)
- Success/failure status and error messages
- Row count for read operations

The audit log is exposed as an MCP resource (`security://audit-log`) so the LLM can report on its own activity.

## Security Guarantees

| Threat | Mitigation |
|:-------|:-----------|
| SQL Injection | Parameterized queries + defense-in-depth blocklist |
| Arbitrary SQL Execution | Template-only execution (no raw SQL endpoint) |
| Schema Manipulation | No DDL templates generated (no CREATE/ALTER/DROP) |
| Data Exfiltration | Pagination limits on list operations (max 100 rows) |
| Privilege Escalation | No admin/system operations exposed |
| Audit Evasion | All operations logged before execution |

### How Zero-Knowledge Enforcement Works (Code-Level)

The critical security guarantee is that **there is no code path in the entire system** where raw SQL can be executed. Here's how the enforcement is layered:

**1. Single entry point for all database access:**

The `ZeroKnowledgeValidator.validate_and_execute()` method in `src/security.py` is the **only** function in the entire codebase that calls `conn.execute()` with application SQL. There is no alternative execution path.

```python
# src/security.py — the ONLY place SQL runs
def validate_and_execute(self, template_id: str, params: dict) -> list[dict]:
    template = self.template_registry.get(template_id)  # Step 1: lookup
    if not template:
        raise SecurityError(...)  # REJECT unknown templates
    self._validate_params(params, template)              # Step 2: type-check
    self._sanitize_params(params)                        # Step 3: blocklist
    ordered_params = self._build_ordered_params(...)     # Step 4: order
    cursor = conn.execute(template.sql, ordered_params)  # Step 5: execute
```

**2. No raw SQL accepted anywhere:**

- The MCP tools (`src/crud_generator.py`) only pass `template_id` strings and `params` dicts to the validator — they never construct SQL.
- The template registry (`src/sql_templates.py`) is populated once at startup and is immutable at runtime.
- The `conn.execute()` call inside `_get_connection()` only runs `PRAGMA foreign_keys = ON` — a fixed, hardcoded safety setting, not user-supplied SQL.

**3. Five-layer validation before any query runs:**

| Layer | Check | Blocks |
|:------|:------|:-------|
| Template lookup | Is `template_id` in the registry? | Any arbitrary/unknown query |
| Param presence | Are all required params provided? | Missing fields |
| Param restriction | Are there any extra params? | Parameter injection |
| Type validation | Does each param match expected SQLite type? | Type confusion attacks |
| Pattern blocklist | Do string params contain `DROP`, `UNION SELECT`, `--`, etc.? | Defense-in-depth |

**4. Why this qualifies as "Zero-Knowledge":**

The LLM has **zero knowledge** of the underlying SQL. It only sees:
- Tool names like `list_customers`, `read_orders`
- Parameter names like `id`, `limit`, `offset`
- Structured results as JSON

It never sees, generates, or has the ability to influence the SQL string itself. The SQL exists only inside the pre-compiled template registry.

## Why FastMCP Over Raw MCP SDK

| Feature | FastMCP | Raw JSON-RPC |
|:--------|:--------|:-------------|
| Tool registration | `@mcp.tool()` decorator | Manual JSON schema + handler mapping |
| Transport handling | Built-in stdio/SSE | Implement from scratch |
| Prompt support | `@mcp.prompt()` decorator | Manual prompt protocol |
| Type inference | Automatic from Python signatures | Manual JSON Schema |
| Inspector integration | `mcp dev server.py` | Not available |
| Lines of boilerplate | ~5 lines | ~200+ lines |

FastMCP is the official recommendation from the MCP specification and reduces boilerplate by 95%, letting us focus on the core logic (introspection, security, CRUD generation) rather than protocol plumbing.

## Why SQLite PRAGMA for Introspection

| Approach | Pros | Cons |
|:---------|:-----|:-----|
| **PRAGMA (chosen)** | Zero dependencies, native to SQLite, truly "zero-knowledge" | SQLite-specific |
| SQLAlchemy automap | Database-agnostic | Heavy ORM dependency, not truly "zero-knowledge" |
| Manual SQL queries | Simple | Fragile, error-prone |

PRAGMAs give us everything needed with zero external dependencies:
- `SELECT name FROM sqlite_master WHERE type='table'` — discover tables
- `PRAGMA table_info(X)` — columns, types, PKs, nullability, defaults
- `PRAGMA foreign_key_list(X)` — foreign key relationships
- `PRAGMA index_list(X)` + `PRAGMA index_info(X)` — indexes

This aligns with the "zero-knowledge" philosophy: the server starts knowing nothing and discovers everything at runtime.

## Design Tradeoffs

| Decision | Tradeoff | Rationale |
|:---------|:---------|:----------|
| SQLite only | Not production-DB ready | Portable, zero-config, perfect for assessment demo |
| In-memory audit log | Lost on restart | Keeps dependencies minimal; production would use persistent storage |
| All columns in UPDATE | Must pass all fields | Simpler template generation; partial updates would double template count |
| Max 100 rows per LIST | Can't bulk export | Security: prevents data exfiltration via large queries |
| Immutable templates | No runtime schema changes | Security: templates can't be modified after startup |

## Testing Strategy

Four test suites cover the critical paths:

1. **test_introspector.py** — Schema discovery: tables, columns, PKs, FKs, types, nullability
2. **test_crud.py** — CRUD operations: template generation, list/read/create/update/delete, search
3. **test_security.py** — Security: unknown templates rejected, SQL injection blocked, param validation, audit logging
4. **test_joins.py** — Relationships: FK detection, junction tables, join execution, schema summaries

## Extensibility

The architecture supports several extensions:
- **Multiple databases**: Run multiple introspectors and merge registries
- **PostgreSQL/MySQL**: Replace PRAGMA introspection with `information_schema` queries
- **Row-level security**: Add user context to the validator for per-user access control
- **Caching**: Add a query cache layer between the validator and database
- **Webhooks**: Emit events on write operations for downstream processing

