# ClusterDrive Local Kubernetes Deployment Guide

This guide documents how to deploy ClusterDrive on a local Kubernetes cluster (such as Docker Desktop Kubernetes, Minikube, or kind).

The deployment uses the `clusterdrive` namespace, ConfigMaps for non-secret configuration, PersistentVolumeClaims for durable storage, a StatefulSet for the Raft metadata cluster, separate storage-node workloads with dedicated volumes, and NodePort/LoadBalancer services for access from your local workstation.

---

## Architecture Overview

```text
                                  Browser
                                     │
                     ┌───────────────┴───────────────┐
                     │                               │
             :30080 (NodePort)               :30081 (NodePort)
                     ▼                               ▼
            ┌─────────────────┐             ┌─────────────────┐
            │    Frontend     │──reverse───▶│       API       │
            │   Deployment    │  proxy      │   Deployment    │
            └─────────────────┘             └────────┬────────┘
                                                     │
             ┌───────────────────────┬───────────────┴───────────────┐
             ▼                       ▼                               ▼
    ┌─────────────────┐    ┌────────────────────┐          ┌───────────────────┐
    │      Redis      │    │    Storage Nodes   │          │  Metadata Cluster │
    │   Deployment    │    │  (Deployments 1-3) │          │    StatefulSet    │
    │   + redis-pvc   │    │  + separate pvcs   │          │  (metadata-01..3) │
    └─────────────────┘    └────────────────────┘          │  + metadata-pvcs  │
                                                           └───────────────────┘
```

- **Namespace**: `clusterdrive` isolates all application workloads.
- **ConfigMap**: `clusterdrive-config` supplies environment variables without hardcoded secrets.
- **Redis**: Caching service with AOF persistence mounted on `redis-data-pvc`.
- **Storage Nodes**: Three independent workloads (`storage-node-01`, `storage-node-02`, `storage-node-03`), each backed by its own dedicated PersistentVolumeClaim.
- **Metadata Cluster**: An educational 3-peer Raft consensus cluster deployed as a `StatefulSet` with `volumeClaimTemplates` (`metadata-data`), ensuring each replica maintains its own persistent term, log, vote, and commit state file without sharing storage.
- **API**: FastAPI application connected to Redis, gRPC storage nodes, and the Raft consensus leader. Persists catalog metadata on `api-catalog-pvc`.
- **Background Worker**: Asynchronous replica synchronization runs via the API service's internal background thread pool (`ThreadPoolExecutor`), maintaining non-blocking client uploads while converging replicas across nodes.
- **Frontend**: React + Vite dashboard served via Nginx, reverse-proxying `/api/`, `/health`, and `/docs` to the API.

---

## 1. Select the Kubernetes Context

Ensure your `kubectl` is pointed at your local Docker Desktop Kubernetes cluster:

```powershell
# List available contexts
kubectl config get-contexts

# Switch to the Docker Desktop context
kubectl config use-context docker-desktop
```

---

## 2. Check Node Readiness

Verify that the local Kubernetes node is running and reports `Ready`:

```powershell
kubectl get nodes
```

Expected output:
```text
NAME             STATUS   ROLES           AGE   VERSION
docker-desktop   Ready    control-plane   ...   v1.36.x
```

---

## 3. Build Container Images

Docker Desktop shares its local image cache with the built-in Kubernetes cluster. Build the backend and frontend images once:

```powershell
# Build both images locally
docker compose build
```

Verify that the built images exist:
```powershell
docker images | Select-String "clusterdive"
```

Expected output:
```text
clusterdive-backend    local    ...
clusterdive-frontend   local    ...
```

---

## 4. Apply the Kubernetes Manifests

Apply all manifests from the `k8s/` directory:

```powershell
kubectl apply -f k8s/
```

This creates:
1. `Namespace/clusterdrive`
2. `ConfigMap/clusterdrive-config`
3. `PersistentVolumeClaim`s for Redis, API catalog, and each storage node
4. `Deployment/redis` and `Service/redis`
5. `Deployment/storage-node-01..03` and `Service/storage-node-01..03`
6. `StatefulSet/metadata` and `Service/metadata-hs` (headless)
7. `Deployment/api` and `Service/api` (NodePort 30081)
8. `Deployment/frontend` and `Service/frontend` (NodePort 30080)

---

## 5. Check Pods, Deployments, Services, Events, and Logs

### Check Pod Status
```powershell
kubectl get pods -n clusterdrive -o wide
```

Expected output (all pods `Running` and `Ready`):
```text
NAME                               READY   STATUS    RESTARTS   AGE
api-...                            1/1     Running   0          ...
frontend-...                       1/1     Running   0          ...
metadata-0                         1/1     Running   0          ...
metadata-1                         1/1     Running   0          ...
metadata-2                         1/1     Running   0          ...
redis-...                          1/1     Running   0          ...
storage-node-01-...                1/1     Running   0          ...
storage-node-02-...                1/1     Running   0          ...
storage-node-03-...                1/1     Running   0          ...
```

### Check Deployments & StatefulSets
```powershell
kubectl get deployments,statefulsets -n clusterdrive
```

### Check Persistent Volume Claims
```powershell
kubectl get pvc -n clusterdrive
```

All claims should show `STATUS: Bound`.

### Check Services & NodePorts
```powershell
kubectl get svc -n clusterdrive
```

### Inspect Recent Cluster Events
```powershell
kubectl get events -n clusterdrive --sort-by='.metadata.creationTimestamp'
```

### Inspect Workload Logs
```powershell
# API logs
kubectl logs -n clusterdrive -l app.kubernetes.io/name=api --tail=50 -f

# Raft metadata node logs
kubectl logs -n clusterdrive metadata-0 --tail=50 -f

# Storage node logs
kubectl logs -n clusterdrive -l app.kubernetes.io/name=storage-node-01 --tail=50 -f
```

---

## 6. Access the Dashboard and API

The services expose stable NodePorts on your local machine:

- **Frontend Dashboard**: [http://localhost:30080/](http://localhost:30080/)
- **API Documentation (Swagger UI)**: [http://localhost:30081/docs](http://localhost:30081/docs)
- **API Health Check**: [http://localhost:30081/health](http://localhost:30081/health)
- **Raft Status Endpoint**: [http://localhost:30081/api/raft/status](http://localhost:30081/api/raft/status)
- **Storage Nodes Status**: [http://localhost:30081/api/nodes](http://localhost:30081/api/nodes)

Alternatively, you can use `kubectl port-forward`:
```powershell
# Forward API to port 8001
kubectl port-forward svc/api -n clusterdrive 8001:8000

# Forward Frontend to port 5174
kubectl port-forward svc/frontend -n clusterdrive 5174:80
```

---

## 7. Test Upload, Download, Replica Synchronization, and Node Failure

### A. Health and Cluster Verification
```powershell
# Verify API Health
Invoke-RestMethod http://localhost:30081/health

# Verify Raft consensus leader and majority quorum
Invoke-RestMethod http://localhost:30081/api/raft/status

# Verify all 3 storage nodes are healthy
Invoke-RestMethod http://localhost:30081/api/nodes
```

### B. File Upload and Reconstruction
Upload a file through the dashboard at [http://localhost:30080/](http://localhost:30080/) or via PowerShell:

```powershell
$filePath = "test_k8s.bin"
[System.IO.File]::WriteAllBytes($filePath, (1..1048576 | ForEach-Object { [byte]($_ % 256) }))
$shaBefore = (Get-FileHash $filePath -Algorithm SHA256).Hash

# Upload file
$form = @{ file = Get-Item $filePath }
$uploaded = Invoke-RestMethod -Uri "http://localhost:30081/api/files" -Method Post -Form $form
$fileId = $uploaded.id
Write-Host "Uploaded file ID: $fileId"

# Download and verify SHA-256 match
Invoke-WebRequest -Uri "http://localhost:30081/api/files/$fileId/download" -OutFile "downloaded_k8s.bin"
$shaAfter = (Get-FileHash "downloaded_k8s.bin" -Algorithm SHA256).Hash

if ($shaBefore -eq $shaAfter) {
    Write-Host "Reconstruction test PASSED: Checksums match!"
} else {
    Write-Error "Checksum mismatch!"
}
```

### C. Check Replica Synchronization
```powershell
Invoke-RestMethod http://localhost:30081/api/replication/status
```

Confirm that `synchronized` increments and `pending` reaches `0`.

### D. Simulate Storage Node Failure & Replica Failover
Scale `storage-node-02` down to `0` replicas:

```powershell
kubectl scale deployment storage-node-02 --replicas=0 -n clusterdrive
```

1. Check node status:
   ```powershell
   Invoke-RestMethod http://localhost:30081/api/nodes
   ```
   `node-02` will report `unavailable`, with active count `2/3`.
2. Download the file again:
   ```powershell
   Invoke-WebRequest -Uri "http://localhost:30081/api/files/$fileId/download" -OutFile "failover_k8s.bin"
   (Get-FileHash "failover_k8s.bin" -Algorithm SHA256).Hash -eq $shaBefore
   ```
   The download succeeds via replica fallback on surviving healthy nodes (`node-01` and `node-03`).
3. Recover the node:
   ```powershell
   kubectl scale deployment storage-node-02 --replicas=1 -n clusterdrive
   ```
   Once the pod is ready, `node-02` rejoins the cluster as `healthy` with all its existing chunk data preserved.

---

## 8. Safe Cleanup (Preserves Persistent Data)

### Stop Workloads Without Deleting Data
To tear down the pods and services while **preserving all uploaded files, metadata, and Redis state**:

```powershell
# Delete deployments, statefulsets, services, and configmap (keeps PVCs)
kubectl delete -f k8s/07-frontend.yaml
kubectl delete -f k8s/06-api.yaml
kubectl delete -f k8s/05-metadata-statefulset.yaml
kubectl delete -f k8s/04-storage-nodes.yaml
kubectl delete -f k8s/03-redis.yaml
kubectl delete -f k8s/01-configmap.yaml
```

Do NOT delete the PVCs (`02-pvc.yaml` and `metadata-data-*`). When you re-apply the manifests later with `kubectl apply -f k8s/`, the workloads reattach to their existing volumes and resume with all data intact.

### Complete Cleanup (Deletes All Data)
> [!CAUTION]
> The following command permanently deletes all persistent volumes, file chunks, and metadata:
> ```powershell
> kubectl delete namespace clusterdrive
> ```

