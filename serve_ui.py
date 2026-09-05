import http.server
import socketserver
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PORT = 8000

handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(*args, directory=str(BASE_DIR), **kwargs)

with socketserver.TCPServer(("127.0.0.1", PORT), handler) as httpd:
    print(f"Servidor ativo em http://127.0.0.1:{PORT}/index.html")
    print("Para parar, pressiona Ctrl+C no terminal.")
    httpd.serve_forever()
