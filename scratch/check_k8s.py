import base64
import tempfile
import ssl
import urllib.request
import json
import os
import re

with open(r'C:\Users\ADMIN\.kube\config', 'r') as f:
    text = f.read()

server_m = re.search(r'server:\s*(https://[^\r\n]+)', text)
server = server_m.group(1).strip()

ca_m = re.search(r'certificate-authority-data:\s*([A-Za-z0-9+/=]+)', text)
ca_data = base64.b64decode(ca_m.group(1).strip())

cert_m = re.search(r'client-certificate-data:\s*([A-Za-z0-9+/=]+)', text)
cert_data = base64.b64decode(cert_m.group(1).strip())

key_m = re.search(r'client-key-data:\s*([A-Za-z0-9+/=]+)', text)
key_data = base64.b64decode(key_m.group(1).strip())

with tempfile.NamedTemporaryFile(delete=False, suffix='.crt') as f_cert, \
     tempfile.NamedTemporaryFile(delete=False, suffix='.key') as f_key, \
     tempfile.NamedTemporaryFile(delete=False, suffix='.ca') as f_ca:
    f_cert.write(cert_data)
    f_cert.flush()
    f_key.write(key_data)
    f_key.flush()
    f_ca.write(ca_data)
    f_ca.flush()
    cert_file = f_cert.name
    key_file = f_key.name
    ca_file = f_ca.name

try:
    ctx = ssl.create_default_context(cafile=ca_file)
    ctx.load_cert_chain(certfile=cert_file, keyfile=key_file)
    
    url = f"{server}/api/v1/namespaces/clusterdrive/pods"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        data = json.loads(resp.read().decode())
        items = data.get('items', [])
        print(f"Total pods in clusterdrive: {len(items)}")
        for item in items:
            name = item['metadata']['name']
            phase = item['status'].get('phase', 'Unknown')
            conditions = {c['type']: c['status'] for c in item['status'].get('conditions', [])}
            container_statuses = item['status'].get('containerStatuses', [])
            ready = all(cs.get('ready', False) for cs in container_statuses) if container_statuses else False
            restarts = sum(cs.get('restartCount', 0) for cs in container_statuses)
            print(f"- {name}: Phase={phase}, Ready={ready}, Restarts={restarts}")
finally:
    for path in [cert_file, key_file, ca_file]:
        try:
            os.remove(path)
        except OSError:
            pass
