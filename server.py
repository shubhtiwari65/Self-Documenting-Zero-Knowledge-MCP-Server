"""
Self-Documenting Zero-Knowledge MCP Server
============================================
Main entry point for the MCP server.

This server autonomously:
1. Scans an undocumented legacy database at startup
2. Generates CRUD tools for every discovered table
3. Creates prompts explaining how to join tables
4. Enforces Zero-Knowledge security (pre-validated SQL templates only)

Usage:
    # Run with stdio transport (default, for Claude Desktop):
    python server.py

    # Run with SSE transport (for network access):
    python server.py --transport sse --port 8080

    # Specify a custom database path:
    python server.py --db /path/to/database.db

    # Seed a demo database first:
    python server.py --seed
"""

import os
import sys
import json
import logging
import argparse

from mcp.server.fastmcp import FastMCP

from src.introspector import DatabaseIntrospector
from src.schema_registry import SchemaRegistry
from src.sql_templates import SQLTemplateGenerator
from src.security import ZeroKnowledgeValidator
from src.crud_generator import CRUDGenerator
from src.join_analyzer import JoinAnalyzer

# ── Logging setup (stderr only — stdout is reserved for MCP protocol) ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("zk-mcp-server")


# ── Default paths ──
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "legacy_store.db")


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Self-Documenting Zero-Knowledge MCP Server"
    )
    parser.add_argument(
        "--db", default=DEFAULT_DB_PATH,
        help=f"Path to the SQLite database (default: {DEFAULT_DB_PATH})"
    )
    parser.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio",
        help="MCP transport method (default: stdio)"
    )
    parser.add_argument(
        "--port", type=int, default=8080,
        help="Port for SSE transport (default: 8080)"
    )
    parser.add_argument(
        "--seed", action="store_true",
        help="Seed a demo legacy database before starting"
    )
    return parser.parse_args()


def seed_database(db_path: str) -> None:
    """Seed a demo legacy database."""
    from sample_data.seed_legacy_db import seed_database as _seed
    _seed(db_path)


def build_server(db_path: str) -> FastMCP:
    """
    Build the MCP server by introspecting the database and registering
    all tools, resources, and prompts.
    """
    # ── Step 1: Verify database exists ──
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        logger.error("Run with --seed flag to create a demo database, or specify --db path")
        sys.exit(1)

    logger.info(f"═══════════════════════════════════════════════════════")
    logger.info(f"  Self-Documenting Zero-Knowledge MCP Server")
    logger.info(f"  Database: {db_path}")
    logger.info(f"═══════════════════════════════════════════════════════")

    # ── Step 2: Introspect the database ──
    logger.info("Phase 1: Introspecting database schema...")
    introspector = DatabaseIntrospector(db_path)
    schema = introspector.introspect()

    # ── Step 3: Build schema registry ──
    logger.info("Phase 2: Building schema registry...")
    registry = SchemaRegistry(schema)

    # ── Step 4: Generate SQL templates ──
    logger.info("Phase 3: Generating pre-validated SQL templates...")
    template_generator = SQLTemplateGenerator(registry)
    template_registry = template_generator.generate_all()

    # ── Step 5: Initialize security validator ──
    logger.info("Phase 4: Initializing Zero-Knowledge security validator...")
    validator = ZeroKnowledgeValidator(db_path, template_registry)

    # ── Step 6: Create MCP server ──
    mcp = FastMCP(
        "ZK-MCP-Server",
        instructions=(
            "Self-documenting MCP server that autonomously discovers database "
            "schema and provides secure CRUD operations through pre-validated "
            "SQL templates. Zero-Knowledge security ensures no raw SQL execution."
        ),
    )

    # ── Step 7: Register CRUD tools ──
    logger.info("Phase 5: Generating CRUD tools for all tables...")
    crud_generator = CRUDGenerator(mcp, registry, validator)
    tools = crud_generator.generate_all_tools()

    # ── Step 8: Analyze joins and register prompts ──
    logger.info("Phase 6: Analyzing relationships and generating prompts...")
    join_analyzer = JoinAnalyzer(mcp, registry, validator)
    prompts = join_analyzer.analyze_and_register()

    # ── Step 9: Register schema resources ──
    logger.info("Phase 7: Registering schema resources...")
    _register_resources(mcp, registry, validator)

    # ── Summary ──
    logger.info(f"═══════════════════════════════════════════════════════")
    logger.info(f"  Server ready!")
    logger.info(f"  Tables discovered: {len(registry.get_table_names())}")
    logger.info(f"  CRUD tools registered: {len(tools)}")
    logger.info(f"  Prompts registered: {len(prompts)}")
    logger.info(f"  SQL templates: {template_registry.count}")
    logger.info(f"  Security: Zero-Knowledge mode (template-only execution)")
    logger.info(f"═══════════════════════════════════════════════════════")

    return mcp


def _register_resources(
    mcp: FastMCP,
    registry: SchemaRegistry,
    validator: ZeroKnowledgeValidator,
) -> None:
    """Register MCP resources for schema information and audit logs."""

    # Resource: Full schema overview
    @mcp.resource("schema://tables")
    def schema_tables() -> str:
        """Complete database schema overview — all tables, columns, and relationships."""
        return registry.get_full_schema_summary()

    # Resource: Individual table details
    def _make_table_resource(tn):
        def table_schema() -> str:
            return registry.get_table_summary(tn)
        return table_schema

    for table_name in registry.get_table_names():
        fn = _make_table_resource(table_name)
        mcp.resource(
            f"schema://tables/{table_name}",
            name=f"schema_{table_name}",
            description=f"Detailed schema for the '{table_name}' table",
        )(fn)

    # Resource: Security audit log
    @mcp.resource("security://audit-log")
    def audit_log() -> str:
        """Recent query audit log — shows all executed operations with timestamps."""
        log = validator.get_audit_log(limit=50)
        return json.dumps(log, indent=2)

    # Resource: Security report
    @mcp.resource("security://report")
    def security_report() -> str:
        """Security summary — total queries, success/failure counts, recent violations."""
        report = validator.get_security_report()
        return json.dumps(report, indent=2)

    # Resource: Registered SQL templates
    @mcp.resource("security://templates")
    def sql_templates() -> str:
        """All registered SQL templates — the ONLY queries allowed to execute."""
        templates = validator.template_registry.list_templates()
        return json.dumps([t.to_dict() for t in templates], indent=2)


# ── Main ──
args = parse_args()

# Seed if requested
if args.seed:
    logger.info("Seeding demo legacy database...")
    seed_database(args.db)

# Build and store the server
mcp = build_server(args.db)

if __name__ == "__main__":
    # Run the server
    if args.transport == "sse":
        mcp.run(transport="sse", port=args.port)
    else:
        mcp.run(transport="stdio")
