# ClusterDrive — Distributed Cloud Storage & Consensus Engine

[![Tests: Backend](https://img.shields.io/badge/backend%20tests-41%2F41%20passing-brightgreen)](#automated-testing)
[![Tests: Frontend](https://img.shields.io/badge/frontend%20tests-10%2F10%20passing-brightgreen)](#frontend-tests)
[![Deployment: Compose](https://img.shields.io/badge/docker%20compose-verified-blue)](#docker-compose-deployment)
[![Deployment: Kubernetes](https://img.shields.io/badge/kubernetes-verified-blue)](#kubernetes-deployment)

ClusterDrive is an educational, production-modeled distributed object-storage platform. It demonstrates how modern distributed systems split, hash, replicate, balance, and reconstruct binary files across independent storage nodes, while coordinating cluster metadata through a 3-node **Raft consensus cluster** and visualizing classic distributed algorithms (**Lamport clocks**, **Ricart–Agrawala mutual exclusion**, and **wait-for graph deadlock recovery**).

The system supports local development, containerized multi-service orchestration with **Docker Compose**, and declarative cloud-native orchestration with **Kubernetes** (deployable locally on Docker Desktop).

---

## Architecture Diagram

```mermaid
flowchart TD
    subgraph Clients["Clients & Presentation"]
        Browser["Web Browser"]
        Dashboard["React + Vite Frontend (Port 5173 / K8s: 30080)"]
    end

    subgraph Gateway["API Gateway Layer"]
        API["FastAPI Cluster Service (Port 8000 / K8s: 30081)"]
        Cache[("Redis Cache (Port 6379)")]
        LocalCatalog[("Local Metadata Catalog (SQLite/JSON Fallback)")]
    end

    subgraph Consensus["Metadata Consensus (Raft Cluster)"]
        M1["Metadata Node 01 (Port 50161)"]
        M2["Metadata Node 02 (Port 50161)"]
        M3["Metadata Node 03 (Port 50161)"]
    end

    subgraph Storage["Distributed Storage Fabric (gRPC)"]
        S1[("Storage Node 01 (Port 50051)<br/>Volume: node-01-data")]
        S2[("Storage Node 02 (Port 50051)<br/>Volume: node-02-data")]
        S3[("Storage Node 03 (Port 50051)<br/>Volume: node-03-data")]
    end

    Browser -->|HTTP| Dashboard
    Dashboard -->|HTTP / JSON REST| API
   API -- "Cache-Aside (TTL 60s)" --> Cache
    API -->|Fallback Read/Write| LocalCatalog

    API -->|gRPC: Propose Metadata Update| M1
    M1 <-->|gRPC: RequestVote & AppendEntries| M2
    M1 <-->|gRPC: RequestVote & AppendEntries| M3

    API -->|gRPC: StoreChunk / RetrieveChunk| S1
    API -->|gRPC: StoreChunk / RetrieveChunk| S2
    API -->|gRPC: StoreChunk / RetrieveChunk| S3

    S1 <-->|gRPC: ReplicateChunk (Anti-Entropy)| S2
    S2 <-->|gRPC: ReplicateChunk (Anti-Entropy)| S3
    S1 <-->|gRPC: ReplicateChunk (Anti-Entropy)| S3
```

---

## Technology Stack

- **Frontend:** React 18, Vite 5, JavaScript (ES2022), custom dark-mode CSS theme, Lucide React icons, and Vitest testing library.
- **API & Backend:** Python 3.13+, FastAPI, Uvicorn, Pydantic v2.
- **Inter-Service Communication:** gRPC and Protocol Buffers (`proto/storage.proto`, `proto/raft.proto`).
- **Distributed Consensus:** 3-node Raft consensus implementation (`RequestVote`, `AppendEntries`, randomized election timeouts, persistent term/log state machine).
- **Caching Layer:** Redis 7 (Alpine), utilizing the cache-aside pattern with TTL expiration, invalidation hooks, and graceful degradation fallback.
- **Containerization:** Docker multi-stage builds (`Dockerfile.backend`, `Dockerfile.frontend`) and Docker Compose.
- **Cluster Orchestration:** Kubernetes (Deployments, 3-replica StatefulSet with headless service, dedicated PersistentVolumeClaims, NodePort services, tcpSocket/httpGet probes).
- **Test Frameworks:** Pytest 9, AnyIO, HTTPX, Vitest, Testing Library.

---

## Folder Structure

```text
ClusterDrive/
├── backend/                      # Python backend and microservices
│   ├── algorithms/               # Distributed algorithms implementations
│   │   ├── deadlock.py           # Wait-for graph & cycle abort victim selection
│   │   ├── lamport.py            # Lamport logical clock
│   │   ├── load_balancer.py      # Round-robin and capacity-weighted placement
│   │   └── ricart_agrawala.py    # Distributed mutual exclusion engine
│   ├── app/                      # FastAPI gateway application
│   │   ├── cache.py              # Redis client with cache-aside and in-memory fallback
│   │   ├── config.py             # Environment configuration parser
│   │   ├── main.py               # Application factory and lifespan manager
│   │   ├── models.py             # Pydantic API response and request models
│   │   ├── replication.py        # Asynchronous replica synchronization worker
│   │   ├── routes.py             # REST API endpoint definitions
│   │   ├── storage_client.py     # gRPC client wrapper for storage nodes
│   │   └── storage_service.py    # File chunking, placement, hashing, reconstruction
│   ├── metadata/                 # Raft metadata cluster peers
│   │   ├── raft_node.py          # Raft state machine, elections, log replication
│   │   └── server.py             # Metadata gRPC peer server entrypoint
│   ├── proto/                    # Compiled Protocol Buffers and gRPC stubs
│   │   ├── raft_pb2.py & grpc    # Raft RPC stubs
│   │   └── storage_pb2.py & grpc # Storage RPC stubs
│   ├── storage/                  # Storage node gRPC server
│   │   └── node.py               # Chunk persistence, retrieval, and disk verification
│   └── tests/                    # Automated pytest test suites (41 tests)
│       ├── test_algorithms.py    # Lamport, Ricart-Agrawala, and Deadlock tests
│       ├── test_api.py           # FastAPI routes, CORS, and health tests
│       ├── test_distributed_storage.py # Chunking, reconstruction, failover tests
│       ├── test_metadata_cache.py# Redis hit/miss/invalidation/outage tests
│       └── test_raft_cluster.py  # Raft election, commit quorum, partition tests
├── frontend/                     # React dashboard application
│   ├── src/
│   │   ├── components/           # UI components (Header, Nav, MetricCards)
│   │   ├── pages/                # 7 Dashboard views (Overview, Files, Nodes, etc.)
│   │   ├── App.jsx               # Main dashboard controller and router
│   │   └── App.test.jsx          # Vitest test suite (10 tests)
│   └── vite.config.js            # Vite build and test configuration
├── k8s/                          # Kubernetes deployment manifests
│   ├── 00-namespace.yaml         # Namespace 'clusterdrive'
│   ├── 01-configmap.yaml         # Non-secret environment configuration
│   ├── 02-pvc.yaml               # Dedicated PVCs for nodes and catalog
│   ├── 03-redis.yaml             # Redis deployment & service
│   ├── 04-storage-nodes.yaml     # 3 Storage Node deployments & services
│   ├── 05-metadata-statefulset.yaml # 3-replica StatefulSet & headless service
│   ├── 06-api.yaml               # FastAPI deployment & NodePort service (30081)
│   └── 07-frontend.yaml          # Nginx frontend deployment & NodePort service (30080)
├── docs/                         # Technical documentation
│   ├── ARCHITECTURE.md           # System design and protocol specification
│   ├── KUBERNETES.md             # Complete Kubernetes deployment guide
│   └── TEST_MATRIX.md            # Comprehensive test matrix and screenshot checklist
├── scratch/                      # Automated verification scripts
│   ├── verify_k8s.py             # Real Kubernetes end-to-end verification script
│   └── check_k8s.py              # Cluster diagnostics script
├── proto/                        # Source Protocol Buffer definitions
│   ├── raft.proto
│   └── storage.proto
├── docker-compose.yml            # Multi-container Compose orchestration (9 services)
├── Dockerfile.backend            # Multi-purpose Python backend container image
├── Dockerfile.frontend           # Multi-stage Nginx React frontend container image
├── requirements.txt              # Python runtime dependencies
└── .env.example                  # Environment configuration template
```

---

## Ten Distributed Systems Syllabus Topics Matrix

Every topic from the syllabus is implemented in modular, tested code and represented visually in the interactive dashboard:

| # | Topic | Exact File & Symbol | How It Works in ClusterDrive |
|---|---|---|---|
| **1** | **gRPC & Protocol Buffers** | `proto/storage.proto`<br>`backend/storage/node.py`<br>`backend/app/storage_client.py` | Binary streaming and unary RPCs handle file chunk placement (`StoreChunk`), retrieval (`RetrieveChunk`), inter-node replication (`ReplicateChunk`), chunk deletion (`DeleteChunk`), and health telemetry (`GetNodeMetrics`). |
| **2** | **Lamport Logical Clocks** | `backend/algorithms/lamport.py`<br>`LamportClock` | Manages monotonically increasing logical timestamps. Increments on internal events (`tick()`), attaches timestamps to outgoing RPCs (`send_event()`), and merges received timestamps via `max(local, received) + 1` (`receive_event()`). |
| **3** | **Distributed Mutual Exclusion** | `backend/algorithms/ricart_agrawala.py`<br>`DistributedMutex` | Full Ricart–Agrawala algorithm: nodes broadcast `REQUEST(timestamp, node_id)` to enter critical sections. Peers grant immediate `REPLY` unless competing with lower timestamp or currently holding the lock; deferred replies are queued and released upon exiting. |
| **4** | **Deadlock Detection & Recovery** | `backend/algorithms/deadlock.py`<br>`WaitforGraph` | Maintains an in-memory Wait-For Graph (WFG) of active transactions and resource locks. Runs Tarjan/DFS cycle detection; upon cycle discovery, it executes deterministic victim selection (youngest transaction / least progress), aborts the victim, releases held resources, and restores acyclic state. |
| **5** | **Load Balancing** | `backend/app/storage_service.py`<br>`_select_storage_nodes()` | Stateful round-robin chunk distributor balances 1 MB slices and their replicas evenly across active storage nodes, actively skipping nodes detected as unhealthy during heartbeat checks. |
| **6** | **Eventual Consistency** | `backend/app/replication.py`<br>`ReplicationManager` | Replicas are tracked across states: `pending`, `synchronized`, `degraded`, and `failed`. An asynchronous anti-entropy background worker processes repair queues. The dashboard features an interactive demo to induce artificial replica lag and observe convergence. |
| **7** | **Redis Caching** | `backend/app/metadata_cache.py`<br>`MetadataCache` | Cache-aside architecture caches file list and chunk catalogs in Redis with a 60-second TTL. Uploads and deletions trigger instant cache invalidation. If Redis suffers an outage, the system logs the incident and transparently falls back to local disk storage without interrupting client requests. |
| **8** | **Raft Consensus** | `backend/metadata/raft_node.py`<br>`RaftNode` | A 3-node consensus cluster (`metadata-01`, `02`, `03`) elects a single leader via randomized election timeouts (5.0s–8.0s) and heartbeats (0.5s). All catalog modifications are proposed to the leader, appended to logs, replicated, and committed only when acknowledged by a majority quorum (2/3 nodes). Persistent state (`term`, `voted_for`, `log.json`) survives node restarts. |
| **9** | **Kubernetes Pod Deployment** | `k8s/*.yaml`<br>`k8s/05-metadata-statefulset.yaml` | Production-modeled declarative manifests deploy the 9 microservices into a dedicated `clusterdrive` namespace using Deployments, a StatefulSet with `volumeClaimTemplates` for stable Raft identities, headless DNS discovery, dedicated PVCs per node, resource limits, and non-blocking `tcpSocket` and `httpGet` probes. |
| **10** | **Distributed File Storage** | `backend/app/storage_service.py`<br>`ClusterStorageService` | Slices uploaded files into 1 MB chunks, computes SHA-256 hashes per chunk and across the whole file, distributes replicas across multiple nodes, and verifies chunk hashes on download. If a primary node is down or a chunk is corrupted, it automatically falls back to surviving replicas to reconstruct the original payload byte-for-byte. |

---

## Setup Instructions for Windows

### Prerequisites
- **Operating System:** Windows 10/11 (x64) with WSL2 enabled.
- **Python:** Python 3.13 or 3.14 installed with `Add Python to PATH` checked.
- **Node.js:** Node.js v18+ (v20+ recommended) and npm.
- **Docker Desktop:** Docker Desktop installed with WSL2 engine and Kubernetes enabled in Settings.

---

## Running Locally (Bare Metal / Virtualenv)

To run without containers for lightweight development:

### 1. Backend Setup
```powershell
# Navigate to project root
cd c:\Users\ADMIN\Documents\ClusterDrive

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Copy environment variables
Copy-Item .env.example .env

# Start 3 background storage nodes (ports 50051, 50052, 50053)
Start-Process python -ArgumentList "-m backend.storage.node --node-id node-01 --port 50051 --storage-dir data/storage/node-01"
Start-Process python -ArgumentList "-m backend.storage.node --node-id node-02 --port 50052 --storage-dir data/storage/node-02"
Start-Process python -ArgumentList "-m backend.storage.node --node-id node-03 --port 50053 --storage-dir data/storage/node-03"

# Start the FastAPI service (port 8000)
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Frontend Setup
```powershell
# In a new PowerShell terminal
cd c:\Users\ADMIN\Documents\ClusterDrive\frontend

# Install dependencies
npm install

# Start Vite dev server (port 5173)
npm run dev
```
Open your browser at `http://localhost:5173`.

---

## Docker Compose Deployment

Docker Compose orchestrates all 9 microservices with isolated container networking and persistent named volumes:

### Start the Stack
```powershell
# Build and start all 9 containers in background
docker compose up --build -d
```

### Inspect Containers & Health Status
```powershell
docker compose ps
```
*Expected: 9 containers reporting `(healthy)`: `api`, `frontend`, `redis`, `storage-node-01..03`, `metadata-01..03`.*

### View Logs
```powershell
# Follow logs for all services
docker compose logs -f

# Follow API service specifically
docker compose logs -f api
```

### Access Services
- **Dashboard UI:** `http://localhost:5173`
- **FastAPI Documentation:** `http://localhost:8000/docs`
- **API Health:** `http://localhost:8000/health`

### Stop the Stack (Preserving Persistent Storage)
```powershell
# Stops containers without deleting persistent chunk/metadata volumes
docker compose stop

# To restart later without rebuilding
docker compose start

# To completely tear down containers while keeping data volumes
docker compose down
```

---

## Kubernetes Deployment

Deploy ClusterDrive to a local Kubernetes cluster (e.g., Docker Desktop Kubernetes or Minikube).

### 1. Verify Kubernetes Context & Nodes
```powershell
kubectl config use-context docker-desktop
kubectl get nodes
```
*Node `docker-desktop` should report `Ready`.*

### 2. Apply Manifests
```powershell
# Apply all manifests in order
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-configmap.yaml
kubectl apply -f k8s/02-pvc.yaml
kubectl apply -f k8s/03-redis.yaml
kubectl apply -f k8s/04-storage-nodes.yaml
kubectl apply -f k8s/05-metadata-statefulset.yaml
kubectl apply -f k8s/06-api.yaml
kubectl apply -f k8s/07-frontend.yaml
```

### 3. Verify Pods, PVCs, and Services
```powershell
# Check pods (should show 9/9 Running)
kubectl get pods -n clusterdrive

# Check PVCs (all 8 claims should show Bound)
kubectl get pvc -n clusterdrive

# Check services and NodePorts
kubectl get svc -n clusterdrive
```

### 4. Access Kubernetes Endpoints
- **Web Dashboard:** `http://localhost:30080` (NodePort `30080 -> 80`)
- **API Health:** `http://localhost:30081/health` (NodePort `30081 -> 8000`)
- **Raft Status:** `http://localhost:30081/api/raft/status`
- **Active Storage Nodes:** `http://localhost:30081/api/nodes`

### 5. Automated End-to-End Cluster Test
Run the automated verification script:
```powershell
python scratch/verify_k8s.py
```
*This uploads a 2.5 MB multi-chunk file, verifies replica synchronization, tests direct and reverse-proxy downloads with SHA-256 matching, scales down `storage-node-02` to simulate node failure, proves fault-tolerant replica failover reconstruction, and restores the node with persistent data intact.*

### 6. Safe Teardown (Without Deleting Persistent Data)
```powershell
# Deletes deployments, pods, and services, preserving PVC storage volumes
kubectl delete -f k8s/07-frontend.yaml
kubectl delete -f k8s/06-api.yaml
kubectl delete -f k8s/05-metadata-statefulset.yaml
kubectl delete -f k8s/04-storage-nodes.yaml
kubectl delete -f k8s/03-redis.yaml
```

---

## Automated Testing

### Backend Unit & Integration Tests
```powershell
.\.venv\Scripts\Activate.ps1
pytest backend/tests -v
```
**Results:** **41 passed in 29.61s** (100% passing rate).

### Frontend Component & Integration Tests
```powershell
npm test --prefix frontend
```
**Results:** **10 passed in 24.65s** (100% passing rate).

### Production Frontend Build Check
```powershell
npm run build --prefix frontend
```
**Results:** Built cleanly in **8.87s** (zero warnings or type errors).

---

## Limitations & Future Improvements

1. **Educational Raft Scope:** The Raft cluster implementation models election terms, heartbeats, log replication, and majority quorum commit gates for metadata operations. It does not implement dynamic cluster membership changes (joint consensus) or log compaction via snapshotting.
2. **Chunk Size & Streaming:** Files are sliced into 1 MB chunks in-memory during upload. For production petabyte-scale engines, chunk upload should stream chunks directly from disk sockets to storage workers using gRPC client-streaming.
3. **Erasure Coding:** ClusterDrive uses $N$-way replication (default: 2 copies per chunk). Integrating Reed-Solomon erasure coding ($K+M$ blocks) would reduce storage overhead while preserving high fault tolerance.
4. **Transport Layer Security (TLS):** Internal gRPC and HTTP communication currently runs over unencrypted internal network channels. Future versions will configure mutual TLS (mTLS) with SPIFFE/SPIRE certificates.

---

## Five-Minute Demonstration Script

Use this step-by-step walkthrough during an evaluation, demo, or viva:

### Minute 1: Introduction & Architecture Overview
- Open the dashboard at `http://localhost:30080` (or `http://localhost:5173`).
- Point out the **Overview** page: explain that the cluster consists of 3 gRPC storage nodes, a 3-node Raft consensus cluster, Redis cache, and FastAPI.
- Highlight the real live telemetry cards: 3 healthy storage nodes, Redis cache hit rate, and zero mock data.

### Minute 2: Multi-Chunk Upload & SHA-256 Hashing
- Navigate to the **File Manager** tab.
- Click **Choose File**, select a 2.5 MB+ file (e.g., an image or test document), and click **Upload**.
- Show the resulting file entry: point out that the file was split into 1 MB chunks and replicated across distinct storage nodes (`node-01`, `node-02`, `node-03`) with a `synchronized` badge.
- Click **Download** to demonstrate instant byte-for-byte reconstruction and integrity verification.

### Minute 3: Raft Consensus & Leader Election
- Navigate to the **Raft Cluster** tab.
- Show the 3 active metadata peers (`metadata-01`, `metadata-02`, `metadata-03`).
- Point out the elected **Leader** badge, current **Term**, commit index, and millisecond heartbeat counters.
- Explain: *"Every file write must be committed by a 2-of-3 majority in Raft before the API records the file as available, guaranteeing metadata consistency."*

### Minute 4: Distributed Algorithms (Deadlock & Lamport Clocks)
- Navigate to the **Distributed Algorithms** tab.
- View the **Lamport Logical Clocks** table showing monotonic timestamps updated on every cluster event.
- Scroll to the **Deadlock Detection & Recovery** panel.
- Click **Run Deadlock Demo**: observe the visualization of an intentionally created circular wait-for cycle, see the algorithm identify the youngest transaction as victim, abort it, release its locks, and restore the acyclic graph.

### Minute 5: Fault Tolerance & Storage Node Failover
- In a terminal, run:
  ```powershell
  kubectl scale deployment storage-node-02 --replicas=0 -n clusterdrive
  ```
  *(Or in Compose: `docker compose stop storage-node-02`)*
- Refresh the **Storage Nodes** page: observe `node-02` instantly turn red (`unavailable`).
- Return to **File Manager** and click **Download** on the file uploaded in Minute 2.
- Point out: *"Even though `node-02` is completely dead, the download completes seamlessly because ClusterDrive's load balancer automatically falls back to surviving chunk replicas on `node-01` and `node-03`."*
- Restore the node: `kubectl scale deployment storage-node-02 --replicas=1 -n clusterdrive` and show it return to healthy status with all persistent volume data intact.

