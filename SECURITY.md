# Security Policy

## Zero-Knowledge Security Model

This MCP server enforces a strict **Zero-Knowledge** security model.
The LLM never constructs, sees, or executes arbitrary SQL — ever.

---

## How It Works

### Layer 1 — Template-Only Execution
Only SQL from the pre-generated template registry can execute.
There is no raw SQL endpoint. No exceptions.

### Layer 2 — Parameter Validation
Every parameter is type-checked against the introspected schema
before being passed to any template. Wrong types are rejected.

### Layer 3 — Input Sanitization
A defense-in-depth blocklist catches SQL injection patterns
in parameter values, even though parameterized queries already
prevent injection at the database driver level.

### Layer 4 — Audit Trail
Every database operation is logged with:
- Timestamp
- Template ID
- Parameters used
- Success / failure status

Accessible via the `security://audit-log` MCP resource.

### Layer 5 — No DDL
Only SELECT, INSERT, UPDATE, DELETE are permitted.
No CREATE, DROP, ALTER, or any schema manipulation is possible.

---

## What the LLM Sees vs What It Cannot Do

| The LLM CAN | The LLM CANNOT |
|---|---|
| Call named MCP tools | Write or inject SQL |
| Pass typed parameters | Access the DB directly |
| Read schema resources | Execute arbitrary queries |
| View audit logs | Modify table structure |

---

## Reporting a Vulnerability

If you discover a security issue, please open a GitHub Issue
with the label `[SECURITY]`.

**Do not include exploit code or attack details in public issues.**
Describe the class of vulnerability and we will follow up.