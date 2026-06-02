"""
Zero-Knowledge Security Validator
===================================
Enforces that the LLM can ONLY execute pre-validated SQL templates.
No raw SQL is ever allowed — the LLM never sees or constructs SQL directly.

Security guarantees:
1. Template-Only Execution: Only SQL from the template registry can run
2. Parameter Validation: All params are type-checked against the schema
3. Input Sanitization: Dangerous patterns are blocked as defense-in-depth
4. Audit Logging: Every query execution is logged with full context
5. No Raw SQL: The LLM interacts with template IDs and typed parameters only
"""

import sqlite3
import logging
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Optional

from src.sql_templates import SQLTemplate, SQLTemplateRegistry

logger = logging.getLogger(__name__)


# --- Dangerous SQL patterns (defense-in-depth blocklist) ---
DANGEROUS_PATTERNS = [
    re.compile(r";\s*DROP\s+", re.IGNORECASE),
    re.compile(r";\s*DELETE\s+", re.IGNORECASE),
    re.compile(r";\s*UPDATE\s+", re.IGNORECASE),
    re.compile(r";\s*INSERT\s+", re.IGNORECASE),
    re.compile(r";\s*ALTER\s+", re.IGNORECASE),
    re.compile(r";\s*CREATE\s+", re.IGNORECASE),
    re.compile(r"UNION\s+SELECT", re.IGNORECASE),
    re.compile(r"--\s*", re.IGNORECASE),         # SQL comments
    re.compile(r"/\*.*\*/", re.IGNORECASE),       # Block comments
    re.compile(r"xp_\w+", re.IGNORECASE),         # SQL Server extended procedures
    re.compile(r"exec\s*\(", re.IGNORECASE),      # Execute statements
    re.compile(r"ATTACH\s+DATABASE", re.IGNORECASE),
    re.compile(r"DETACH\s+DATABASE", re.IGNORECASE),
    re.compile(r"PRAGMA\s+", re.IGNORECASE),      # Prevent PRAGMA manipulation
    re.compile(r"sqlite_master", re.IGNORECASE),  # Prevent schema enumeration via SQL
]


class SecurityError(Exception):
    """Raised when a security violation is detected."""
    pass


@dataclass
class AuditLogEntry:
    """A single audit log entry for a query execution."""
    timestamp: str
    template_id: str
    operation: str
    table: str
    params: dict
    success: bool
    error: Optional[str] = None
    row_count: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "template_id": self.template_id,
            "operation": self.operation,
            "table": self.table,
            "params": self.params,
            "success": self.success,
            "error": self.error,
            "row_count": self.row_count,
        }


class ZeroKnowledgeValidator:
    """
    The core security layer of the MCP server.
    
    All database access MUST go through this validator. It ensures:
    - Only pre-registered SQL templates can be executed
    - All parameters are validated against expected types
    - All parameter values are sanitized for dangerous patterns
    - Every execution is audit-logged
    """

    # SQLite type mapping for validation
    TYPE_VALIDATORS = {
        "INTEGER": lambda v: isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()),
        "REAL": lambda v: isinstance(v, (int, float)) or _is_numeric_string(v),
        "TEXT": lambda v: isinstance(v, str),
        "BLOB": lambda v: isinstance(v, (str, bytes)),
        "TIMESTAMP": lambda v: isinstance(v, str),
        "": lambda v: True,  # Unknown type, allow anything
    }

    def __init__(self, db_path: str, template_registry: SQLTemplateRegistry):
        self.db_path = db_path
        self.template_registry = template_registry
        self.audit_log: list[AuditLogEntry] = []
        logger.info(
            f"ZeroKnowledgeValidator initialized with {template_registry.count} templates"
        )

    def _get_connection(self) -> sqlite3.Connection:
        """Create a database connection with safety settings."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def validate_and_execute(
        self, template_id: str, params: dict[str, Any]
    ) -> list[dict]:
        """
        Validate a template ID and parameters, then execute the query.
        
        This is the ONLY way to run SQL in the entire system.
        
        Args:
            template_id: The registered template ID to execute
            params: Dictionary of parameter name → value
            
        Returns:
            List of result rows as dictionaries
            
        Raises:
            SecurityError: If template is unknown, params are invalid,
                          or dangerous patterns are detected
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # Step 1: Verify template exists in registry
        template = self.template_registry.get(template_id)
        if not template:
            self._log_audit(timestamp, template_id, "UNKNOWN", "", params, False,
                           error="Unknown template ID")
            raise SecurityError(
                f"Security violation: Unknown template '{template_id}'. "
                f"Only pre-validated templates can be executed."
            )

        # Step 2: Validate parameters
        self._validate_params(params, template)

        # Step 3: Sanitize parameter values
        self._sanitize_params(params)

        # Step 4: Build ordered parameter list
        ordered_params = self._build_ordered_params(params, template)

        # Step 5: Execute the query
        try:
            conn = self._get_connection()
            try:
                cursor = conn.execute(template.sql, ordered_params)

                if template.is_write:
                    conn.commit()
                    result = [{"affected_rows": cursor.rowcount}]
                    if template.operation == "CREATE":
                        result[0]["last_insert_id"] = cursor.lastrowid
                else:
                    rows = cursor.fetchall()
                    result = [dict(row) for row in rows]

                self._log_audit(
                    timestamp, template_id, template.operation, template.table,
                    params, True, row_count=len(result)
                )
                return result
            finally:
                conn.close()

        except sqlite3.Error as e:
            self._log_audit(
                timestamp, template_id, template.operation, template.table,
                params, False, error=str(e)
            )
            raise SecurityError(f"Database error executing '{template_id}': {str(e)}")

    def _validate_params(self, params: dict[str, Any], template: SQLTemplate) -> None:
        """Validate that all required parameters are present and correctly typed."""
        # Check all required params are provided
        for param_name in template.params:
            if param_name not in params:
                raise SecurityError(
                    f"Missing required parameter '{param_name}' for template '{template.id}'. "
                    f"Required parameters: {template.params}"
                )

        # Check no extra params are provided
        allowed_params = set(template.params)
        for param_name in params:
            if param_name not in allowed_params:
                raise SecurityError(
                    f"Unexpected parameter '{param_name}' for template '{template.id}'. "
                    f"Allowed parameters: {template.params}"
                )

        # Type-check each parameter
        for param_name, value in params.items():
            if value is None:
                continue  # Allow NULL values

            expected_type = template.param_types.get(param_name, "").upper()
            # Normalize type names
            if expected_type in ("VARCHAR", "CHAR", "NVARCHAR"):
                expected_type = "TEXT"
            elif expected_type in ("INT", "SMALLINT", "BIGINT", "BOOLEAN"):
                expected_type = "INTEGER"
            elif expected_type in ("FLOAT", "DOUBLE", "DECIMAL", "NUMERIC"):
                expected_type = "REAL"
            elif expected_type in ("DATETIME", "DATE", "TIME"):
                expected_type = "TIMESTAMP"

            validator = self.TYPE_VALIDATORS.get(expected_type, self.TYPE_VALIDATORS[""])
            if not validator(value):
                raise SecurityError(
                    f"Type mismatch for parameter '{param_name}': "
                    f"expected {expected_type}, got {type(value).__name__} ({value!r})"
                )

    def _sanitize_params(self, params: dict[str, Any]) -> None:
        """
        Defense-in-depth: check parameter values for dangerous SQL patterns.
        
        Even though we use parameterized queries (which prevent SQL injection),
        we still check for suspicious patterns as an extra safety layer.
        """
        for param_name, value in params.items():
            if not isinstance(value, str):
                continue

            for pattern in DANGEROUS_PATTERNS:
                if pattern.search(value):
                    raise SecurityError(
                        f"Potentially dangerous content detected in parameter '{param_name}': "
                        f"value matches blocked pattern. Input rejected."
                    )

    def _build_ordered_params(
        self, params: dict[str, Any], template: SQLTemplate
    ) -> list[Any]:
        """Convert named params dict to ordered list matching template placeholders."""
        return [params.get(name) for name in template.params]

    def _log_audit(
        self,
        timestamp: str,
        template_id: str,
        operation: str,
        table: str,
        params: dict,
        success: bool,
        error: Optional[str] = None,
        row_count: Optional[int] = None,
    ) -> None:
        """Record an audit log entry."""
        entry = AuditLogEntry(
            timestamp=timestamp,
            template_id=template_id,
            operation=operation,
            table=table,
            params=params,
            success=success,
            error=error,
            row_count=row_count,
        )
        self.audit_log.append(entry)

        log_msg = (
            f"[AUDIT] {timestamp} | {template_id} | {operation} | "
            f"{'SUCCESS' if success else 'FAILED'}"
        )
        if error:
            log_msg += f" | Error: {error}"
        if row_count is not None:
            log_msg += f" | Rows: {row_count}"

        if success:
            logger.info(log_msg)
        else:
            logger.warning(log_msg)

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        """Return recent audit log entries."""
        entries = self.audit_log[-limit:]
        return [e.to_dict() for e in reversed(entries)]

    def get_security_report(self) -> dict:
        """Generate a security summary report."""
        total = len(self.audit_log)
        successes = sum(1 for e in self.audit_log if e.success)
        failures = total - successes

        return {
            "total_queries": total,
            "successful": successes,
            "failed": failures,
            "registered_templates": self.template_registry.count,
            "recent_failures": [
                e.to_dict() for e in self.audit_log if not e.success
            ][-10:],
        }


def _is_numeric_string(value: Any) -> bool:
    """Check if a value is a string that represents a number."""
    if not isinstance(value, str):
        return False
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False
