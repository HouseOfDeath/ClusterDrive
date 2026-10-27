import hashlib
import json
import os
import subprocess
import time
import urllib.request
import urllib.error

API_URL = "http://localhost:30081"
FRONTEND_URL = "http://localhost:30080"

def log(msg):
    print(f"[TEST] {msg}", flush=True)

def test_health():
    log("Checking API health...")
    with urllib.request.urlopen(f"{API_URL}/health", timeout=5) as resp:
        data = json.loads(resp.read().decode())
        assert data["status"] == "ok"
        log(f"API health OK: {data}")

def test_raft_and_nodes():
    log("Checking Raft status and active nodes...")
    with urllib.request.urlopen(f"{API_URL}/api/raft/status", timeout=5) as resp:
        raft = json.loads(resp.read().decode())
        assert raft["quorum_available"] is True
        log(f"Raft quorum available: Leader={raft['leader_id']}, term={raft['nodes'][0]['term']}")
    
    with urllib.request.urlopen(f"{API_URL}/api/nodes", timeout=5) as resp:
        nodes = json.loads(resp.read().decode())
        assert nodes["active_count"] == 3
        log(f"All 3 storage nodes healthy: {[n['id'] for n in nodes['items']]}")

def test_upload_and_download():
    log("Generating 2.5 MB test payload...")
    data = os.urandom(2_500_000)
    expected_hash = hashlib.sha256(data).hexdigest()
    boundary = "----WebKitFormBoundaryClusterDriveTest"
    
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="k8s_e2e_test.dat"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    
    log("Uploading 2.5 MB file to API NodePort 30081...")
    req = urllib.request.Request(f"{API_URL}/api/files", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        upload_resp = json.loads(resp.read().decode())
        file_id = upload_resp["id"]
        log(f"Uploaded successfully! File ID: {file_id}, Chunks: {upload_resp['chunk_count']}")
        assert upload_resp["chunk_count"] == 3
        assert upload_resp["size_bytes"] == 2_500_000

    # Check files list
    with urllib.request.urlopen(f"{API_URL}/api/files", timeout=5) as resp:
        file_list = json.loads(resp.read().decode())
        log(f"Files in catalog: {file_list['count']}")
        matching = next(f for f in file_list["items"] if f["id"] == file_id)
        log(f"File confirmed in catalog: {matching['name']} ({matching['size_bytes']} bytes, {matching['chunk_count']} chunks)")

    # Direct API download
    log("Downloading file directly from API NodePort 30081...")
    with urllib.request.urlopen(f"{API_URL}/api/files/{file_id}/download", timeout=15) as resp:
        downloaded = resp.read()
        downloaded_hash = hashlib.sha256(downloaded).hexdigest()
        assert downloaded_hash == expected_hash
        assert len(downloaded) == 2_500_000
        log("API Download byte-for-byte SHA-256 match verified!")

    # Frontend reverse proxy download
    log("Downloading file through Frontend proxy NodePort 30080...")
    with urllib.request.urlopen(f"{FRONTEND_URL}/api/files/{file_id}/download", timeout=15) as resp:
        proxy_downloaded = resp.read()
        proxy_hash = hashlib.sha256(proxy_downloaded).hexdigest()
        assert proxy_hash == expected_hash
        assert len(proxy_downloaded) == 2_500_000
        log("Frontend Proxy Download byte-for-byte SHA-256 match verified!")

    return file_id, expected_hash

def test_node_failure_and_resilience(file_id, expected_hash):
    log("Testing node resilience: scaling storage-node-02 to 0 replicas...")
    subprocess.run(["kubectl", "scale", "deployment", "storage-node-02", "--replicas=0", "-n", "clusterdrive"], check=True)
    
    log("Waiting for node-02 to report unavailable...")
    for _ in range(20):
        time.sleep(1)
        try:
            with urllib.request.urlopen(f"{API_URL}/api/nodes", timeout=3) as resp:
                nodes = json.loads(resp.read().decode())
                node2 = next(n for n in nodes["items"] if n["id"] == "node-02")
                if node2["status"] == "unavailable":
                    log("Verified: node-02 is accurately reported as unavailable!")
                    break
        except Exception:
            pass

    log("Downloading file with storage-node-02 down (replica failover verification)...")
    with urllib.request.urlopen(f"{API_URL}/api/files/{file_id}/download", timeout=15) as resp:
        downloaded = resp.read()
        assert hashlib.sha256(downloaded).hexdigest() == expected_hash
        log("Failover download succeeded! File was reconstructed from surviving replicas.")

    log("Restoring storage-node-02: scaling back to 1 replica...")
    subprocess.run(["kubectl", "scale", "deployment", "storage-node-02", "--replicas=1", "-n", "clusterdrive"], check=True)
    
    log("Waiting for storage-node-02 to recover...")
    for _ in range(30):
        time.sleep(2)
        try:
            with urllib.request.urlopen(f"{API_URL}/api/nodes", timeout=3) as resp:
                nodes = json.loads(resp.read().decode())
                node2 = next(n for n in nodes["items"] if n["id"] == "node-02")
                if node2["status"] == "healthy":
                    log("Verified: storage-node-02 restored and healthy!")
                    break
        except Exception:
            pass

if __name__ == "__main__":
    log("=== Starting Kubernetes E2E Verification ===")
    test_health()
    test_raft_and_nodes()
    file_id, expected_hash = test_upload_and_download()
    test_node_failure_and_resilience(file_id, expected_hash)
    log("=== All Kubernetes Verification Steps Passed! ===")
