#!/usr/bin/env python
"""HTTP server with forced UTF-8 encoding for all text responses."""
import http.server
import os
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18765
DIRECTORY = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()

class UTF8HTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        
        ctype = self.guess_type(path)
        ext = os.path.splitext(path)[1].lower()
        
        text_types = {
            '.md': 'text/markdown; charset=utf-8',
            '.txt': 'text/plain; charset=utf-8',
            '.json': 'application/json; charset=utf-8',
            '.csv': 'text/csv; charset=utf-8',
            '.log': 'text/plain; charset=utf-8',
            '.py': 'text/x-python; charset=utf-8',
            '.js': 'text/javascript; charset=utf-8',
            '.css': 'text/css; charset=utf-8',
            '.html': 'text/html; charset=utf-8',
            '.htm': 'text/html; charset=utf-8',
            '.xml': 'text/xml; charset=utf-8',
            '.yaml': 'text/vnd.yaml; charset=utf-8',
            '.yml': 'text/vnd.yaml; charset=utf-8',
            '.toml': 'text/plain; charset=utf-8',
            '.ini': 'text/plain; charset=utf-8',
            '.cfg': 'text/plain; charset=utf-8',
            '.conf': 'text/plain; charset=utf-8',
        }
        if ext in text_types:
            ctype = text_types[ext]
        elif ctype and ctype.startswith('text/'):
            ctype = ctype.split(';')[0] + '; charset=utf-8'
        
        try:
            f = open(path, 'rb')
        except OSError:
            return super().send_head()
        
        try:
            fs = os.fstat(f.fileno())
            self.send_response(200)
            self.send_header("Content-type", ctype)
            self.send_header("Content-Length", str(fs[6]))
            self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            return f
        except:
            f.close()
            raise

if __name__ == '__main__':
    print(f"Starting UTF-8 HTTP server on port {PORT}")
    print(f"Serving directory: {DIRECTORY}")
    server = http.server.HTTPServer(('0.0.0.0', PORT), UTF8HTTPRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
