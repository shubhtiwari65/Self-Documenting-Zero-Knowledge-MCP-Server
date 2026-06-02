"""Tests for the Zero-Knowledge Security Validator."""

import os
import sys
import sqlite3
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.introspector import DatabaseIntrospector
from src.schema_registry import SchemaRegistry
from src.sql_templates import SQLTemplateGenerator
from src.security import ZeroKnowledgeValidator, SecurityError


@pytest.fixture
def secure_system(tmp_path):
    """Create a system for security testing."""
    db_path = str(tmp_path / "test_security.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE secrets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL,
            value TEXT NOT NULL
        );
        INSERT INTO secrets (key, value) VALUES ('api_key', 'sk-12345');
        INSERT INTO secrets (key, value) VALUES ('password', 'hunter2');
    """)
    conn.commit()
    conn.close()

    introspector = DatabaseIntrospector(db_path)
    schema = introspector.introspect()
    registry = SchemaRegistry(schema)
    template_gen = SQLTemplateGenerator(registry)
    template_registry = template_gen.generate_all()
    validator = ZeroKnowledgeValidator(db_path, template_registry)

    return validator


def test_unknown_template_rejected(secure_system):
    """Test that unknown template IDs are rejected."""
    with pytest.raises(SecurityError, match="Unknown template"):
        secure_system.validate_and_execute("drop_all_tables", {})


def test_raw_sql_not_possible(secure_system):
    """Test that there's no way to execute raw SQL."""
    # The validator only accepts template IDs, not SQL strings
    with pytest.raises(SecurityError, match="Unknown template"):
        secure_system.validate_and_execute(
            "SELECT * FROM secrets; DROP TABLE secrets; --", {}
        )


def test_missing_params_rejected(secure_system):
    """Test that missing required parameters are rejected."""
    with pytest.raises(SecurityError, match="Missing required parameter"):
        secure_system.validate_and_execute("read_secrets", {})


def test_extra_params_rejected(secure_system):
    """Test that unexpected parameters are rejected."""
    with pytest.raises(SecurityError, match="Unexpected parameter"):
        secure_system.validate_and_execute("read_secrets", {
            "id": 1,
            "malicious_param": "'; DROP TABLE secrets; --"
        })


def test_sql_injection_in_params_blocked(secure_system):
    """Test that SQL injection patterns in parameter values are blocked."""
    # Even though parameterized queries prevent injection,
    # the defense-in-depth sanitizer should catch these
    with pytest.raises(SecurityError, match="dangerous content"):
        secure_system.validate_and_execute("search_secrets", {
            "search_key": "'; DROP TABLE secrets; --",
            "search_value": "normal",
        })


def test_union_injection_blocked(secure_system):
    """Test that UNION SELECT injection is blocked."""
    with pytest.raises(SecurityError, match="dangerous content"):
        secure_system.validate_and_execute("search_secrets", {
            "search_key": "x' UNION SELECT * FROM sqlite_master --",
            "search_value": "normal",
        })


def test_comment_injection_blocked(secure_system):
    """Test that SQL comment injection is blocked."""
    with pytest.raises(SecurityError, match="dangerous content"):
        secure_system.validate_and_execute("search_secrets", {
            "search_key": "value -- comment",
            "search_value": "normal",
        })


def test_valid_operation_succeeds(secure_system):
    """Test that legitimate operations work correctly."""
    result = secure_system.validate_and_execute("list_secrets", {
        "limit": 10, "offset": 0
    })
    assert len(result) == 2
    assert result[0]["key"] == "api_key"


def test_security_report(secure_system):
    """Test that the security report is generated."""
    # Execute some operations
    secure_system.validate_and_execute("list_secrets", {"limit": 5, "offset": 0})
    
    try:
        secure_system.validate_and_execute("nonexistent", {})
    except SecurityError:
        pass

    report = secure_system.get_security_report()
    assert report["total_queries"] == 2
    assert report["successful"] == 1
    assert report["failed"] == 1


def test_type_validation(secure_system):
    """Test that type mismatches are caught."""
    # read_secrets expects id as INTEGER
    # Passing a valid integer should work
    result = secure_system.validate_and_execute("read_secrets", {"id": 1})
    assert len(result) == 1


def test_audit_log_records_all_operations(secure_system):
    """Test that the audit log captures all operations."""
    # Successful operation
    secure_system.validate_and_execute("list_secrets", {"limit": 5, "offset": 0})
    
    # Failed operation
    try:
        secure_system.validate_and_execute("fake_template", {})
    except SecurityError:
        pass

    log = secure_system.get_audit_log()
    assert len(log) == 2
    # Most recent first
    assert log[0]["success"] is False
    assert log[1]["success"] is True


def test_create_with_valid_data(secure_system):
    """Test creating data through the security layer."""
    result = secure_system.validate_and_execute("create_secrets", {
        "key": "new_key",
        "value": "new_value",
    })
    assert result[0]["last_insert_id"] == 3


def test_delete_by_pk(secure_system):
    """Test deleting through the security layer."""
    result = secure_system.validate_and_execute("delete_secrets", {"id": 1})
    assert result[0]["affected_rows"] == 1
    
    # Verify deleted
    remaining = secure_system.validate_and_execute("list_secrets", {
        "limit": 10, "offset": 0
    })
    assert len(remaining) == 1
