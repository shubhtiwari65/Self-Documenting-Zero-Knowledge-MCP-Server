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
