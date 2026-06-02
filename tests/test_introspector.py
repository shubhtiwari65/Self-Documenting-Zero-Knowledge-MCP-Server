"""Tests for the Database Introspector."""

import os
import sys
import sqlite3
import tempfile
import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.introspector import DatabaseIntrospector, DatabaseSchema, TableInfo


@pytest.fixture
def sample_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            age INTEGER
        );
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        INSERT INTO users (name, email, age) VALUES ('Alice', 'alice@test.com', 30);
        INSERT INTO users (name, email, age) VALUES ('Bob', 'bob@test.com', 25);
        INSERT INTO posts (user_id, title, content) VALUES (1, 'First Post', 'Hello World');
        INSERT INTO posts (user_id, title, content) VALUES (1, 'Second Post', 'More content');
        INSERT INTO posts (user_id, title, content) VALUES (2, 'Bob Post', 'Bob says hi');
    """)
    conn.commit()
    conn.close()
    return db_path


def test_introspect_discovers_tables(sample_db):
    """Test that introspection discovers all tables."""
    introspector = DatabaseIntrospector(sample_db)
    schema = introspector.introspect()
    
    assert isinstance(schema, DatabaseSchema)
    assert "users" in schema.table_names
    assert "posts" in schema.table_names
    assert len(schema.tables) == 2


def test_introspect_discovers_columns(sample_db):
    """Test that columns are correctly discovered."""
    introspector = DatabaseIntrospector(sample_db)
    schema = introspector.introspect()
    
    users = schema.tables["users"]
    assert len(users.columns) == 4
    
    col_names = [c.name for c in users.columns]
    assert "id" in col_names
    assert "name" in col_names
    assert "email" in col_names
    assert "age" in col_names


def test_introspect_identifies_primary_keys(sample_db):
    """Test that primary keys are identified."""
    introspector = DatabaseIntrospector(sample_db)
    schema = introspector.introspect()
    
    users = schema.tables["users"]
    assert users.primary_key_columns == ["id"]


def test_introspect_discovers_foreign_keys(sample_db):
    """Test that foreign keys are discovered."""
    introspector = DatabaseIntrospector(sample_db)
    schema = introspector.introspect()
    
    posts = schema.tables["posts"]
    assert len(posts.foreign_keys) == 1
    fk = posts.foreign_keys[0]
    assert fk.from_table == "posts"
    assert fk.from_column == "user_id"
    assert fk.to_table == "users"
    assert fk.to_column == "id"


def test_introspect_counts_rows(sample_db):
    """Test that row counts are correct."""
    introspector = DatabaseIntrospector(sample_db)
    schema = introspector.introspect()
    
    assert schema.tables["users"].row_count == 2
    assert schema.tables["posts"].row_count == 3


def test_introspect_column_types(sample_db):
    """Test that column types are preserved."""
    introspector = DatabaseIntrospector(sample_db)
    schema = introspector.introspect()
    
    users = schema.tables["users"]
    id_col = users.get_column("id")
    assert id_col.data_type == "INTEGER"
    assert id_col.is_primary_key
    
    name_col = users.get_column("name")
    assert name_col.data_type == "TEXT"
    assert not name_col.is_nullable


def test_introspect_nullable_columns(sample_db):
    """Test that nullability is correctly detected."""
    introspector = DatabaseIntrospector(sample_db)
    schema = introspector.introspect()
    
    users = schema.tables["users"]
    # 'name' is NOT NULL
    assert not users.get_column("name").is_nullable
    # 'age' has no NOT NULL constraint
    assert users.get_column("age").is_nullable


def test_schema_to_dict(sample_db):
    """Test that schema can be serialized to dict."""
    introspector = DatabaseIntrospector(sample_db)
    schema = introspector.introspect()
    
    d = schema.to_dict()
    assert "tables" in d
    assert "total_tables" in d
    assert d["total_tables"] == 2


def test_get_all_relationships(sample_db):
    """Test getting all relationships across tables."""
    introspector = DatabaseIntrospector(sample_db)
    schema = introspector.introspect()
    
    rels = schema.get_all_relationships()
    assert len(rels) == 1
    assert rels[0].from_table == "posts"
    assert rels[0].to_table == "users"
