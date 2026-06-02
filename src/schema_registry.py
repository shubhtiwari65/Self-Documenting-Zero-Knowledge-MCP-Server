"""
Schema Registry
================
In-memory registry that holds the introspected database schema.
Provides a clean API for other modules to query table metadata,
columns, relationships, and primary keys.
"""

import logging
from typing import Optional
from src.introspector import DatabaseSchema, TableInfo, ColumnInfo, ForeignKeyInfo

logger = logging.getLogger(__name__)


class SchemaRegistry:
    """
    Central registry for database schema metadata.
    
    Populated by the DatabaseIntrospector at startup, then queried
    by the CRUD generator, join analyzer, and template engine.
    """

    def __init__(self, schema: DatabaseSchema):
        self._schema = schema
        logger.info(f"Schema registry initialized with {len(schema.tables)} tables")

    @property
    def database_path(self) -> str:
        return self._schema.db_path

    def get_table_names(self) -> list[str]:
        """Return all discovered table names, sorted alphabetically."""
        return self._schema.table_names

    def get_table(self, table_name: str) -> Optional[TableInfo]:
        """Return full metadata for a specific table."""
        return self._schema.tables.get(table_name)

    def get_columns(self, table_name: str) -> list[ColumnInfo]:
        """Return all columns for a specific table."""
        table = self.get_table(table_name)
        return table.columns if table else []

    def get_column_names(self, table_name: str) -> list[str]:
        """Return all column names for a specific table."""
        table = self.get_table(table_name)
        return table.column_names if table else []

    def get_primary_key(self, table_name: str) -> list[str]:
        """Return the primary key column(s) for a specific table."""
        table = self.get_table(table_name)
        return table.primary_key_columns if table else []

    def get_non_pk_columns(self, table_name: str) -> list[str]:
        """Return non-primary-key column names for a specific table."""
        table = self.get_table(table_name)
        return table.non_pk_columns if table else []

    def get_foreign_keys(self, table_name: str) -> list[ForeignKeyInfo]:
        """Return all foreign key relationships for a specific table."""
        table = self.get_table(table_name)
        return table.foreign_keys if table else []

    def get_all_relationships(self) -> list[ForeignKeyInfo]:
        """Return all foreign key relationships across the entire database."""
        return self._schema.get_all_relationships()

    def get_tables_referencing(self, table_name: str) -> list[tuple[str, str, str]]:
        """
        Find all tables that have a FK pointing TO the given table.
        
        Returns list of (from_table, from_column, to_column) tuples.
        """
        referencing = []
        for fk in self.get_all_relationships():
            if fk.to_table == table_name:
                referencing.append((fk.from_table, fk.from_column, fk.to_column))
        return referencing

    def get_table_summary(self, table_name: str) -> str:
        """Generate a human-readable summary of a table's structure."""
        table = self.get_table(table_name)
        if not table:
            return f"Table '{table_name}' not found."

        lines = [f"Table: {table_name} ({table.row_count} rows)"]
        lines.append("Columns:")
        for col in table.columns:
            pk_marker = " [PK]" if col.is_primary_key else ""
            null_marker = " (nullable)" if col.is_nullable else " (NOT NULL)"
            default_marker = f" DEFAULT {col.default_value}" if col.default_value else ""
            lines.append(f"  - {col.name}: {col.data_type}{pk_marker}{null_marker}{default_marker}")

        if table.foreign_keys:
            lines.append("Foreign Keys:")
            for fk in table.foreign_keys:
                lines.append(f"  - {fk.from_column} -> {fk.to_table}.{fk.to_column}")

        if table.indexes:
            lines.append("Indexes:")
            for idx in table.indexes:
                unique_marker = " (UNIQUE)" if idx.is_unique else ""
                lines.append(f"  - {idx.name}: [{', '.join(idx.columns)}]{unique_marker}")

        return "\n".join(lines)

    def get_full_schema_summary(self) -> str:
        """Generate a complete human-readable schema summary."""
        lines = [
            f"Database: {self._schema.db_path}",
            f"Total Tables: {len(self._schema.tables)}",
            "=" * 50,
        ]
        for table_name in self.get_table_names():
            lines.append("")
            lines.append(self.get_table_summary(table_name))
            lines.append("-" * 40)

        # Add relationship overview
        relationships = self.get_all_relationships()
        if relationships:
            lines.append("")
            lines.append("Relationships:")
            for fk in relationships:
                lines.append(f"  {fk.from_table}.{fk.from_column} -> {fk.to_table}.{fk.to_column}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Return the full schema as a dictionary."""
        return self._schema.to_dict()
