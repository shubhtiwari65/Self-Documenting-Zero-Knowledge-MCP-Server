"""
SQL Template Engine
====================
Generates pre-validated, parameterized SQL templates for every table
discovered during introspection. These templates are the ONLY SQL
that the Zero-Knowledge security layer will allow to execute.

Each template is:
- Generated at startup from introspected schema
- Stored with a unique ID in the template registry
- Uses positional '?' placeholders (never string interpolation)
- Type-annotated with expected parameter types
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from src.schema_registry import SchemaRegistry

logger = logging.getLogger(__name__)


@dataclass
class SQLTemplate:
    """A single pre-validated SQL template."""
    id: str
    description: str
    sql: str
    params: list[str]
    param_types: dict[str, str]
    operation: str  # CREATE, READ, UPDATE, DELETE, LIST, JOIN
    table: str
    is_write: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "sql": self.sql,
            "params": self.params,
            "param_types": self.param_types,
            "operation": self.operation,
            "table": self.table,
            "is_write": self.is_write,
        }


class SQLTemplateRegistry:
    """
    Registry of all pre-validated SQL templates.
    
    Templates are generated at startup from the schema and cannot be
    modified at runtime. This is the foundation of the zero-knowledge
    security model.
    """

    def __init__(self):
        self._templates: dict[str, SQLTemplate] = {}

    def register(self, template: SQLTemplate) -> None:
        """Register a new SQL template."""
        if template.id in self._templates:
            logger.warning(f"Template '{template.id}' already registered, overwriting.")
        self._templates[template.id] = template
        logger.debug(f"Registered template: {template.id}")

    def get(self, template_id: str) -> Optional[SQLTemplate]:
        """Retrieve a template by ID."""
        return self._templates.get(template_id)

    def list_templates(self) -> list[SQLTemplate]:
        """Return all registered templates."""
        return list(self._templates.values())

    def list_by_table(self, table_name: str) -> list[SQLTemplate]:
        """Return all templates for a specific table."""
        return [t for t in self._templates.values() if t.table == table_name]

    def list_by_operation(self, operation: str) -> list[SQLTemplate]:
        """Return all templates of a specific operation type."""
        return [t for t in self._templates.values() if t.operation == operation]

    @property
    def count(self) -> int:
        return len(self._templates)


class SQLTemplateGenerator:
    """
    Generates SQL templates from the schema registry.
    
    For each table, generates:
    - CREATE: INSERT INTO table (...) VALUES (...)
    - READ: SELECT * FROM table WHERE pk = ?
    - UPDATE: UPDATE table SET col1=?, col2=? WHERE pk = ?
    - DELETE: DELETE FROM table WHERE pk = ?
    - LIST: SELECT * FROM table LIMIT ? OFFSET ?
    - SEARCH: SELECT * FROM table WHERE col LIKE ?
    
    For each FK relationship, generates:
    - JOIN: SELECT ... FROM t1 JOIN t2 ON ...
    """

    def __init__(self, schema_registry: SchemaRegistry):
        self.schema = schema_registry
        self.registry = SQLTemplateRegistry()

    def generate_all(self) -> SQLTemplateRegistry:
        """Generate all SQL templates for every discovered table."""
        for table_name in self.schema.get_table_names():
            self._generate_crud_templates(table_name)
            self._generate_search_template(table_name)

        self._generate_join_templates()

        logger.info(f"Generated {self.registry.count} SQL templates total")
        return self.registry

    def _generate_crud_templates(self, table_name: str) -> None:
        """Generate CRUD templates for a single table."""
        table = self.schema.get_table(table_name)
        if not table:
            return

        pk_cols = table.primary_key_columns
        non_pk_cols = table.non_pk_columns
        all_cols = table.column_names

        # --- CREATE (INSERT) ---
        if non_pk_cols:
            insert_cols = non_pk_cols
            placeholders = ", ".join(["?"] * len(insert_cols))
            col_list = ", ".join([f"[{c}]" for c in insert_cols])
            param_types = {}
            for col_name in insert_cols:
                col = table.get_column(col_name)
                if col:
                    param_types[col_name] = col.data_type

            self.registry.register(SQLTemplate(
                id=f"create_{table_name}",
                description=f"Insert a new row into {table_name}",
                sql=f"INSERT INTO [{table_name}] ({col_list}) VALUES ({placeholders})",
                params=insert_cols,
                param_types=param_types,
                operation="CREATE",
                table=table_name,
                is_write=True,
            ))

        # --- READ (SELECT by PK) ---
        if pk_cols:
            pk_where = " AND ".join([f"[{pk}] = ?" for pk in pk_cols])
            pk_types = {}
            for pk in pk_cols:
                col = table.get_column(pk)
                if col:
                    pk_types[pk] = col.data_type

            self.registry.register(SQLTemplate(
                id=f"read_{table_name}",
                description=f"Read a single row from {table_name} by primary key",
                sql=f"SELECT * FROM [{table_name}] WHERE {pk_where}",
                params=pk_cols,
                param_types=pk_types,
                operation="READ",
                table=table_name,
            ))

        # --- UPDATE (by PK) ---
        if pk_cols and non_pk_cols:
            set_clause = ", ".join([f"[{c}] = ?" for c in non_pk_cols])
            pk_where = " AND ".join([f"[{pk}] = ?" for pk in pk_cols])
            update_params = non_pk_cols + pk_cols
            param_types = {}
            for col_name in update_params:
                col = table.get_column(col_name)
                if col:
                    param_types[col_name] = col.data_type

            self.registry.register(SQLTemplate(
                id=f"update_{table_name}",
                description=f"Update a row in {table_name} by primary key",
                sql=f"UPDATE [{table_name}] SET {set_clause} WHERE {pk_where}",
                params=update_params,
                param_types=param_types,
                operation="UPDATE",
                table=table_name,
                is_write=True,
            ))

        # --- DELETE (by PK) ---
        if pk_cols:
            pk_where = " AND ".join([f"[{pk}] = ?" for pk in pk_cols])
            pk_types = {}
            for pk in pk_cols:
                col = table.get_column(pk)
                if col:
                    pk_types[pk] = col.data_type

            self.registry.register(SQLTemplate(
                id=f"delete_{table_name}",
                description=f"Delete a row from {table_name} by primary key",
                sql=f"DELETE FROM [{table_name}] WHERE {pk_where}",
                params=pk_cols,
                param_types=pk_types,
                operation="DELETE",
                table=table_name,
                is_write=True,
            ))

        # --- LIST (paginated) ---
        self.registry.register(SQLTemplate(
            id=f"list_{table_name}",
            description=f"List rows from {table_name} with pagination",
            sql=f"SELECT * FROM [{table_name}] LIMIT ? OFFSET ?",
            params=["limit", "offset"],
            param_types={"limit": "INTEGER", "offset": "INTEGER"},
            operation="LIST",
            table=table_name,
        ))

    def _generate_search_template(self, table_name: str) -> None:
        """Generate a search template for TEXT columns."""
        table = self.schema.get_table(table_name)
        if not table:
            return

        text_cols = [c for c in table.columns if c.data_type.upper() in ("TEXT", "VARCHAR", "CHAR", "")]
        if not text_cols:
            return

        # Build a search that checks all text columns
        conditions = " OR ".join([f"[{c.name}] LIKE ?" for c in text_cols])
        params = [f"search_{c.name}" for c in text_cols]
        param_types = {f"search_{c.name}": "TEXT" for c in text_cols}

        self.registry.register(SQLTemplate(
            id=f"search_{table_name}",
            description=f"Search {table_name} across text columns: {', '.join(c.name for c in text_cols)}",
            sql=f"SELECT * FROM [{table_name}] WHERE {conditions} LIMIT 50",
            params=params,
            param_types=param_types,
            operation="SEARCH",
            table=table_name,
        ))

    def _generate_join_templates(self) -> None:
        """Generate JOIN templates from foreign key relationships."""
        relationships = self.schema.get_all_relationships()

        for fk in relationships:
            from_table = fk.from_table
            to_table = fk.to_table

            # Get PK of the referenced table for filtering
            to_pk = self.schema.get_primary_key(to_table)
            filter_col = to_pk[0] if to_pk else fk.to_column

            # Get column info for type
            to_table_info = self.schema.get_table(to_table)
            filter_type = "INTEGER"
            if to_table_info:
                col = to_table_info.get_column(filter_col)
                if col:
                    filter_type = col.data_type

            self.registry.register(SQLTemplate(
                id=f"join_{from_table}_to_{to_table}",
                description=(
                    f"Join {from_table} with {to_table} "
                    f"on {from_table}.{fk.from_column} = {to_table}.{fk.to_column}"
                ),
                sql=(
                    f"SELECT a.*, b.* FROM [{from_table}] a "
                    f"INNER JOIN [{to_table}] b ON a.[{fk.from_column}] = b.[{fk.to_column}] "
                    f"WHERE b.[{filter_col}] = ?"
                ),
                params=[f"{to_table}_{filter_col}"],
                param_types={f"{to_table}_{filter_col}": filter_type},
                operation="JOIN",
                table=from_table,
            ))
