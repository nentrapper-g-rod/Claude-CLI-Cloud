#!/usr/bin/env python3
"""
Simple Settings API Server (Port 8891)
Handles saving init.sh and personalpref.txt files
Also handles conversation sync from bridge servers
"""

import asyncio
import json
from aiohttp import web
from pathlib import Path
import sys

# Import conversation database
sys.path.insert(0, str(Path.home() / '.claude-bridge'))
try:
    from conversation_db import get_db
except ImportError:
    get_db = None

class SettingsAPI:
    def __init__(self):
        self.base_path = Path(__file__).parent
        self.db = get_db() if get_db else None

    async def handle_save_init_script(self, request):
        """Save the init.sh script"""
        try:
            data = await request.json()
            script_content = data.get('script', '')

            script_path = self.base_path / 'init.sh'
            script_path.write_text(script_content)
            script_path.chmod(0o755)

            return web.json_response({'status': 'success'})
        except Exception as e:
            print(f"Error saving init script: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_save_personal_prefs(self, request):
        """Save personal preferences to personalpref.txt"""
        try:
            data = await request.json()
            prefs_content = data.get('personalPreferences', '')

            prefs_path = self.base_path / 'personalpref.txt'
            prefs_path.write_text(prefs_content)

            return web.json_response({'status': 'success'})
        except Exception as e:
            print(f"Error saving personal preferences: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_init_script(self, request):
        """Get the init.sh script"""
        try:
            script_path = self.base_path / 'init.sh'
            if script_path.exists():
                content = script_path.read_text()
                return web.json_response({'script': content})
            else:
                return web.json_response({'script': ''})
        except Exception as e:
            print(f"Error getting init script: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_save_connections(self, request):
        """Save connections configuration"""
        try:
            data = await request.json()
            connections = data.get('connections', [])

            connections_path = self.base_path / 'connections.json'
            connections_path.write_text(json.dumps(connections, indent=2))

            return web.json_response({'status': 'success'})
        except Exception as e:
            print(f"Error saving connections: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_connections(self, request):
        """Get connections configuration"""
        try:
            connections_path = self.base_path / 'connections.json'
            if connections_path.exists():
                content = connections_path.read_text()
                connections = json.loads(content)
                return web.json_response({'connections': connections})
            else:
                return web.json_response({'connections': []})
        except Exception as e:
            print(f"Error getting connections: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_sync_conversation(self, request):
        """Receive conversation data from bridge servers"""
        try:
            if not self.db:
                return web.json_response({'error': 'Database not available'}, status=500)

            data = await request.json()
            session_id = data.get('session_id')
            connection_name = data.get('connection_name')
            messages = data.get('messages', [])
            project = data.get('project')
            cwd = data.get('cwd')

            if not session_id or not connection_name:
                return web.json_response({'error': 'Missing session_id or connection_name'}, status=400)

            # Upsert session
            self.db.upsert_session(
                session_id=session_id,
                connection_name=connection_name,
                project=project,
                cwd=cwd
            )

            # Add messages if provided
            if messages:
                self.db.add_messages(
                    session_id=session_id,
                    connection_name=connection_name,
                    messages=messages,
                    project=project,
                    cwd=cwd
                )

            print(f"Synced conversation: {connection_name} / {session_id} ({len(messages)} messages)")
            return web.json_response({'status': 'success', 'message_count': len(messages)})

        except Exception as e:
            print(f"Error syncing conversation: {e}")
            import traceback
            traceback.print_exc()
            return web.json_response({'error': str(e)}, status=500)

    async def handle_query_session(self, request):
        """Query if a session exists in the central database"""
        try:
            if not self.db:
                return web.json_response({'error': 'Database not available'}, status=500)

            session_id = request.query.get('session_id')
            if not session_id:
                return web.json_response({'error': 'Missing session_id parameter'}, status=400)

            # Get session info
            sessions = self.db.get_sessions(connection_name=None, limit=1000)
            session = next((s for s in sessions if s['session_id'] == session_id), None)

            if not session:
                return web.json_response({
                    'found': False,
                    'session_id': session_id
                })

            # Get message count
            messages = self.db.get_session_messages(session_id, limit=10000)

            return web.json_response({
                'found': True,
                'session_id': session_id,
                'connection_name': session['connection_name'],
                'project': session.get('project'),
                'message_count': len(messages),
                'last_modified': session.get('last_modified')
            })

        except Exception as e:
            print(f"Error querying session: {e}")
            import traceback
            traceback.print_exc()
            return web.json_response({'error': str(e)}, status=500)

    async def handle_query_stats(self, request):
        """Get conversation statistics by connection"""
        try:
            if not self.db:
                return web.json_response({'error': 'Database not available'}, status=500)

            sessions = self.db.get_sessions(connection_name=None, limit=10000)

            # Group by connection_name
            stats = {}
            for session in sessions:
                conn = session['connection_name']
                if conn not in stats:
                    stats[conn] = {'session_count': 0, 'message_count': 0}
                stats[conn]['session_count'] += 1

                # Count messages for this session
                messages = self.db.get_session_messages(session['session_id'], limit=10000)
                stats[conn]['message_count'] += len(messages)

            return web.json_response({'stats': stats})

        except Exception as e:
            print(f"Error getting stats: {e}")
            import traceback
            traceback.print_exc()
            return web.json_response({'error': str(e)}, status=500)

    async def handle_sessions_grouped(self, request):
        """Get sessions grouped by connection and project directory"""
        try:
            if not self.db:
                return web.json_response({'error': 'Database not available'}, status=500)

            sessions = self.db.get_sessions(connection_name=None, limit=10000)

            # Group by connection_name and project
            grouped = {}
            for session in sessions:
                conn = session['connection_name']
                project = session.get('project') or session.get('cwd') or 'Unknown'

                if conn not in grouped:
                    grouped[conn] = {}

                if project not in grouped[conn]:
                    grouped[conn][project] = []

                grouped[conn][project].append({
                    'session_id': session['session_id'],
                    'parent_session_id': session.get('parent_session_id'),
                    'connection_name': conn,
                    'project': project,
                    'cwd': session.get('cwd'),
                    'created_at': session.get('created_at'),
                    'last_modified': session.get('last_modified'),
                    'message_count': session.get('message_count', 0),
                    'project_tags': session.get('project_tags')
                })

            return web.json_response(grouped)

        except Exception as e:
            print(f"Error getting grouped sessions: {e}")
            import traceback
            traceback.print_exc()
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_session_messages(self, request):
        """Get messages for a specific session"""
        try:
            if not self.db:
                return web.json_response({'error': 'Database not available'}, status=500)

            session_id = request.match_info.get('session_id')
            if not session_id:
                return web.json_response({'error': 'Missing session_id'}, status=400)

            messages = self.db.get_session_messages(session_id, limit=10000)
            return web.json_response({'messages': messages})

        except Exception as e:
            print(f"Error getting session messages: {e}")
            import traceback
            traceback.print_exc()
            return web.json_response({'error': str(e)}, status=500)

    def create_app(self):
        """Create and configure the web application"""
        app = web.Application()

        # Add routes
        app.router.add_post('/api/init-script', self.handle_save_init_script)
        app.router.add_get('/api/init-script', self.handle_get_init_script)
        app.router.add_post('/api/personal-prefs', self.handle_save_personal_prefs)
        app.router.add_post('/api/connections', self.handle_save_connections)
        app.router.add_get('/api/connections', self.handle_get_connections)
        app.router.add_post('/api/conversations/sync', self.handle_sync_conversation)
        app.router.add_get('/api/conversations/query', self.handle_query_session)
        app.router.add_get('/api/conversations/stats', self.handle_query_stats)
        app.router.add_get('/api/sessions/grouped', self.handle_sessions_grouped)
        app.router.add_get('/api/conversations/{session_id}', self.handle_get_session_messages)

        # Add CORS middleware
        async def cors_middleware(app, handler):
            async def middleware_handler(request):
                if request.method == 'OPTIONS':
                    response = web.Response()
                else:
                    response = await handler(request)

                response.headers['Access-Control-Allow-Origin'] = '*'
                response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
                response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
                return response
            return middleware_handler

        app.middlewares.append(cors_middleware)

        return app

async def main():
    api = SettingsAPI()
    app = api.create_app()

    runner = web.AppRunner(app)
    await runner.setup()

    # Run on port 8891 (no SSL needed, local only)
    site = web.TCPSite(runner, '0.0.0.0', 8891)
    print("Settings API Server running on http://0.0.0.0:8891")

    await site.start()
    print("Press Ctrl+C to stop")

    await asyncio.Future()  # Run forever

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
