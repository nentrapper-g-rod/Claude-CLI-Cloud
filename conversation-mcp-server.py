#!/usr/bin/env python3
"""
Conversation History MCP Server
Exposes conversation database to Claude CLI via Model Context Protocol
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, Sequence
import json

# Add conversation_db to path
sys.path.insert(0, str(Path.home() / '.claude-bridge'))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
)

try:
    from conversation_db import get_db
except ImportError:
    print("Error: conversation_db module not found", file=sys.stderr)
    sys.exit(1)

# Initialize database
db = get_db()

# Create MCP server
app = Server("conversation-history")


@app.list_resources()
async def list_resources() -> list[Resource]:
    """List available conversation resources"""
    return [
        Resource(
            uri="conversation://sessions",
            name="All Conversation Sessions",
            description="List all conversation sessions across all connections",
            mimeType="application/json"
        ),
        Resource(
            uri="conversation://recent",
            name="Recent Conversations",
            description="Get the 20 most recent conversation sessions",
            mimeType="application/json"
        ),
        Resource(
            uri="conversation://connections",
            name="Connection List",
            description="List all available connections/machines",
            mimeType="application/json"
        ),
    ]


@app.read_resource()
async def read_resource(uri: str) -> str:
    """Read conversation resource content"""

    if uri == "conversation://sessions":
        # Get all sessions
        sessions = db.get_sessions(limit=1000)
        return json.dumps(sessions, indent=2)

    elif uri == "conversation://recent":
        # Get recent sessions
        sessions = db.get_sessions(limit=20)
        return json.dumps(sessions, indent=2)

    elif uri == "conversation://connections":
        # Get all connections
        connections = db.get_connections()
        return json.dumps(connections, indent=2)

    elif uri.startswith("conversation://session/"):
        # Get specific session messages
        session_id = uri.split("/")[-1]
        messages = db.get_session_messages(session_id, limit=1000)
        return json.dumps(messages, indent=2)

    else:
        raise ValueError(f"Unknown resource URI: {uri}")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available conversation tools"""
    return [
        Tool(
            name="search_conversations",
            description="Search through all conversation messages for specific content. Returns matching messages with context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find in message content"
                    },
                    "connection_name": {
                        "type": "string",
                        "description": "Optional: Filter by connection/machine name"
                    },
                    "limit": {
                        "type": "number",
                        "description": "Maximum number of results (default: 50)",
                        "default": 50
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_session_messages",
            description="Get all messages from a specific conversation session",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "The session ID to retrieve messages from"
                    },
                    "limit": {
                        "type": "number",
                        "description": "Maximum number of messages (default: 100)",
                        "default": 100
                    }
                },
                "required": ["session_id"]
            }
        ),
        Tool(
            name="get_recent_sessions",
            description="Get recent conversation sessions with summary info",
            inputSchema={
                "type": "object",
                "properties": {
                    "connection_name": {
                        "type": "string",
                        "description": "Optional: Filter by connection/machine name"
                    },
                    "limit": {
                        "type": "number",
                        "description": "Number of sessions to retrieve (default: 10)",
                        "default": 10
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_sessions_by_project",
            description="Get all conversation sessions for a specific project",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project name to filter sessions"
                    }
                },
                "required": ["project"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    """Handle tool calls"""

    if name == "search_conversations":
        query = arguments.get("query")
        connection_name = arguments.get("connection_name")
        limit = arguments.get("limit", 50)

        results = db.search_messages(
            query=query,
            connection_name=connection_name,
            limit=limit
        )

        return [
            TextContent(
                type="text",
                text=json.dumps(results, indent=2)
            )
        ]

    elif name == "get_session_messages":
        session_id = arguments.get("session_id")
        limit = arguments.get("limit", 100)

        messages = db.get_session_messages(
            session_id=session_id,
            limit=limit
        )

        return [
            TextContent(
                type="text",
                text=json.dumps(messages, indent=2)
            )
        ]

    elif name == "get_recent_sessions":
        connection_name = arguments.get("connection_name")
        limit = arguments.get("limit", 10)

        sessions = db.get_sessions(
            connection_name=connection_name,
            limit=limit
        )

        return [
            TextContent(
                type="text",
                text=json.dumps(sessions, indent=2)
            )
        ]

    elif name == "get_sessions_by_project":
        project = arguments.get("project")

        # Get sessions filtered by project
        sessions = db.get_sessions(limit=1000)
        filtered = [s for s in sessions if s.get('project') == project]

        return [
            TextContent(
                type="text",
                text=json.dumps(filtered, indent=2)
            )
        ]

    else:
        raise ValueError(f"Unknown tool: {name}")


async def main():
    """Run the MCP server via stdio"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
