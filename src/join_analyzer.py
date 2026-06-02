"""
Join Analyzer & Prompt Generator
==================================
Analyzes foreign key relationships discovered during introspection
and generates MCP prompts that explain how to join tables together.

Features:
- Detects one-to-many and many-to-many relationships
- Generates human-readable join explanations
- Creates pre-validated join query templates
- Provides data exploration guides
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.schema_registry import SchemaRegistry
from src.security import ZeroKnowledgeValidator

logger = logging.getLogger(__name__)


@dataclass
class Relationship:
    """Represents a discovered table relationship."""
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    relationship_type: str  # "one-to-many", "many-to-many"
    junction_table: str | None = None


class JoinAnalyzer:
    """
    Analyzes foreign key relationships and generates MCP prompts
    that explain how to join tables in the database.
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
        self.relationships: list[Relationship] = []
        self._registered_prompts: list[str] = []

    def analyze_and_register(self) -> list[str]:
        """
        Analyze all relationships and register MCP prompts.
        
        Returns a list of registered prompt names.
        """
        self._discover_relationships()
        self._register_join_prompts()
        self._register_exploration_prompt()
        self._register_schema_prompt()

        logger.info(
            f"Discovered {len(self.relationships)} relationships, "
            f"registered {len(self._registered_prompts)} prompts"
        )
        return self._registered_prompts

    def _discover_relationships(self) -> None:
        """Discover and classify all table relationships."""
        all_fks = self.schema.get_all_relationships()
        
        # Track which tables are junction tables (have 2+ FKs and primarily serve as connectors)
        table_fk_counts = {}
        for fk in all_fks:
            table_fk_counts[fk.from_table] = table_fk_counts.get(fk.from_table, 0) + 1

        # Identify junction tables (tables with 2+ FKs and few own columns)
        junction_tables = set()
        for table_name, fk_count in table_fk_counts.items():
            if fk_count >= 2:
                table = self.schema.get_table(table_name)
                if table:
                    # A junction table typically has FKs + maybe an ID + a few extra columns
                    non_fk_non_pk = len([
                        c for c in table.columns 
                        if not c.is_primary_key and c.name not in [
                            fk.from_column for fk in table.foreign_keys
                        ]
                    ])
                    if non_fk_non_pk <= 3:  # Allow a few extra columns (qty, price, etc.)
                        junction_tables.add(table_name)

        # Build relationships
        for fk in all_fks:
            if fk.from_table in junction_tables:
                # This FK is part of a many-to-many via junction table
                # Find the other FK in the same junction table
                other_fks = [
                    f for f in all_fks 
                    if f.from_table == fk.from_table and f.to_table != fk.to_table
                ]
                for other_fk in other_fks:
                    # Only add one direction to avoid duplicates
                    if fk.to_table < other_fk.to_table:
                        self.relationships.append(Relationship(
                            from_table=fk.to_table,
                            from_column=fk.to_column,
                            to_table=other_fk.to_table,
                            to_column=other_fk.to_column,
                            relationship_type="many-to-many",
                            junction_table=fk.from_table,
                        ))
            
            # Always add direct one-to-many relationship
            self.relationships.append(Relationship(
                from_table=fk.from_table,
                from_column=fk.from_column,
                to_table=fk.to_table,
                to_column=fk.to_column,
                relationship_type="one-to-many",
            ))

    def _generate_relationship_text(self, rel: Relationship) -> str:
        """Generate human-readable explanation of a relationship."""
        if rel.relationship_type == "many-to-many":
            return (
                f"## Many-to-Many: {rel.from_table} ↔ {rel.to_table}\n\n"
                f"These tables are connected through the junction table '{rel.junction_table}'.\n\n"
                f"**How to join:**\n"
                f"```sql\n"
                f"SELECT a.*, b.*\n"
                f"FROM {rel.from_table} a\n"
                f"INNER JOIN {rel.junction_table} j ON a.{rel.from_column} = j.{self._find_fk_column(rel.junction_table, rel.from_table)}\n"
                f"INNER JOIN {rel.to_table} b ON j.{self._find_fk_column(rel.junction_table, rel.to_table)} = b.{rel.to_column}\n"
                f"```\n\n"
                f"**Relationship**: Many {rel.from_table} can be associated with many {rel.to_table}.\n"
                f"**Use case**: Find all {rel.to_table} related to a specific {rel.from_table} (or vice versa).\n"
            )
        else:
            return (
                f"## One-to-Many: {rel.to_table} → {rel.from_table}\n\n"
                f"Each row in '{rel.to_table}' can have many related rows in '{rel.from_table}'.\n\n"
                f"**Join column**: `{rel.from_table}.{rel.from_column}` → `{rel.to_table}.{rel.to_column}`\n\n"
                f"**How to join:**\n"
                f"```sql\n"
                f"SELECT a.*, b.*\n"
                f"FROM {rel.from_table} a\n"
                f"INNER JOIN {rel.to_table} b ON a.{rel.from_column} = b.{rel.to_column}\n"
                f"```\n\n"
                f"**Use case**: Get {rel.from_table} data along with their parent {rel.to_table} info.\n"
            )

    def _find_fk_column(self, junction_table: str, target_table: str) -> str:
        """Find the FK column in a junction table that points to the target table."""
        fks = self.schema.get_foreign_keys(junction_table)
        for fk in fks:
            if fk.to_table == target_table:
                return fk.from_column
        return "id"  # fallback

    def _register_join_prompts(self) -> None:
        """Register MCP prompts for each relationship."""
        
        # Group relationships by table pairs for a cleaner prompt
        seen_pairs = set()
        
        for rel in self.relationships:
            pair_key = tuple(sorted([rel.from_table, rel.to_table]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            
            prompt_name = f"join_{pair_key[0]}_and_{pair_key[1]}"
            explanation = self._generate_relationship_text(rel)

            def make_join_prompt(exp):
                def join_prompt() -> str:
                    return exp
                return join_prompt

            fn = make_join_prompt(explanation)
            self.mcp.prompt(name=prompt_name, description=f"Explains how to join {pair_key[0]} and {pair_key[1]} tables")(fn)
            self._registered_prompts.append(prompt_name)

    def _register_exploration_prompt(self) -> None:
        """Register a prompt that guides data exploration."""
        
        table_summaries = []
        for table_name in self.schema.get_table_names():
            table = self.schema.get_table(table_name)
            if table:
                cols = ", ".join(table.column_names[:5])
                if len(table.column_names) > 5:
                    cols += f", ... ({len(table.column_names)} total)"
                table_summaries.append(
                    f"- **{table_name}** ({table.row_count} rows): {cols}"
                )

        relationship_summary = []
        for rel in self.relationships:
            if rel.relationship_type == "many-to-many":
                relationship_summary.append(
                    f"- {rel.from_table} ↔ {rel.to_table} (many-to-many via {rel.junction_table})"
                )
            else:
                relationship_summary.append(
                    f"- {rel.from_table}.{rel.from_column} → {rel.to_table}.{rel.to_column} (one-to-many)"
                )

        guide_text = (
            f"# Database Exploration Guide\n\n"
            f"## Available Tables\n"
            + "\n".join(table_summaries)
            + f"\n\n## Relationships\n"
            + "\n".join(relationship_summary)
            + f"\n\n## Available Operations\n"
            f"For each table, you can:\n"
            f"- `list_{{table}}` — Browse rows with pagination\n"
            f"- `read_{{table}}` — Get a specific row by primary key\n"
            f"- `create_{{table}}` — Insert a new row\n"
            f"- `update_{{table}}` — Update a row by primary key\n"
            f"- `delete_{{table}}` — Delete a row by primary key\n"
            f"- `search_{{table}}` — Search across text columns\n"
            f"\n## Tips\n"
            f"- All operations go through pre-validated SQL templates for security\n"
            f"- Use join prompts to understand how tables relate to each other\n"
            f"- Start with `list_{{table}}` to explore data before making changes\n"
        )

        @self.mcp.prompt(name="explore_database", description="Complete guide to exploring this database — tables, relationships, and available operations")
        def exploration_prompt() -> str:
            return guide_text

        self._registered_prompts.append("explore_database")

    def _register_schema_prompt(self) -> None:
        """Register a prompt that shows the full schema."""

        schema_text = self.schema.get_full_schema_summary()
        full_text = (
            f"# Complete Database Schema\n\n"
            f"Below is the complete schema discovered by autonomous introspection.\n"
            f"No prior documentation was available — all metadata was extracted at runtime.\n\n"
            f"```\n{schema_text}\n```\n\n"
            f"## Security Note\n"
            f"All queries are restricted to pre-validated SQL templates. "
            f"No raw SQL can be executed. All parameters are type-checked and sanitized.\n"
        )

        @self.mcp.prompt(name="show_schema", description="Display the complete auto-discovered database schema")
        def schema_prompt() -> str:
            return full_text

        self._registered_prompts.append("show_schema")
