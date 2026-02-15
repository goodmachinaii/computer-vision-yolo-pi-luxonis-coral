from __future__ import annotations
import sqlite3
import threading
from pathlib import Path


def create_app(db_path: Path, state: dict):
    from flask import Flask, jsonify, request, send_from_directory

    app = Flask(__name__, static_folder=str((Path(__file__).resolve().parent.parent / 'front').resolve()))

    def q(sql: str, params=()):
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @app.get('/status')
    def status():
        return jsonify({
            'mode': state.get('mode', 'unknown'),
            'fps': round(float(state.get('fps', 0.0)), 2),
            'infer_ms': round(float(state.get('infer_ms', 0.0)), 2),
            'running': bool(state.get('running', True)),
        })

    @app.get('/detections')
    def detections_latest():
        rows = q(
            """
            SELECT timestamp, mode, infer_ms, label, confidence, bbox_x, bbox_y, bbox_w, bbox_h, depth_cm
            FROM detections
            ORDER BY id DESC LIMIT 50
            """
        )
        return jsonify({'objects': rows})

    @app.get('/detections/history')
    def detections_history():
        minutes = int(request.args.get('minutes', '60'))
        rows = q(
            """
            SELECT timestamp, mode, infer_ms, label, confidence, depth_cm
            FROM detections
            WHERE timestamp >= datetime('now', ?)
            ORDER BY id DESC
            LIMIT 500
            """,
            (f'-{minutes} minutes',),
        )
        return jsonify(rows)

    @app.get('/detections/stats')
    def detections_stats():
        hours = int(request.args.get('hours', '24'))
        rows = q(
            """
            SELECT label, COUNT(*) as n
            FROM detections
            WHERE timestamp >= datetime('now', ?)
            GROUP BY label
            ORDER BY n DESC
            """,
            (f'-{hours} hours',),
        )
        return jsonify({'hours': hours, 'counts': rows})

    @app.get('/')
    def root():
        return send_from_directory(app.static_folder, 'index.html')

    @app.get('/front/<path:name>')
    def front_files(name):
        return send_from_directory(app.static_folder, name)

    return app


class ApiServer:
    def __init__(self, db_path: Path, state: dict, host='0.0.0.0', port=5000):
        self.db_path = db_path
        self.state = state
        self.host = host
        self.port = int(port)
        self.thread = None
        self.server = None

    def _query(self, sql: str, params=()):
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def _start_stdlib_fallback(self):
        import json
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import urlparse, parse_qs

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, obj, code=200, content_type='application/json'):
                data = json.dumps(obj).encode('utf-8') if content_type == 'application/json' else obj
                self.send_response(code)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                p = urlparse(self.path)
                if p.path == '/status':
                    return self._send({
                        'mode': outer.state.get('mode', 'unknown'),
                        'fps': round(float(outer.state.get('fps', 0.0)), 2),
                        'infer_ms': round(float(outer.state.get('infer_ms', 0.0)), 2),
                        'running': bool(outer.state.get('running', True)),
                    })
                if p.path == '/detections':
                    rows = outer._query("SELECT timestamp, mode, infer_ms, label, confidence, bbox_x, bbox_y, bbox_w, bbox_h, depth_cm FROM detections ORDER BY id DESC LIMIT 50")
                    return self._send({'objects': rows})
                if p.path == '/detections/history':
                    qs = parse_qs(p.query)
                    minutes = int((qs.get('minutes') or ['60'])[0])
                    rows = outer._query(
                        "SELECT timestamp, mode, infer_ms, label, confidence, depth_cm FROM detections WHERE timestamp >= datetime('now', ?) ORDER BY id DESC LIMIT 500",
                        (f'-{minutes} minutes',),
                    )
                    return self._send(rows)
                if p.path == '/detections/stats':
                    qs = parse_qs(p.query)
                    hours = int((qs.get('hours') or ['24'])[0])
                    rows = outer._query("SELECT label, COUNT(*) as n FROM detections WHERE timestamp >= datetime('now', ?) GROUP BY label ORDER BY n DESC", (f'-{hours} hours',))
                    return self._send({'hours': hours, 'counts': rows})
                if p.path in ('/', '/front/index.html'):
                    index = (Path(__file__).resolve().parent.parent / 'front' / 'index.html')
                    if index.exists():
                        return self._send(index.read_bytes(), content_type='text/html; charset=utf-8')
                self._send({'error': 'not found'}, code=404)

            def log_message(self, format, *args):
                return

        self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return True, 'stdlib-http'

    def start(self):
        try:
            from werkzeug.serving import make_server
            app = create_app(self.db_path, self.state)
            self.server = make_server(self.host, self.port, app)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            return True, 'flask'
        except Exception:
            return self._start_stdlib_fallback()

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
