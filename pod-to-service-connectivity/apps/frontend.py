import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen


BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:80")
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pod to Service Connectivity</title>
<style>
body { font: 18px system-ui; max-width: 850px; margin: 60px auto; padding: 24px;
       background: #102032; color: #eaf2fa; }
button { padding: 12px 20px; font: inherit; cursor: pointer; }
pre { padding: 20px; background: #071321; white-space: pre-wrap; overflow-wrap: anywhere; }
</style></head><body>
<h1>Frontend → Backend Service → Backend Pod</h1>
<p>The frontend server calls the backend through its Kubernetes Service name.</p>
<button id="call">Call backend</button>
<pre id="result" aria-live="polite">Click to send a request.</pre>
<script>
document.getElementById('call').onclick = async () => {
  const result = document.getElementById('result');
  result.textContent = 'Calling backend...';
  try {
    const response = await fetch('/api/backend', {cache: 'no-store'});
    result.textContent = JSON.stringify(await response.json(), null, 2);
  } catch (error) { result.textContent = String(error); }
};
</script></body></html>""".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self.respond(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/healthz":
            self.respond(200, b"ok", "text/plain")
        elif self.path == "/api/backend":
            result = {"frontend_pod": socket.gethostname(), "backend_url": BACKEND_URL}
            try:
                with urlopen(BACKEND_URL, timeout=5) as response:
                    result["backend_response"] = json.load(response)
                status = 200
            except (OSError, ValueError) as error:
                result["error"] = str(error)
                status = 502
            self.respond(status, json.dumps(result).encode(), "application/json")
        else:
            self.send_error(404)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "8080"))), Handler).serve_forever()
