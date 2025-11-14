#!/usr/bin/env python3
"""
FileMaker Bridge Server
Version: 1.0.0
Purpose: WebSocket server for FileMaker database integration with Claude
Runs on port 8767 (separate from Claude bridge on 8766)
"""

import asyncio
import websockets
import json
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import traceback
import aiohttp
import base64

try:
    from anthropic import Anthropic
    import aiofiles
    from conversation_db import get_db
except ImportError:
    print("ERROR: Required dependencies not installed.")
    print("Please install: pip install anthropic aiofiles websockets aiohttp")
    sys.exit(1)


class FileMakerDataAPI:
    """FileMaker Server Data API client"""

    def __init__(self, host: str, database: str, username: str, password: str, use_https: bool = True):
        self.host = host
        self.database = database
        self.username = username
        self.password = password
        self.protocol = 'https' if use_https else 'http'
        self.base_url = f"{self.protocol}://{self.host}/fmi/data/v1"
        self.token = None
        self.session = None

    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession()
        await self.login()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.token:
            try:
                await self.logout()
            except:
                pass
        if self.session:
            await self.session.close()

    async def login(self):
        """Authenticate and get session token"""
        url = f"{self.base_url}/databases/{self.database}/sessions"
        auth = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json"
        }

        print(f"\n{'='*60}")
        print(f"FileMaker Data API - Login Request")
        print(f"{'='*60}")
        print(f"  Method: POST")
        print(f"  URL: {url}")
        print(f"  Headers: {{'Authorization': 'Basic ***', 'Content-Type': 'application/json'}}")
        print(f"  Body: {{}}")
        print(f"  User: {self.username}")
        print(f"  Database: {self.database}")

        async with self.session.post(url, headers=headers, json={}, ssl=False) as response:
            print(f"\nFileMaker Data API - Login Response")
            print(f"  Status: {response.status}")
            print(f"  Reason: {response.reason}")

            if response.status == 200:
                data = await response.json()
                self.token = data['response']['token']

                print(f"  Response Body:")
                print(f"    messages: {data.get('messages', [])}")
                print(f"    response.token: {self.token}")
                print(f"\n✓ FileMaker Data API: Login successful!")
                print(f"  Session Token: {self.token}")
                print(f"{'='*60}\n")

                return self.token
            else:
                error_text = await response.text()
                print(f"  Error Response: {error_text}")
                print(f"✗ FileMaker Data API: Login failed!")
                print(f"{'='*60}\n")
                raise Exception(f"FileMaker login failed: {response.status} - {error_text}")

    async def logout(self):
        """End the session"""
        if not self.token:
            return

        url = f"{self.base_url}/databases/{self.database}/sessions/{self.token}"
        headers = {"Content-Type": "application/json"}

        print(f"\n{'='*60}")
        print(f"FileMaker Data API - Logout Request")
        print(f"{'='*60}")
        print(f"  Method: DELETE")
        print(f"  URL: {url}")
        print(f"  Token: {self.token}")

        async with self.session.delete(url, headers=headers, ssl=False) as response:
            print(f"\nFileMaker Data API - Logout Response")
            print(f"  Status: {response.status}")
            print(f"  Reason: {response.reason}")

            if response.status == 200:
                data = await response.json()
                print(f"  Response Body:")
                print(f"    messages: {data.get('messages', [])}")
                print(f"\n✓ FileMaker Data API: Logout successful!")
                print(f"{'='*60}\n")
                self.token = None
            else:
                error_text = await response.text()
                print(f"  Error Response: {error_text}")
                print(f"✗ FileMaker Data API: Logout failed!")
                print(f"{'='*60}\n")

    async def get_records(self, layout: str, offset: int = 1, limit: int = 100, query: dict = None):
        """Get records from a layout"""
        if not self.token:
            await self.login()

        url = f"{self.base_url}/databases/{self.database}/layouts/{layout}/records"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        params = {"_offset": offset, "_limit": limit}

        async with self.session.get(url, headers=headers, params=params, ssl=False) as response:
            if response.status == 200:
                data = await response.json()
                return data['response']['data']
            else:
                error_text = await response.text()
                raise Exception(f"Get records failed: {response.status} - {error_text}")

    async def find_records(self, layout: str, query: List[Dict], offset: int = 1, limit: int = 100):
        """Find records using query"""
        if not self.token:
            await self.login()

        url = f"{self.base_url}/databases/{self.database}/layouts/{layout}/_find"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        body = {
            "query": query,
            "offset": str(offset),
            "limit": str(limit)
        }

        async with self.session.post(url, headers=headers, json=body, ssl=False) as response:
            if response.status == 200:
                data = await response.json()
                return data['response']['data']
            else:
                error_text = await response.text()
                raise Exception(f"Find records failed: {response.status} - {error_text}")

    async def create_record(self, layout: str, field_data: dict):
        """Create a new record"""
        if not self.token:
            await self.login()

        url = f"{self.base_url}/databases/{self.database}/layouts/{layout}/records"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        body = {"fieldData": field_data}

        async with self.session.post(url, headers=headers, json=body, ssl=False) as response:
            if response.status == 200:
                data = await response.json()
                return data['response']
            else:
                error_text = await response.text()
                raise Exception(f"Create record failed: {response.status} - {error_text}")

    async def update_record(self, layout: str, record_id: int, field_data: dict):
        """Update an existing record"""
        if not self.token:
            await self.login()

        url = f"{self.base_url}/databases/{self.database}/layouts/{layout}/records/{record_id}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        body = {"fieldData": field_data}

        async with self.session.patch(url, headers=headers, json=body, ssl=False) as response:
            if response.status == 200:
                data = await response.json()
                return data['response']
            else:
                error_text = await response.text()
                raise Exception(f"Update record failed: {response.status} - {error_text}")

    async def delete_record(self, layout: str, record_id: int):
        """Delete a record"""
        if not self.token:
            await self.login()

        url = f"{self.base_url}/databases/{self.database}/layouts/{layout}/records/{record_id}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        async with self.session.delete(url, headers=headers, ssl=False) as response:
            if response.status == 200:
                data = await response.json()
                return data['response']
            else:
                error_text = await response.text()
                raise Exception(f"Delete record failed: {response.status} - {error_text}")

    async def get_layouts(self):
        """Get list of available layouts"""
        if not self.token:
            await self.login()

        url = f"{self.base_url}/databases/{self.database}/layouts"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        print(f"\nFileMaker Data API - Get Layouts Request")
        print(f"  Method: GET")
        print(f"  URL: {url}")
        print(f"  Token: {self.token[:20]}...")

        async with self.session.get(url, headers=headers, ssl=False) as response:
            print(f"  Response Status: {response.status}")

            if response.status == 200:
                data = await response.json()
                layouts = data['response']['layouts']
                print(f"  ✓ Retrieved {len(layouts)} layouts")
                return layouts
            else:
                error_text = await response.text()
                print(f"  ✗ Error: {error_text}")
                raise Exception(f"Get layouts failed: {response.status} - {error_text}")


class FileMakerBridgeServer:
    """WebSocket server for FileMaker integration"""

    def __init__(self, machine_name: str, filemaker_data_dir: str = None, api_key: Optional[str] = None,
                 fms_host: str = None, fms_database: str = None, fms_username: str = None, fms_password: str = None):
        self.machine_name = machine_name
        self.version = "1.2.0"

        # FMS API configuration (can be set later via configure_fms message)
        self.fms_host = fms_host
        self.fms_database = fms_database
        self.fms_username = fms_username
        self.fms_password = fms_password

        # FileMaker data directory (for storing FileMaker-related data)
        if filemaker_data_dir:
            self.data_dir = Path(filemaker_data_dir).expanduser()
        else:
            # Default to ~/.filemaker-bridge
            self.data_dir = Path.home() / '.filemaker-bridge'

        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Try to get API key from: 1) parameter, 2) env var
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY')

        if not self.api_key or self.api_key == 'test-key':
            print("WARNING: No valid API key found")
            print("Set via: --api-key or ANTHROPIC_API_KEY env var")
            self.api_key = self.api_key or 'test-key'

        self.anthropic = Anthropic(api_key=self.api_key)
        self.clients = set()

        # FileMaker Server configuration
        self.fms_host = fms_host or os.getenv('FMS_HOST')
        self.fms_username = fms_username or os.getenv('FMS_USERNAME')
        self.fms_password = fms_password or os.getenv('FMS_PASSWORD')

        # Store FMS API connections per database
        self.fms_connections = {}  # {database_name: FileMakerDataAPI}

        # Store persistent FMS API connection for configured database
        self.persistent_fms_api = None

        # Database connection for session metadata
        try:
            self.db = get_db()
        except Exception as e:
            print(f"Warning: Could not connect to database: {e}")
            self.db = None

        # Session cache for FileMaker sessions
        # {session_id: {messages: [], metadata: {}, filemaker_database: str, fms_api: FileMakerDataAPI}}
        self.session_cache = {}

        # Track available FileMaker databases
        self.available_databases = []
        if self.fms_host and self.fms_username and self.fms_password:
            print(f"FileMaker Server configured: {self.fms_host}")
        else:
            print("WARNING: FileMaker Server not configured. Set FMS_HOST, FMS_USERNAME, FMS_PASSWORD env vars")
            print("         Or use --fms-host, --fms-username, --fms-password command line args")

        # Heartbeat task to keep FMS API connection alive
        self.heartbeat_task = None
        self.heartbeat_interval = 60  # 60 seconds to keep session active in FMS Admin Console

    async def keep_fms_connection_alive(self):
        """Background task to keep FMS API connection alive"""
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)

                if self.persistent_fms_api and self.persistent_fms_api.token:
                    print(f"[{datetime.now().isoformat()}] FMS API heartbeat - checking connection...")
                    print(f"  Token: {self.persistent_fms_api.token[:20]}...")
                    print(f"  Database: {self.persistent_fms_api.database}")
                    print(f"  Host: {self.persistent_fms_api.host}")

                    try:
                        # Test the connection by getting layouts (lightweight operation)
                        layouts = await self.persistent_fms_api.get_layouts()
                        print(f"✓ FMS API connection alive - {len(layouts)} layouts available")
                        print(f"✓ Session active in FileMaker Server")

                        # Notify all connected clients that API is still connected
                        for client in self.clients:
                            try:
                                await client.send(json.dumps({
                                    "type": "fms_api_status",
                                    "connected": True,
                                    "message": f"Connected to {self.fms_host} / {self.fms_database}"
                                }))
                            except:
                                pass

                    except Exception as e:
                        print(f"✗ FMS API connection lost: {e}")
                        print(f"→ Attempting to reconnect...")

                        try:
                            # Try to re-login
                            await self.persistent_fms_api.login()
                            print(f"✓ FMS API reconnected successfully")

                            # Notify clients of reconnection
                            for client in self.clients:
                                try:
                                    await client.send(json.dumps({
                                        "type": "fms_api_status",
                                        "connected": True,
                                        "message": f"Reconnected to {self.fms_host} / {self.fms_database}"
                                    }))
                                except:
                                    pass

                        except Exception as reconnect_error:
                            print(f"✗ FMS API reconnection failed: {reconnect_error}")

                            # Notify clients of connection failure
                            for client in self.clients:
                                try:
                                    await client.send(json.dumps({
                                        "type": "fms_api_error",
                                        "error": f"Connection lost: {str(reconnect_error)}",
                                        "connected": False
                                    }))
                                except:
                                    pass

            except asyncio.CancelledError:
                print("FMS API heartbeat task cancelled")
                break
            except Exception as e:
                print(f"Error in FMS API heartbeat: {e}")

    def get_fms_api(self, database: str) -> FileMakerDataAPI:
        """Get or create FMS API connection for a database"""
        if not self.fms_host or not self.fms_username or not self.fms_password:
            raise Exception("FileMaker Server not configured")

        if database not in self.fms_connections:
            self.fms_connections[database] = FileMakerDataAPI(
                host=self.fms_host,
                database=database,
                username=self.fms_username,
                password=self.fms_password
            )

        return self.fms_connections[database]

    async def handle_client(self, websocket):
        """Handle incoming WebSocket connections"""
        try:
            self.clients.add(websocket)
            client_address = websocket.remote_address
            print(f"[{datetime.now().isoformat()}] Client connected from {client_address}")

            # Send handshake with capability info
            await self.send_handshake(websocket)

            # Handle messages
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.handle_message(websocket, data)
                except json.JSONDecodeError as e:
                    print(f"Invalid JSON received: {e}")
                    await self.send_error(websocket, "Invalid JSON format")
                except Exception as e:
                    print(f"Error handling message: {e}")
                    traceback.print_exc()
                    await self.send_error(websocket, str(e))

        except websockets.exceptions.ConnectionClosed:
            print(f"[{datetime.now().isoformat()}] Client disconnected: {client_address}")
        except Exception as e:
            print(f"Error in client handler: {e}")
            traceback.print_exc()
        finally:
            self.clients.discard(websocket)

    async def send_handshake(self, websocket):
        """Send handshake message with capability info"""
        fms_configured = bool(self.fms_host and self.fms_username and self.fms_password)

        handshake = {
            "type": "handshake",
            "has_filemaker": True,
            "version": self.version,
            "machine_name": self.machine_name,
            "capabilities": {
                "fms_api": fms_configured,
                "fms_host": self.fms_host if fms_configured else None,
                "session_types": ["claude", "filemaker"]
            }
        }
        await websocket.send(json.dumps(handshake))
        print(f"[{datetime.now().isoformat()}] Sent handshake to client (FMS API: {'enabled' if fms_configured else 'disabled'})")

    async def send_error(self, websocket, error_message: str):
        """Send error message to client"""
        error_data = {
            "type": "error",
            "message": error_message,
            "timestamp": datetime.now().isoformat()
        }
        await websocket.send(json.dumps(error_data))

    async def handle_message(self, websocket, data: Dict):
        """Handle incoming message based on type"""
        msg_type = data.get('type')

        print(f"[{datetime.now().isoformat()}] Received message type: {msg_type}")

        if msg_type == 'configure_fms':
            await self.handle_configure_fms(websocket, data)

        elif msg_type == 'list_hosted_databases':
            await self.handle_list_hosted_databases(websocket, data)

        elif msg_type == 'list_filemaker_files':
            await self.handle_list_files(websocket)

        elif msg_type == 'create_filemaker_session':
            await self.handle_create_session(websocket, data)

        elif msg_type == 'send_message':
            await self.handle_send_message(websocket, data)

        elif msg_type == 'get_sessions':
            await self.handle_get_sessions(websocket, data)

        elif msg_type == 'close_session':
            await self.handle_close_session(websocket, data)

        elif msg_type == 'list_bridge_scripts':
            await self.handle_list_bridge_scripts(websocket, data)

        elif msg_type == 'get_bridge_script':
            await self.handle_get_bridge_script(websocket, data)

        else:
            await self.send_error(websocket, f"Unknown message type: {msg_type}")

    async def handle_list_hosted_databases(self, websocket, data: Dict):
        """Query FMS Admin API to get list of hosted databases"""
        fms_host = data.get('fms_host')
        admin_username = data.get('admin_username')
        admin_password = data.get('admin_password')

        print(f"[{datetime.now().isoformat()}] Listing hosted databases on {fms_host}")

        if not fms_host or not admin_username or not admin_password:
            error_msg = "Missing FMS host or admin credentials"
            print(f"ERROR: {error_msg}")
            await websocket.send(json.dumps({
                "type": "hosted_databases_error",
                "error": error_msg
            }))
            return

        try:
            # Call FMS Admin API
            url = f"https://{fms_host}/fmi/admin/api/v2/databases"
            auth = base64.b64encode(f"{admin_username}:{admin_password}".encode()).decode()
            headers = {
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, ssl=False) as response:
                    if response.status == 200:
                        result = await response.json()
                        databases = result.get('response', {}).get('databases', [])

                        # Extract just the filenames
                        db_list = [db.get('filename') or db.get('name') for db in databases]

                        print(f"✓ Found {len(db_list)} hosted databases")
                        await websocket.send(json.dumps({
                            "type": "hosted_databases_list",
                            "databases": db_list
                        }))
                    else:
                        error_text = await response.text()
                        error_msg = f"FMS Admin API returned {response.status}: {error_text}"
                        print(f"✗ {error_msg}")
                        await websocket.send(json.dumps({
                            "type": "hosted_databases_error",
                            "error": error_msg
                        }))

        except Exception as e:
            error_msg = str(e)
            print(f"✗ Failed to list hosted databases: {error_msg}")
            await websocket.send(json.dumps({
                "type": "hosted_databases_error",
                "error": error_msg
            }))

    async def handle_configure_fms(self, websocket, data: Dict):
        """Configure FMS API connection with credentials from client"""
        fms_host = data.get('fms_host')
        fms_database = data.get('fms_database')
        fms_username = data.get('fms_username')
        fms_password = data.get('fms_password')

        print(f"[{datetime.now().isoformat()}] Configuring FMS API: {fms_host} / {fms_database}")

        if not fms_host or not fms_database or not fms_username or not fms_password:
            error_msg = "Missing FMS credentials (host, database, username, or password)"
            print(f"ERROR: {error_msg}")
            await websocket.send(json.dumps({
                "type": "fms_api_error",
                "error": error_msg
            }))
            return

        # Update server configuration
        self.fms_host = fms_host
        self.fms_database = fms_database
        self.fms_username = fms_username
        self.fms_password = fms_password

        # Close existing persistent connection if any
        if self.persistent_fms_api:
            try:
                await self.persistent_fms_api.logout()
                if self.persistent_fms_api.session:
                    await self.persistent_fms_api.session.close()
                print(f"✓ Closed previous FMS API connection")
            except Exception as e:
                print(f"Warning: Error closing previous connection: {e}")

        # Create and maintain persistent connection to FMS API
        try:
            # Create persistent API connection
            self.persistent_fms_api = FileMakerDataAPI(
                host=self.fms_host,
                database=self.fms_database,
                username=self.fms_username,
                password=self.fms_password
            )

            # Initialize session and login
            self.persistent_fms_api.session = aiohttp.ClientSession()
            await self.persistent_fms_api.login()

            print(f"✓ FMS API persistent connection established: {fms_host} / {fms_database}")
            print(f"✓ Session token: {self.persistent_fms_api.token[:20]}...")

            # Start heartbeat task to keep connection alive
            if self.heartbeat_task:
                self.heartbeat_task.cancel()
            self.heartbeat_task = asyncio.create_task(self.keep_fms_connection_alive())
            print(f"✓ FMS API heartbeat started (checking every {self.heartbeat_interval}s)")

            await websocket.send(json.dumps({
                "type": "fms_api_status",
                "connected": True,
                "message": f"Connected to {fms_host} / {fms_database} (persistent)"
            }))

        except Exception as e:
            error_msg = str(e)
            print(f"✗ FMS API connection failed: {error_msg}")
            self.persistent_fms_api = None
            await websocket.send(json.dumps({
                "type": "fms_api_error",
                "error": error_msg,
                "connected": False
            }))

    async def handle_list_files(self, websocket):
        """Send list of available FileMaker files"""
        response = {
            "type": "filemaker_files",
            "files": self.available_files
        }
        await websocket.send(json.dumps(response))

    async def handle_create_session(self, websocket, data: Dict):
        """Create a new FileMaker session"""
        session_id = data.get('session_id')
        filemaker_file = data.get('filemaker_file')
        initial_prompt = data.get('initial_prompt')

        if not session_id or not filemaker_file:
            await self.send_error(websocket, "Missing session_id or filemaker_file")
            return

        # Create session in database with session_type='filemaker'
        if self.db:
            try:
                self.db.upsert_session(
                    session_id=session_id,
                    connection_name=self.machine_name,
                    session_type='filemaker',
                    metadata={'filemaker_file': filemaker_file},
                    session_source='web'
                )
            except Exception as e:
                print(f"Error creating session in database: {e}")

        # Initialize session cache
        self.session_cache[session_id] = {
            "messages": [],
            "metadata": {
                "filemaker_file": filemaker_file,
                "created_at": datetime.now().isoformat()
            }
        }

        # Send confirmation
        response = {
            "type": "session_created",
            "session_id": session_id,
            "filemaker_file": filemaker_file
        }
        await websocket.send(json.dumps(response))

        print(f"[{datetime.now().isoformat()}] Created FileMaker session: {session_id} for file: {filemaker_file}")

    async def handle_send_message(self, websocket, data: Dict):
        """Handle sending a message in a FileMaker session"""
        session_id = data.get('session_id')
        content = data.get('content')

        if not session_id or not content:
            await self.send_error(websocket, "Missing session_id or content")
            return

        # Get session from cache
        session = self.session_cache.get(session_id)
        if not session:
            await self.send_error(websocket, f"Session not found: {session_id}")
            return

        # Add user message to session
        user_message = {
            "role": "user",
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        session["messages"].append(user_message)

        # Send assistant response (placeholder for now)
        assistant_message = {
            "role": "assistant",
            "content": f"FileMaker Bridge v{self.version} - Processing your request for FileMaker file: {session['metadata']['filemaker_file']}",
            "timestamp": datetime.now().isoformat()
        }
        session["messages"].append(assistant_message)

        # Send response to client
        response = {
            "type": "message",
            "session_id": session_id,
            "message": assistant_message
        }
        await websocket.send(json.dumps(response))

        # Save to database
        if self.db:
            try:
                self.db.add_messages(
                    session_id=session_id,
                    connection_name=self.machine_name,
                    messages=[user_message, assistant_message]
                )
            except Exception as e:
                print(f"Error saving messages to database: {e}")

    async def handle_get_sessions(self, websocket, data: Dict):
        """Get FileMaker sessions for this connection"""
        if not self.db:
            await self.send_error(websocket, "Database not available")
            return

        try:
            # Get only FileMaker sessions
            sessions = self.db.get_sessions_by_type(
                session_type='filemaker',
                connection_name=self.machine_name,
                limit=100
            )

            response = {
                "type": "sessions",
                "sessions": sessions
            }
            await websocket.send(json.dumps(response))
        except Exception as e:
            print(f"Error getting sessions: {e}")
            await self.send_error(websocket, f"Error retrieving sessions: {str(e)}")

    async def handle_close_session(self, websocket, data: Dict):
        """Close a FileMaker session"""
        session_id = data.get('session_id')

        if session_id in self.session_cache:
            del self.session_cache[session_id]

        response = {
            "type": "session_closed",
            "session_id": session_id
        }
        await websocket.send(json.dumps(response))

    async def handle_list_bridge_scripts(self, websocket, data: Dict):
        """List FileMaker Bridge scripts from /opt/FileMaker/FileMaker Server/Data/Documents/FM-Bridge-Scripts"""
        scripts_dir = Path("/opt/FileMaker/FileMaker Server/Data/Documents/FM-Bridge-Scripts")

        print(f"[{datetime.now().isoformat()}] Listing bridge scripts from {scripts_dir}")

        try:
            if not scripts_dir.exists():
                print(f"Scripts directory does not exist: {scripts_dir}")
                await websocket.send(json.dumps({
                    "type": "bridge_scripts_list",
                    "scripts": [],
                    "error": "Scripts directory not found"
                }))
                return

            # List all files in the scripts directory
            scripts = []
            for file_path in scripts_dir.iterdir():
                if file_path.is_file():
                    stat_info = file_path.stat()
                    scripts.append({
                        "name": file_path.name,
                        "path": str(file_path),
                        "size": stat_info.st_size,
                        "modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                        "extension": file_path.suffix
                    })

            # Sort by name
            scripts.sort(key=lambda x: x['name'])

            print(f"✓ Found {len(scripts)} bridge scripts")
            await websocket.send(json.dumps({
                "type": "bridge_scripts_list",
                "scripts": scripts,
                "directory": str(scripts_dir)
            }))

        except Exception as e:
            error_msg = str(e)
            print(f"✗ Failed to list bridge scripts: {error_msg}")
            await websocket.send(json.dumps({
                "type": "bridge_scripts_error",
                "error": error_msg
            }))

    async def handle_get_bridge_script(self, websocket, data: Dict):
        """Get contents of a specific bridge script"""
        script_name = data.get('script_name')
        scripts_dir = Path("/opt/FileMaker/FileMaker Server/Data/Documents/FM-Bridge-Scripts")

        if not script_name:
            await self.send_error(websocket, "Missing script_name")
            return

        script_path = scripts_dir / script_name

        print(f"[{datetime.now().isoformat()}] Reading bridge script: {script_path}")

        try:
            if not script_path.exists() or not script_path.is_file():
                print(f"Script not found: {script_path}")
                await websocket.send(json.dumps({
                    "type": "bridge_script_error",
                    "error": f"Script not found: {script_name}"
                }))
                return

            # Read script contents
            async with aiofiles.open(script_path, 'r') as f:
                content = await f.read()

            print(f"✓ Read bridge script: {script_name} ({len(content)} bytes)")
            await websocket.send(json.dumps({
                "type": "bridge_script_content",
                "script_name": script_name,
                "content": content,
                "path": str(script_path)
            }))

        except Exception as e:
            error_msg = str(e)
            print(f"✗ Failed to read bridge script: {error_msg}")
            await websocket.send(json.dumps({
                "type": "bridge_script_error",
                "error": error_msg
            }))

    async def start_server(self, host: str = '0.0.0.0', port: int = 8767):
        """Start the WebSocket server"""
        fms_status = f"Connected ({self.fms_host})" if (self.fms_host and self.fms_username and self.fms_password) else "Not configured"

        print(f"=" * 60)
        print(f"FileMaker Bridge Server v{self.version}")
        print(f"=" * 60)
        print(f"Machine: {self.machine_name}")
        print(f"Data Directory: {self.data_dir}")
        print(f"Session Database: {'Connected' if self.db else 'Not available'}")
        print(f"FileMaker Server API: {fms_status}")
        print(f"\nStarting WebSocket server on {host}:{port}...")
        print(f"Press Ctrl+C to stop\n")

        async with websockets.serve(self.handle_client, host, port):
            await asyncio.Future()  # Run forever


def main():
    parser = argparse.ArgumentParser(
        description='FileMaker Bridge Server for Claude Integration'
    )
    parser.add_argument(
        '--machine-name',
        default=os.uname().nodename,
        help='Name to identify this machine (default: hostname)'
    )
    parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='Host to bind to (default: 0.0.0.0)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=8767,
        help='Port to listen on (default: 8767)'
    )
    parser.add_argument(
        '--data-dir',
        help='Directory for FileMaker data (default: ~/.filemaker-bridge)'
    )
    parser.add_argument(
        '--api-key',
        help='Anthropic API key (or set ANTHROPIC_API_KEY env var)'
    )
    parser.add_argument(
        '--fms-host',
        help='FileMaker Server host (or set FMS_HOST env var)'
    )
    parser.add_argument(
        '--fms-username',
        help='FileMaker Server username (or set FMS_USERNAME env var)'
    )
    parser.add_argument(
        '--fms-password',
        help='FileMaker Server password (or set FMS_PASSWORD env var)'
    )

    args = parser.parse_args()

    # Create and start server
    server = FileMakerBridgeServer(
        machine_name=args.machine_name,
        filemaker_data_dir=args.data_dir,
        api_key=args.api_key,
        fms_host=args.fms_host,
        fms_username=args.fms_username,
        fms_password=args.fms_password
    )

    try:
        asyncio.run(server.start_server(host=args.host, port=args.port))
    except KeyboardInterrupt:
        print("\n\nShutting down FileMaker Bridge Server...")
        sys.exit(0)


if __name__ == '__main__':
    main()
