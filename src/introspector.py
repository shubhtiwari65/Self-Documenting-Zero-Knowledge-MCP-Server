"""
Database Introspector
=====================
Autonomously scans an undocumented SQLite database using PRAGMA statements
to discover schema information: tables, columns, foreign keys, indexes,
and primary keys — with zero prior knowledge of the database structure.
"""

import sqlite3
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ColumnInfo:
    """Represents a single column in a database table."""
    name: str
    data_type: str
    is_nullable: bool
    default_value: Optional[str]
    is_primary_key: bool

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.data_type,
            "nullable": self.is_nullable,
            "default": self.default_value,
            "primary_key": self.is_primary_key,
        }


@dataclass
class ForeignKeyInfo:
    """Represents a foreign key relationship."""
    from_table: str
    from_column: str
    to_table: str
    to_column: str

    def to_dict(self) -> dict:
        return {
            "from_table": self.from_table,
            "from_column": self.from_column,
            "to_table": self.to_table,
            "to_column": self.to_column,
        }


@dataclass
class IndexInfo:
    """Represents an index on a table."""
    name: str
    table: str
    columns: list[str]
    is_unique: bool

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "table": self.table,
            "columns": self.columns,
            "unique": self.is_unique,
        }


@dataclass
class TableInfo:
    """Complete metadata for a single table."""
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    row_count: int = 0

    @property
    def primary_key_columns(self) -> list[str]:
        """Return the names of primary key columns."""
        return [col.name for col in self.columns if col.is_primary_key]

    @property
    def non_pk_columns(self) -> list[str]:
        """Return names of non-primary-key columns."""
        return [col.name for col in self.columns if not col.is_primary_key]

    @property
    def column_names(self) -> list[str]:
        """Return all column names."""
        return [col.name for col in self.columns]

    def get_column(self, name: str) -> Optional[ColumnInfo]:
        """Get column info by name."""
        for col in self.columns:
            if col.name == name:
                return col
        return None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "columns": [c.to_dict() for c in self.columns],
            "foreign_keys": [fk.to_dict() for fk in self.foreign_keys],
            "indexes": [idx.to_dict() for idx in self.indexes],
            "primary_keys": self.primary_key_columns,
            "row_count": self.row_count,
        }


@dataclass
class DatabaseSchema:
    """Complete database schema discovered via introspection."""
    tables: dict[str, TableInfo] = field(default_factory=dict)
    db_path: str = ""

    @property
    def table_names(self) -> list[str]:
        return sorted(self.tables.keys())

    def get_all_relationships(self) -> list[ForeignKeyInfo]:
        """Return all foreign key relationships across all tables."""
        relationships = []
        for table in self.tables.values():
            relationships.extend(table.foreign_keys)
        return relationships

    def to_dict(self) -> dict:
        return {
            "database": self.db_path,
            "tables": {name: t.to_dict() for name, t in self.tables.items()},
            "total_tables": len(self.tables),
        }


class DatabaseIntrospector:
    """
    Scans an undocumented SQLite database and discovers its complete schema
    using only PRAGMA introspection — zero prior knowledge required.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """Create a new database connection with foreign keys enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def introspect(self) -> DatabaseSchema:
        """
        Perform full database introspection.
        
        Returns a DatabaseSchema object containing complete metadata
        for every table, column, foreign key, and index.
        """
        logger.info(f"Starting introspection of: {self.db_path}")
        schema = DatabaseSchema(db_path=self.db_path)

        conn = self._get_connection()
        try:
            table_names = self._discover_tables(conn)
            logger.info(f"Discovered {len(table_names)} tables: {table_names}")

            for table_name in table_names:
                table_info = TableInfo(name=table_name)
                table_info.columns = self._discover_columns(conn, table_name)
                table_info.foreign_keys = self._discover_foreign_keys(conn, table_name)
                table_info.indexes = self._discover_indexes(conn, table_name)
                table_info.row_count = self._get_row_count(conn, table_name)
                schema.tables[table_name] = table_info
                logger.info(
                    f"  Table '{table_name}': {len(table_info.columns)} columns, "
                    f"{len(table_info.foreign_keys)} FKs, {table_info.row_count} rows"
                )
        finally:
            conn.close()

        logger.info("Introspection complete.")
        return schema

    def _discover_tables(self, conn: sqlite3.Connection) -> list[str]:
        """Discover all user tables (excluding internal SQLite tables)."""
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [row["name"] for row in cursor.fetchall()]

    def _discover_columns(self, conn: sqlite3.Connection, table_name: str) -> list[ColumnInfo]:
        """Discover all columns for a given table using PRAGMA table_info."""
        cursor = conn.execute(f"PRAGMA table_info([{table_name}])")
        columns = []
        for row in cursor.fetchall():
            columns.append(ColumnInfo(
                name=row["name"],
                data_type=row["type"] if row["type"] else "TEXT",
                is_nullable=not bool(row["notnull"]),
                default_value=row["dflt_value"],
                is_primary_key=bool(row["pk"]),
            ))
        return columns

    def _discover_foreign_keys(self, conn: sqlite3.Connection, table_name: str) -> list[ForeignKeyInfo]:
        """Discover all foreign key relationships for a given table."""
        cursor = conn.execute(f"PRAGMA foreign_key_list([{table_name}])")
        foreign_keys = []
        for row in cursor.fetchall():
            foreign_keys.append(ForeignKeyInfo(
                from_table=table_name,
                from_column=row["from"],
                to_table=row["table"],
                to_column=row["to"],
            ))
        return foreign_keys

    def _discover_indexes(self, conn: sqlite3.Connection, table_name: str) -> list[IndexInfo]:
        """Discover all indexes for a given table."""
        cursor = conn.execute(f"PRAGMA index_list([{table_name}])")
        indexes = []
        for row in cursor.fetchall():
            index_name = row["name"]
            is_unique = bool(row["unique"])
            # Get columns in this index
            idx_cursor = conn.execute(f"PRAGMA index_info([{index_name}])")
            columns = [idx_row["name"] for idx_row in idx_cursor.fetchall()]
            indexes.append(IndexInfo(
                name=index_name,
                table=table_name,
                columns=columns,
                is_unique=is_unique,
            ))
        return indexes

    def _get_row_count(self, conn: sqlite3.Connection, table_name: str) -> int:
        """Get the number of rows in a table."""
        cursor = conn.execute(f"SELECT COUNT(*) as cnt FROM [{table_name}]")
        return cursor.fetchone()["cnt"]
