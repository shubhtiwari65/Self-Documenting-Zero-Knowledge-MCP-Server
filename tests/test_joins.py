"""Tests for the Join Analyzer."""

import os
import sys
import sqlite3
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.introspector import DatabaseIntrospector
from src.schema_registry import SchemaRegistry
from src.sql_templates import SQLTemplateGenerator
from src.security import ZeroKnowledgeValidator


@pytest.fixture
def relational_db(tmp_path):
    """Create a database with multiple relationships."""
    db_path = str(tmp_path / "test_joins.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE authors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        CREATE TABLE books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author_id INTEGER,
            FOREIGN KEY (author_id) REFERENCES authors(id)
        );
        CREATE TABLE tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        CREATE TABLE book_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            FOREIGN KEY (book_id) REFERENCES books(id),
            FOREIGN KEY (tag_id) REFERENCES tags(id)
        );
        INSERT INTO authors (name) VALUES ('Alice'), ('Bob');
        INSERT INTO books (title, author_id) VALUES ('Book A', 1), ('Book B', 2), ('Book C', 1);
        INSERT INTO tags (name) VALUES ('Fiction'), ('Science'), ('History');
        INSERT INTO book_tags (book_id, tag_id) VALUES (1, 1), (1, 2), (2, 3), (3, 1);
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


def test_join_templates_generated(relational_db):
    """Test that join templates are created for FK relationships."""
    tr = relational_db["template_registry"]
    
    # books → authors join
    join_template = tr.get("join_books_to_authors")
    assert join_template is not None
    assert "INNER JOIN" in join_template.sql
    assert join_template.operation == "JOIN"


def test_junction_table_join_templates(relational_db):
    """Test that junction table joins are generated."""
    tr = relational_db["template_registry"]
    
    # book_tags → books and book_tags → tags
    assert tr.get("join_book_tags_to_books") is not None
    assert tr.get("join_book_tags_to_tags") is not None


def test_join_execution(relational_db):
    """Test executing a join query."""
    validator = relational_db["validator"]
    
    # Get books by author id=1
    result = validator.validate_and_execute(
        "join_books_to_authors", {"authors_id": 1}
    )
    assert len(result) == 2  # Alice has 2 books


def test_schema_registry_relationships(relational_db):
    """Test that the registry correctly reports relationships."""
    registry = relational_db["registry"]
    
    all_rels = registry.get_all_relationships()
    assert len(all_rels) >= 3  # books→authors, book_tags→books, book_tags→tags


def test_tables_referencing(relational_db):
    """Test finding tables that reference a given table."""
    registry = relational_db["registry"]
    
    # Who references authors?
    refs = registry.get_tables_referencing("authors")
    assert len(refs) == 1
    assert refs[0][0] == "books"  # from_table
    assert refs[0][1] == "author_id"  # from_column


def test_schema_summary(relational_db):
    """Test that schema summary includes relationship info."""
    registry = relational_db["registry"]
    
    summary = registry.get_full_schema_summary()
    assert "authors" in summary
    assert "books" in summary
    assert "Relationships" in summary
