"""Tests for CRUD operations and SQL template generation."""

import os
import sys
import sqlite3
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.introspector import DatabaseIntrospector
from src.schema_registry import SchemaRegistry
from src.sql_templates import SQLTemplateGenerator, SQLTemplateRegistry
from src.security import ZeroKnowledgeValidator


@pytest.fixture
def setup_system(tmp_path):
    """Create a full test system with DB, schema, templates, and validator."""
    db_path = str(tmp_path / "test_crud.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL DEFAULT 0.0,
            quantity INTEGER DEFAULT 0,
            description TEXT
        );
        INSERT INTO items (name, price, quantity, description)
        VALUES ('Widget', 9.99, 100, 'A useful widget');
        INSERT INTO items (name, price, quantity, description)
        VALUES ('Gadget', 19.99, 50, 'A fancy gadget');
    """)
    conn.commit()
    conn.close()

    introspector = DatabaseIntrospector(db_path)
    schema = introspector.introspect()
    registry = SchemaRegistry(schema)
    template_gen = SQLTemplateGenerator(registry)
    template_registry = template_gen.generate_all()
    validator = ZeroKnowledgeValidator(db_path, template_registry)

    return {
        "db_path": db_path,
        "registry": registry,
        "template_registry": template_registry,
        "validator": validator,
    }


def test_templates_generated(setup_system):
    """Test that CRUD templates are generated for the items table."""
    tr = setup_system["template_registry"]
    
    assert tr.get("create_items") is not None
    assert tr.get("read_items") is not None
    assert tr.get("update_items") is not None
    assert tr.get("delete_items") is not None
    assert tr.get("list_items") is not None


def test_list_items(setup_system):
    """Test listing items."""
    validator = setup_system["validator"]
    
    result = validator.validate_and_execute("list_items", {"limit": 10, "offset": 0})
    assert len(result) == 2
    assert result[0]["name"] in ("Widget", "Gadget")


def test_read_item_by_pk(setup_system):
    """Test reading a specific item by primary key."""
    validator = setup_system["validator"]
    
    result = validator.validate_and_execute("read_items", {"id": 1})
    assert len(result) == 1
    assert result[0]["name"] == "Widget"
    assert result[0]["price"] == 9.99


def test_create_item(setup_system):
    """Test creating a new item."""
    validator = setup_system["validator"]
    
    result = validator.validate_and_execute("create_items", {
        "name": "Doohickey",
        "price": 29.99,
        "quantity": 25,
        "description": "A new doohickey",
    })
    assert result[0]["last_insert_id"] == 3
    
    # Verify it was actually created
    read_result = validator.validate_and_execute("read_items", {"id": 3})
    assert read_result[0]["name"] == "Doohickey"


def test_update_item(setup_system):
    """Test updating an existing item."""
    validator = setup_system["validator"]
    
    result = validator.validate_and_execute("update_items", {
        "name": "Super Widget",
        "price": 14.99,
        "quantity": 200,
        "description": "An upgraded widget",
        "id": 1,
    })
    assert result[0]["affected_rows"] == 1
    
    # Verify the update
    read_result = validator.validate_and_execute("read_items", {"id": 1})
    assert read_result[0]["name"] == "Super Widget"
    assert read_result[0]["price"] == 14.99


def test_delete_item(setup_system):
    """Test deleting an item."""
    validator = setup_system["validator"]
    
    result = validator.validate_and_execute("delete_items", {"id": 2})
    assert result[0]["affected_rows"] == 1
    
    # Verify it was deleted
    read_result = validator.validate_and_execute("read_items", {"id": 2})
    assert len(read_result) == 0


def test_search_items(setup_system):
    """Test searching items by text."""
    validator = setup_system["validator"]
    
    result = validator.validate_and_execute("search_items", {
        "search_name": "%Widget%",
        "search_description": "%Widget%",
    })
    assert len(result) >= 1
    assert any(r["name"] == "Widget" for r in result)


def test_template_param_types(setup_system):
    """Test that templates have correct parameter types."""
    tr = setup_system["template_registry"]
    
    create_template = tr.get("create_items")
    assert "name" in create_template.param_types
    assert create_template.param_types["name"] == "TEXT"
    assert create_template.param_types["price"] == "REAL"
    assert create_template.param_types["quantity"] == "INTEGER"


def test_list_templates_by_table(setup_system):
    """Test listing templates by table."""
    tr = setup_system["template_registry"]
    
    item_templates = tr.list_by_table("items")
    assert len(item_templates) >= 5  # create, read, update, delete, list, + search


def test_audit_log(setup_system):
    """Test that operations are logged."""
    validator = setup_system["validator"]
    
    # Execute a query
    validator.validate_and_execute("list_items", {"limit": 5, "offset": 0})
    
    # Check audit log
    log = validator.get_audit_log()
    assert len(log) >= 1
    assert log[0]["template_id"] == "list_items"
    assert log[0]["success"] is True
