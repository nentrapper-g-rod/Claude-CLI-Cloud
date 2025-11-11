#!/usr/bin/env python3
"""
Conversation API Server (Port 8889)
Handles conversation sync and history API endpoints
"""

import asyncio
import json
from aiohttp import web
from pathlib import Path
import sys

# Import the conversation database
try:
    from conversation_db import get_db
except ImportError:
    # Try relative import
    import importlib.util
    spec = importlib.util.spec_from_file_location("conversation_db",
                                                  Path(__file__).parent / "conversation-db.py")
    conversation_db = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conversation_db)
    get_db = conversation_db.get_db

class ConversationAPI:
    def __init__(self):
        self.db = get_db()

    async def handle_sync_conversation(self, request):
        """Receive conversation data from bridge servers"""
        try:
            data = await request.json()

            session_id = data.get('session_id')
            connection_name = data.get('connection_name')
            messages = data.get('messages', [])
            project = data.get('project')
            cwd = data.get('cwd')
            parent_session_id = data.get('parent_session_id')

            if not session_id or not connection_name:
                return web.json_response({'error': 'Missing session_id or connection_name'}, status=400)

            # Upsert session
            self.db.upsert_session(
                session_id=session_id,
                connection_name=connection_name,
                parent_session_id=parent_session_id,
                custom_title=data.get('custom_title'),
                project=project,
                cwd=cwd,
                message_count=len(messages)
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

            return web.json_response({'status': 'success', 'message_count': len(messages)})

        except Exception as e:
            print(f"Error syncing conversation: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_conversations(self, request):
        """Get list of conversations/sessions"""
        try:
            connection_name = request.query.get('connection')
            limit = int(request.query.get('limit', 100))

            sessions = self.db.get_sessions(connection_name=connection_name, limit=limit)

            return web.json_response({'sessions': sessions})

        except Exception as e:
            print(f"Error getting conversations: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_conversation(self, request):
        """Get full conversation/session details"""
        try:
            session_id = request.match_info['session_id']
            limit = int(request.query.get('limit', 1000))

            messages = self.db.get_session_messages(session_id=session_id, limit=limit)

            return web.json_response({'session_id': session_id, 'messages': messages})

        except Exception as e:
            print(f"Error getting conversation: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_search_conversations(self, request):
        """Search conversations by content"""
        try:
            query = request.query.get('q')
            if not query:
                return web.json_response({'error': 'Missing query parameter'}, status=400)

            connection_name = request.query.get('connection')
            session_id = request.query.get('session_id')
            limit = int(request.query.get('limit', 100))

            results = self.db.search_messages(
                query=query,
                connection_name=connection_name,
                session_id=session_id,
                limit=limit
            )

            return web.json_response({'results': results, 'count': len(results)})

        except Exception as e:
            print(f"Error searching conversations: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_connections(self, request):
        """Get list of all connection names"""
        try:
            connections = self.db.get_connections()
            return web.json_response({'connections': connections})

        except Exception as e:
            print(f"Error getting connections: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_session_thread(self, request):
        """Get the parent chain for a session"""
        try:
            session_id = request.match_info['session_id']
            thread = self.db.get_session_thread(session_id)
            return web.json_response({'session_id': session_id, 'thread': thread})

        except Exception as e:
            print(f"Error getting session thread: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_session_children(self, request):
        """Get direct children of a session"""
        try:
            session_id = request.match_info['session_id']
            children = self.db.get_session_children(session_id)
            return web.json_response({'session_id': session_id, 'children': children})

        except Exception as e:
            print(f"Error getting session children: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_session_tree(self, request):
        """Get the complete tree for a session (parent chain + all descendants)"""
        try:
            session_id = request.match_info['session_id']
            tree = self.db.get_session_tree(session_id)
            return web.json_response({'session_id': session_id, 'tree': tree})

        except Exception as e:
            print(f"Error getting session tree: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_root_sessions(self, request):
        """Get only root sessions (sessions with no parent)"""
        try:
            connection_name = request.query.get('connection')
            limit = int(request.query.get('limit', 100))

            sessions = self.db.get_root_sessions(connection_name=connection_name, limit=limit)
            return web.json_response({'sessions': sessions})

        except Exception as e:
            print(f"Error getting root sessions: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_favorites(self, request):
        """Get favorite/pinned sessions"""
        try:
            connection_name = request.query.get('connection')
            limit = int(request.query.get('limit', 100))

            sessions = self.db.get_favorite_sessions(connection_name=connection_name, limit=limit)
            return web.json_response({'sessions': sessions})

        except Exception as e:
            print(f"Error getting favorite sessions: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_toggle_favorite(self, request):
        """Toggle favorite status of a session"""
        try:
            session_id = request.match_info['session_id']
            new_status = self.db.toggle_favorite(session_id)
            return web.json_response({'session_id': session_id, 'is_favorite': new_status})

        except Exception as e:
            print(f"Error toggling favorite: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_init_script(self, request):
        """Get the init.sh script"""
        try:
            script_path = Path(__file__).parent / 'init.sh'
            if script_path.exists():
                content = script_path.read_text()
                return web.json_response({'script': content})
            else:
                return web.json_response({'script': ''})
        except Exception as e:
            print(f"Error getting init script: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_save_init_script(self, request):
        """Save the init.sh script to web root (served by port 8888)"""
        try:
            data = await request.json()
            script_content = data.get('script', '')

            # Save to web root so it's accessible via http://host:8888/init.sh
            script_path = Path(__file__).parent / 'init.sh'
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

            # Save to file that's served by HTTP server on port 8888
            prefs_path = Path(__file__).parent / 'personalpref.txt'
            prefs_path.write_text(prefs_content)

            return web.json_response({'status': 'success'})
        except Exception as e:
            print(f"Error saving personal preferences: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_options(self, request):
        """Handle CORS preflight"""
        return web.Response(status=200)

    def create_app(self):
        """Create and configure the web application"""
        app = web.Application()

        # Add routes
        app.router.add_post('/api/conversations/sync', self.handle_sync_conversation)
        app.router.add_get('/api/conversations', self.handle_get_conversations)
        app.router.add_get('/api/conversations/roots', self.handle_get_root_sessions)
        app.router.add_get('/api/conversations/favorites', self.handle_get_favorites)
        app.router.add_get('/api/conversations/{session_id}', self.handle_get_conversation)
        app.router.add_post('/api/conversations/{session_id}/favorite', self.handle_toggle_favorite)
        app.router.add_get('/api/conversations/{session_id}/thread', self.handle_get_session_thread)
        app.router.add_get('/api/conversations/{session_id}/children', self.handle_get_session_children)
        app.router.add_get('/api/conversations/{session_id}/tree', self.handle_get_session_tree)
        app.router.add_get('/api/conversations/search', self.handle_search_conversations)
        app.router.add_get('/api/connections/list', self.handle_get_connections)
        app.router.add_get('/api/init-script', self.handle_get_init_script)
        app.router.add_post('/api/init-script', self.handle_save_init_script)
        app.router.add_post('/api/personal-prefs', self.handle_save_personal_prefs)

        # Add CORS preflight handlers
        app.router.add_options('/api/conversations/sync', self.handle_options)
        app.router.add_options('/api/conversations', self.handle_options)
        app.router.add_options('/api/conversations/roots', self.handle_options)
        app.router.add_options('/api/conversations/favorites', self.handle_options)
        app.router.add_options('/api/conversations/{session_id}', self.handle_options)
        app.router.add_options('/api/conversations/{session_id}/favorite', self.handle_options)
        app.router.add_options('/api/conversations/{session_id}/thread', self.handle_options)
        app.router.add_options('/api/conversations/{session_id}/children', self.handle_options)
        app.router.add_options('/api/conversations/{session_id}/tree', self.handle_options)
        app.router.add_options('/api/conversations/search', self.handle_options)
        app.router.add_options('/api/connections/list', self.handle_options)
        app.router.add_options('/api/init-script', self.handle_options)
        app.router.add_options('/api/personal-prefs', self.handle_options)

        # Add CORS middleware
        async def cors_middleware(app, handler):
            async def middleware_handler(request):
                if request.method == 'OPTIONS':
                    response = web.Response()
                else:
                    response = await handler(request)

                response.headers['Access-Control-Allow-Origin'] = '*'
                response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
                response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
                return response
            return middleware_handler

        app.middlewares.append(cors_middleware)

        return app

async def main():
    import ssl

    api = ConversationAPI()
    app = api.create_app()

    runner = web.AppRunner(app)
    await runner.setup()

    # Set up SSL context
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    cert_path = Path.home() / '.claude-bridge' / 'server-cert.pem'
    key_path = Path.home() / '.claude-bridge' / 'server-key.pem'

    if cert_path.exists() and key_path.exists():
        ssl_context.load_cert_chain(cert_path, key_path)
        site = web.TCPSite(runner, '0.0.0.0', 8889, ssl_context=ssl_context)
        print("Conversation API Server running on https://0.0.0.0:8889")
    else:
        site = web.TCPSite(runner, '0.0.0.0', 8889)
        print("Conversation API Server running on http://0.0.0.0:8889 (SSL certs not found)")

    await site.start()
    print("Press Ctrl+C to stop")

    await asyncio.Future()  # Run forever

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
