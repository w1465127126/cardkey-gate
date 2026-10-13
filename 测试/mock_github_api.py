import base64,json,os,sys
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
HERE=os.path.dirname(os.path.abspath(__file__))
DB=os.path.join(HERE,"gh_db.json")
STATE={"sha":"init000"}
if not os.path.exists(DB):
    open(DB,"w").write(json.dumps({"version":1,"updated":"x","apps":{}}))
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        text=open(DB,encoding="utf-8").read()
        body=json.dumps({"content":base64.b64encode(text.encode()).decode(),"sha":STATE["sha"]}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_PUT(self):
        n=int(self.headers.get("Content-Length",0)); raw=self.rfile.read(n)
        p=json.loads(raw.decode())
        open(DB,"w",encoding="utf-8").write(base64.b64decode(p["content"]).decode())
        STATE["sha"]=os.urandom(4).hex()
        out=json.dumps({"content":{"sha":STATE["sha"]}}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(out))); self.end_headers(); self.wfile.write(out)
    def log_message(self,*a): pass
print("READY",flush=True)
ThreadingHTTPServer(("127.0.0.1",8901),H).serve_forever()
