"""
CRUD Tool Generator
====================
Dynamically generates and registers MCP tools for every table discovered
during introspection. Each tool uses pre-validated SQL templates and
goes through the Zero-Knowledge security validator.

Generated tools per table:
- create_{table}: Insert a new row
- read_{table}: Read a row by primary key
- update_{table}: Update a row by primary key
- delete_{table}: Delete a row by primary key
- list_{table}: Paginated listing of all rows
- search_{table}: Full-text search across text columns
"""

import logging
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from src.schema_registry import SchemaRegistry
from src.security import ZeroKnowledgeValidator

logger = logging.getLogger(__name__)


def _make_create_fn(table_name: str, template_id: str, validator: ZeroKnowledgeValidator):
    """Factory that creates a create tool function with captured closure variables."""
    def create_tool(data: dict[str, Any]) -> str:
        """Dynamically generated CREATE tool."""
        result = validator.validate_and_execute(template_id, data)
        return f"Successfully created row in '{table_name}'. Insert ID: {result[0].get('last_insert_id', 'N/A')}"
    return create_tool


def _make_read_fn(table_name: str, template_id: str, validator: ZeroKnowledgeValidator):
    """Factory that creates a read tool function with captured closure variables."""
    def read_tool(data: dict[str, Any]) -> list[dict]:
        """Dynamically generated READ tool."""
        result = validator.validate_and_execute(template_id, data)
        if not result:
            return f"No row found in '{table_name}' with the given key."
        return result
    return read_tool


def _make_update_fn(table_name: str, template_id: str, validator: ZeroKnowledgeValidator):
    """Factory that creates an update tool function with captured closure variables."""
    def update_tool(data: dict[str, Any]) -> str:
        """Dynamically generated UPDATE tool."""
        result = validator.validate_and_execute(template_id, data)
        affected = result[0].get("affected_rows", 0) if result else 0
        return f"Updated {affected} row(s) in '{table_name}'."
    return update_tool


def _make_delete_fn(table_name: str, template_id: str, validator: ZeroKnowledgeValidator):
    """Factory that creates a delete tool function with captured closure variables."""
    def delete_tool(data: dict[str, Any]) -> str:
        """Dynamically generated DELETE tool."""
        result = validator.validate_and_execute(template_id, data)
        affected = result[0].get("affected_rows", 0) if result else 0
        return f"Deleted {affected} row(s) from '{table_name}'."
    return delete_tool


def _make_list_fn(table_name: str, template_id: str, validator: ZeroKnowledgeValidator):
    """Factory that creates a list tool function with captured closure variables."""
    def list_tool(limit: int = 20, offset: int = 0) -> list[dict]:
        """Dynamically generated LIST tool."""
        safe_limit = min(max(1, limit), 100)
        safe_offset = max(0, offset)
        result = validator.validate_and_execute(
            template_id, {"limit": safe_limit, "offset": safe_offset}
        )
        return result
    return list_tool


def _make_search_fn(table_name: str, template_id: str, validator: ZeroKnowledgeValidator, col_names: list[str]):
    """Factory that creates a search tool function with captured closure variables."""
    def search_tool(query: str) -> list[dict]:
        """Dynamically generated SEARCH tool."""
        search_term = f"%{query}%"
        params = {f"search_{col}": search_term for col in col_names}
        result = validator.validate_and_execute(template_id, params)
        return result
    return search_tool


class CRUDGenerator:
    """
    Dynamically generates MCP tool functions for each database table.
    
    Each generated tool:
    - Has an auto-generated docstring from column metadata
    - Accepts typed parameters matching the table schema
    - Routes all SQL through the ZeroKnowledgeValidator
    - Returns results as structured data
    """

    def __init__(
        self,
        mcp: FastMCP,
        schema_registry: SchemaRegistry,
        validator: ZeroKnowledgeValidator,
    ):
        self.mcp = mcp
        self.schema = schema_registry
        self.validator = validator
        self._registered_tools: list[str] = []

    def generate_all_tools(self) -> list[str]:
        """
        Generate and register CRUD tools for every table.
        
        Returns a list of registered tool names.
        """
        for table_name in self.schema.get_table_names():
            self._generate_create_tool(table_name)
            self._generate_read_tool(table_name)
            self._generate_update_tool(table_name)
            self._generate_delete_tool(table_name)
            self._generate_list_tool(table_name)
            self._generate_search_tool(table_name)

        logger.info(f"Registered {len(self._registered_tools)} CRUD tools")
        return self._registered_tools

    def _generate_create_tool(self, table_name: str) -> None:
        """Generate a CREATE (INSERT) tool for a table."""
        table = self.schema.get_table(table_name)
        if not table:
            return

        non_pk_cols = table.non_pk_columns
        if not non_pk_cols:
            return

        # Build column documentation
        col_docs = []
        for col_name in non_pk_cols:
            col = table.get_column(col_name)
            if col:
                nullable = "optional" if col.is_nullable else "required"
                default = f", default: {col.default_value}" if col.default_value else ""
                col_docs.append(f"  - {col_name} ({col.data_type}, {nullable}{default})")

        docstring = (
            f"Insert a new row into the '{table_name}' table.\n\n"
            f"Parameters (pass as JSON object 'data'):\n"
            + "\n".join(col_docs)
            + f"\n\nReturns the ID of the newly created row."
        )

        fn = _make_create_fn(table_name, f"create_{table_name}", self.validator)
        self.mcp.tool(name=f"create_{table_name}", description=docstring)(fn)
        self._registered_tools.append(f"create_{table_name}")

    def _generate_read_tool(self, table_name: str) -> None:
        """Generate a READ (SELECT by PK) tool for a table."""
        table = self.schema.get_table(table_name)
        if not table or not table.primary_key_columns:
            return

        pk_cols = table.primary_key_columns
        pk_doc = ", ".join([f"{pk} ({table.get_column(pk).data_type})" for pk in pk_cols if table.get_column(pk)])

        docstring = (
            f"Read a single row from '{table_name}' by primary key.\n\n"
            f"Parameters:\n  - {pk_doc}\n\n"
            f"Returns the full row as a JSON object, or empty if not found."
        )

        fn = _make_read_fn(table_name, f"read_{table_name}", self.validator)
        self.mcp.tool(name=f"read_{table_name}", description=docstring)(fn)
        self._registered_tools.append(f"read_{table_name}")

    def _generate_update_tool(self, table_name: str) -> None:
        """Generate an UPDATE tool for a table."""
        table = self.schema.get_table(table_name)
        if not table or not table.primary_key_columns or not table.non_pk_columns:
            return

        pk_cols = table.primary_key_columns
        non_pk_cols = table.non_pk_columns

        col_docs = []
        for col_name in non_pk_cols:
            col = table.get_column(col_name)
            if col:
                col_docs.append(f"  - {col_name} ({col.data_type}): new value")
        for pk in pk_cols:
            col = table.get_column(pk)
            if col:
                col_docs.append(f"  - {pk} ({col.data_type}): primary key to identify the row")

        docstring = (
            f"Update a row in '{table_name}' by primary key.\n\n"
            f"Parameters (pass as JSON object 'data'):\n"
            + "\n".join(col_docs)
            + f"\n\nAll non-PK columns must be provided."
        )

        fn = _make_update_fn(table_name, f"update_{table_name}", self.validator)
        self.mcp.tool(name=f"update_{table_name}", description=docstring)(fn)
        self._registered_tools.append(f"update_{table_name}")

    def _generate_delete_tool(self, table_name: str) -> None:
        """Generate a DELETE tool for a table."""
        table = self.schema.get_table(table_name)
        if not table or not table.primary_key_columns:
            return

        pk_cols = table.primary_key_columns
        pk_doc = ", ".join([f"{pk} ({table.get_column(pk).data_type})" for pk in pk_cols if table.get_column(pk)])

        docstring = (
            f"Delete a row from '{table_name}' by primary key.\n\n"
            f"Parameters:\n  - {pk_doc}\n\n"
            f"Returns the number of affected rows."
        )

        fn = _make_delete_fn(table_name, f"delete_{table_name}", self.validator)
        self.mcp.tool(name=f"delete_{table_name}", description=docstring)(fn)
        self._registered_tools.append(f"delete_{table_name}")

    def _generate_list_tool(self, table_name: str) -> None:
        """Generate a LIST (paginated SELECT *) tool for a table."""
        table = self.schema.get_table(table_name)
        if not table:
            return

        docstring = (
            f"List rows from '{table_name}' with pagination.\n\n"
            f"Parameters:\n"
            f"  - limit (INTEGER): Maximum rows to return (default: 20, max: 100)\n"
            f"  - offset (INTEGER): Number of rows to skip (default: 0)\n\n"
            f"Table has {table.row_count} total rows.\n"
            f"Columns: {', '.join(table.column_names)}"
        )

        fn = _make_list_fn(table_name, f"list_{table_name}", self.validator)
        self.mcp.tool(name=f"list_{table_name}", description=docstring)(fn)
        self._registered_tools.append(f"list_{table_name}")

    def _generate_search_tool(self, table_name: str) -> None:
        """Generate a SEARCH tool for text columns."""
        table = self.schema.get_table(table_name)
        if not table:
            return

        text_cols = [c for c in table.columns if c.data_type.upper() in ("TEXT", "VARCHAR", "CHAR", "")]
        if not text_cols:
            return

        col_names = [c.name for c in text_cols]
        docstring = (
            f"Search '{table_name}' across text columns.\n\n"
            f"Parameters:\n"
            f"  - query (TEXT): Search term (uses SQL LIKE with wildcards)\n\n"
            f"Searches columns: {', '.join(col_names)}\n"
            f"Returns matching rows (max 50)."
        )

        fn = _make_search_fn(table_name, f"search_{table_name}", self.validator, col_names)
        self.mcp.tool(name=f"search_{table_name}", description=docstring)(fn)
        self._registered_tools.append(f"search_{table_name}")
