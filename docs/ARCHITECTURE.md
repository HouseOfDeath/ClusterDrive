# ClusterDrive High-Level Architecture

## What the system does

ClusterDrive accepts a file through a web dashboard, divides it into chunks,
stores chunks on separate storage nodes, and keeps metadata describing how to
find those chunks. Copies of chunks provide redundancy. When a user downloads
the file, the system reads its chunks, checks their SHA-256 checksums, and
reconstructs the original bytes.

The services run locally first. Docker Compose makes it possible to start the
services together on a student computer; Kubernetes is a later deployment
target, not a prerequisite for the first working version.

## Planned services

```text
Browser
  | HTTP (dashboard requests)
  v
React + Vite frontend
  | HTTP/JSON
  v
FastAPI API service
  +-- gRPC client --> Metadata node 1 (Raft; persistent local state)
  +-- gRPC client --> Metadata node 2 (Raft; persistent local state)
  +-- gRPC client --> Metadata node 3 (Raft; persistent local state)
  +-- local JSON API catalog (updated only after Raft commit)
  +-- three logical algorithm-demo nodes (Lamport clocks + Ricart–Agrawala; in-process)
  +-- gRPC + Protocol Buffers --> Storage node 1 (its own data directory)
  +-- gRPC + Protocol Buffers --> Storage node 2 (its own data directory)
  +-- gRPC + Protocol Buffers --> Storage node 3 (its own data directory)
  +-- Redis cache (best-effort, local catalog is fallback)

```

## Implemented API and distributed storage

FastAPI provides these endpoints:

- `GET /health` reports whether the API process is responding.
- `GET /api/dashboard` reports file totals, node health, stored bytes, and
  implementation status for educational features.
- `GET /api/files` lists file records.
- `POST /api/files` accepts a multipart file upload, chunks it, checksums it,
  and writes replicas to storage nodes over gRPC.
- `GET /api/files/{file_id}/download` retrieves, checksum-verifies, and
  reconstructs a file from replicas.
- `DELETE /api/files/{file_id}` removes chunks from all recorded replicas
  before deleting the file record.
- `GET /api/nodes` actively checks configured nodes over gRPC.
- `GET /api/logs` lists actual upload, download, and delete events.
- `GET /api/algorithms/status` reports logical metadata-node clocks and recent
  Ricart–Agrawala permission messages.
- `POST /api/algorithms/deadlock-demo` builds a controlled wait-for cycle,
  selects and aborts a victim, releases its locks, and returns before/after
  graph state.
- `GET /api/replication/status` reports file/chunk replica versions and
  pending, synchronized, failed, or degraded state.
- `POST /api/replication/demo` creates a real primary chunk and deliberately
  leaves its second copy pending; `POST /api/replication/demo/converge` copies
  and verifies that replica.
- `GET /api/metrics` reports Redis cache counters, node request counts, and
  round-robin placement distribution.
- `GET /api/raft/status` queries each configured metadata process over gRPC for
  role, term, leader, heartbeat age, log indexes, and recent entries.

The React frontend fetches these endpoints through one API client. It displays
API loading and error states and does not substitute example records when a
request fails. If the API has no healthy storage nodes, its actual empty file
list and node health are shown. Local file selection previews a file until the
user explicitly uploads it.

### gRPC storage protocol

`backend/storage/proto/storage.proto` defines `StorageService` and its
`UploadChunk`, `DownloadChunk`, `DeleteChunk`, and `CheckHealth` RPCs. The
checked-in Python client/server files are generated with `grpcio-tools`.
After changing the protocol, regenerate those files from the repository root:

```powershell
.\.venv\Scripts\python.exe -m grpc_tools.protoc -I . --python_out=. --grpc_python_out=. backend\storage\proto\storage.proto
```

Storage-node processes are configured independently with a node ID, a port,
and a node-specific data directory. Each node rejects invalid chunk IDs and
checks the supplied SHA-256 value before writing. Its health RPC reports
current used bytes, configured capacity, and stored chunk count.

For a file, the API reads chunks of `CLUSTERDRIVE_CHUNK_SIZE_BYTES` (default
1 MiB). A health check filters unavailable nodes. Primary chunk writes use
round-robin placement across the ordered healthy list, advancing across
uploads; secondary copies use following healthy nodes. The API accepts the
metadata after its primary copies are written, and background workers create
the remaining copies. Each replica tracks its current and target version and
is reported as pending until its bytes are copied and SHA-256 verified. A
failed write is retried on other eligible nodes; the metadata records the
successful destination. A replica is marked failed only after all eligible
destinations reject it, never synchronized. If fewer healthy nodes exist, the
available count is used and the file is marked degraded; with no healthy nodes,
upload fails with HTTP 503. If a node fails after a second replica was
synchronized, downloads fall back to that remaining copy. Partial primary
writes are rolled back when an upload cannot be accepted.

Placement counts and per-node upload, replication, download, and delete request
counts are process-local metrics exposed through `/api/metrics`. The placement
strategy is round-robin per chunk, with health checks before each upload.

Each chunk and each stored replica is associated with the original file ID,
filename, byte size, chunk order, node ID, and SHA-256 checksum. During
download, each chunk is tried against its recorded replicas. Missing nodes,
missing chunks, incorrect hashes, or incorrect lengths are skipped in favor of
another copy. If all copies fail, the API returns HTTP 502 identifying the
chunk and replica errors instead of returning a partial file.

The current metadata catalog is an atomic-write local JSON file at
`CLUSTERDRIVE_METADATA_PATH` (default `data/metadata.json`). This is for a
single local API process and is **not** distributed or Raft-replicated. Do not
delete that file or any node data directory to stop or restart the demo.

For local development, the API allows the Vite origins on ports `5173` and
`5174` for both `localhost` and `127.0.0.1`. These origins can be overridden
with the `CLUSTERDRIVE_CORS_ORIGINS` environment variable.

### Frontend

The React application renders the seven requested dashboard pages and calls
the API for real data and actions. It displays loading, empty, error, and
success states. A page must not imply that an operation succeeded until the API
confirms it. If temporary sample data is needed during development, it must be
visibly identified as sample data.

### API service

FastAPI is the browser-facing entry point. It validates requests, coordinates
metadata and storage operations, and returns clear errors. Browser traffic
uses HTTP; internal service operations use generated gRPC clients and
Protocol Buffer messages.

### Metadata and educational Raft service

Run three independent metadata processes with distinct IDs, peer addresses,
and persistent state directories. The nodes exchange `RequestVote` and
`AppendEntries` messages over generated gRPC/Protocol Buffers bindings. A
follower whose randomized election timeout expires becomes a candidate,
increments its term, votes for itself, and requests votes. A candidate becomes
leader only after receiving a majority. Leaders send periodic AppendEntries
heartbeats and replicate metadata operations through the same RPC.

The leader returns a successful proposal only after a majority of nodes has
stored the entry from the current term; it then advances the commit index and
applies committed operations to its local metadata state machine. Followers
apply the committed entries when they receive the leader's updated commit
index. Persistent state includes the current term, vote, log, commit/applied
indexes, and applied metadata state. The API finds the current leader and
proposes each metadata mutation through gRPC. If the leader or quorum is
unavailable, the write returns HTTP 503 and does not update the API catalog.
If a peer RPC times out after a leader may have replicated an entry, the
outcome can be uncertain; inspect `/api/raft/status` before retrying.

`GET /api/raft/status` reads the peers directly and reports unreachable nodes,
role and term, leader identity, heartbeat age, log/commit/applied indexes, and
recent entries. The Raft dashboard refreshes this status periodically.

The checked-in Python protocol bindings are generated from
`backend/metadata/raft.proto`. From the repository root, regenerate them after
changing the protocol with:

```powershell
.\.venv\Scripts\python.exe -m grpc_tools.protoc -I . --python_out=. --grpc_python_out=. backend\metadata\raft.proto
```

This is educational Raft, not production-ready consensus. It intentionally
omits TLS/authentication, membership changes, log compaction/snapshots,
backpressure, and hardened recovery/monitoring. API reads use its local
catalog; existing catalog records are not automatically imported into the
Raft state machine, and peer state is not yet used to rebuild the API catalog
if that catalog is lost. Raft protects metadata agreement, not file bytes or
storage-node durability.

### Implemented educational coordination algorithms

The API currently creates three logical metadata nodes (`metadata-01` through
`metadata-03`) in one process. Each has its own Lamport clock. A local event
increments that node's clock, an outbound permission message increments it
before send, and receiving a message sets it to `max(local, received) + 1`.
File upload, download, delete, and recovery events include the participating
metadata node ID and logical timestamp where relevant. These logical counters
express causal ordering; they are not wall-clock timestamps.

File uploads and deletes enter a shared `file-write` critical section using
Ricart–Agrawala: a requester broadcasts its Lamport request timestamp and waits
for permission from every other logical node. A node defers permission while
inside the critical section or when its own request has earlier priority.
Priority is the pair `(request timestamp, node ID)`, so equal timestamps have a
deterministic order. After permissions arrive, the API submits metadata changes
to the Raft leader and updates its local catalog only after a majority commit.
Its file-chunk writes remain gRPC operations to storage nodes. The
Lamport/Ricart–Agrawala visualization still uses an educational in-process
message network; the separate Raft metadata processes provide the actual
consensus path for API catalog mutations.

The deadlock demonstration uses a wait-for graph whose edges point from a
waiting transaction to the transaction holding its requested lock. The demo
creates two transactions and two locks in a fixed sequence, so it does not rely
on thread scheduling. It detects the cycle and aborts the youngest transaction
(highest start order; greatest transaction ID breaks ties), releasing its locks to a
waiting transaction. The endpoint response and activity log include the graph
before and after recovery, victim, released locks, metadata node ID, and Lamport
timestamp. This transaction manager is a controlled algorithm demonstration;
it does not replace storage-node locking.

### Storage nodes

Each storage-node process exposes storage operations over gRPC and writes data
only to its own configured directory or persistent volume. Nodes receive file
chunks and return them when requested. The deployment must not point multiple
node instances at one shared local directory.

### Redis cache

Redis holds cacheable file metadata. The API uses a cache-aside pattern: check
Redis first, read from the local catalog on a miss, and cache the result using
`CLUSTERDRIVE_METADATA_CACHE_TTL_SECONDS` (default 60 seconds). File create,
delete, and replica-state changes invalidate the file-list and relevant
file-record keys. Hits, misses, errors, hit rate, availability, and TTL are
observable from `/api/metrics` and the dashboard. If Redis is unreachable or
an entry is malformed, the API logs a warning and uses the local catalog;
Redis failure does not prevent file operations.

## Main upload and download flows

### Upload

1. The browser sends the file to the API.
2. The API divides it into chunks and calculates a SHA-256 checksum for each
   chunk.
3. The API health-checks nodes using gRPC and chooses primary placement by
   round-robin; subsequent healthy nodes are replica targets.
4. It writes and verifies primary chunk copies, obtains Ricart–Agrawala
   permissions, and asks the elected Raft leader to commit the metadata and
   clock-tagged activity event to a majority.
5. The API applies the locally committed record only after the Raft leader
   confirms the majority commit.
6. Background workers copy secondary replicas, verify checksums, and update
   their version and status. Replication status remains pending until those
   workers complete.

### Download

1. The API looks up file metadata in Redis, falling back to the local catalog
   on a cache miss or Redis error.
2. It fetches chunks from healthy storage nodes over gRPC.
3. It verifies each chunk against its SHA-256 checksum.
4. It reconstructs and returns the file only when the data is complete and
   valid; otherwise, it reports which recovery path failed.

## Running the local gRPC cluster on Windows

Run all commands from the repository root unless a step says otherwise. Stop
each running process with **Ctrl+C**; this leaves node data and the JSON
catalog in place.

### 1. Install Python dependencies once

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

This uses the project virtual environment's Python directly, avoiding a
possibly stale global `pip.exe` or `uvicorn.exe` launcher.

### 2. Start Redis (optional, but needed to observe cache hits)

In a separate PowerShell terminal, start a local Redis container:

```powershell
docker run --name clusterdive-redis -p 6379:6379 -d redis:7-alpine
```

The API uses this address by default. If Redis is not running, the API logs the
cache error and safely reads the local JSON catalog. Stop the container with
`docker stop clusterdive-redis`; this demo cache is disposable and does not
contain the authoritative metadata.

### 3. Start three independent storage nodes

Open three separate PowerShell terminals. Each command sets a unique node ID,
gRPC port, and persistent storage path. The node creates its directory if it
does not exist.

**Terminal 1:**

```powershell
$env:CLUSTERDRIVE_NODE_ID = "node-01"
$env:CLUSTERDRIVE_NODE_PORT = "50051"
$env:CLUSTERDRIVE_NODE_STORAGE_DIR = ".\data\storage\node-01"
.\.venv\Scripts\python.exe -m backend.storage.node
```

**Terminal 2:**

```powershell
$env:CLUSTERDRIVE_NODE_ID = "node-02"
$env:CLUSTERDRIVE_NODE_PORT = "50052"
$env:CLUSTERDRIVE_NODE_STORAGE_DIR = ".\data\storage\node-02"
.\.venv\Scripts\python.exe -m backend.storage.node
```

**Terminal 3:**

```powershell
$env:CLUSTERDRIVE_NODE_ID = "node-03"
$env:CLUSTERDRIVE_NODE_PORT = "50053"
$env:CLUSTERDRIVE_NODE_STORAGE_DIR = ".\data\storage\node-03"
.\.venv\Scripts\python.exe -m backend.storage.node
```

Each should print that its ID is listening on its configured port and show a
different data directory. Never point two node processes at the same
directory.

### 4. Start three independent Raft metadata nodes

Open three additional PowerShell terminals from the repository root. The
metadata processes use ports `50161`–`50163` and create a unique persistent
state file under `.\data\metadata-nodes\<node-id>\raft-state.json`.
Do not delete or share those state directories.

**Metadata terminal 1:**

```powershell
$env:CLUSTERDRIVE_METADATA_NODES = "metadata-01=127.0.0.1:50161,metadata-02=127.0.0.1:50162,metadata-03=127.0.0.1:50163"
$env:CLUSTERDRIVE_METADATA_STATE_DIR = ".\data\metadata-nodes"
.\.venv\Scripts\python.exe -m backend.metadata.server --node-id metadata-01
```

**Metadata terminal 2:**

```powershell
$env:CLUSTERDRIVE_METADATA_NODES = "metadata-01=127.0.0.1:50161,metadata-02=127.0.0.1:50162,metadata-03=127.0.0.1:50163"
$env:CLUSTERDRIVE_METADATA_STATE_DIR = ".\data\metadata-nodes"
.\.venv\Scripts\python.exe -m backend.metadata.server --node-id metadata-02
```

**Metadata terminal 3:**

```powershell
$env:CLUSTERDRIVE_METADATA_NODES = "metadata-01=127.0.0.1:50161,metadata-02=127.0.0.1:50162,metadata-03=127.0.0.1:50163"
$env:CLUSTERDRIVE_METADATA_STATE_DIR = ".\data\metadata-nodes"
.\.venv\Scripts\python.exe -m backend.metadata.server --node-id metadata-03
```

Each terminal should log its node ID and listening address. Within a few
seconds, one node should log that it became leader. Confirm the peer view from
another terminal after starting the API with
`Invoke-RestMethod http://127.0.0.1:8001/api/raft/status`; expect one leader,
two followers, and `quorum_available` set to `True`.

To observe recovery, press **Ctrl+C** in the elected leader's terminal. The
remaining two peers should elect a new leader with a higher term. With only one
metadata process left, the status reports no majority and metadata-changing
API requests return HTTP 503 instead of claiming a successful commit.

### 5. Start FastAPI

In another PowerShell terminal:

```powershell
$env:CLUSTERDRIVE_STORAGE_NODES = "node-01=127.0.0.1:50051,node-02=127.0.0.1:50052,node-03=127.0.0.1:50053"
$env:CLUSTERDRIVE_METADATA_NODES = "metadata-01=127.0.0.1:50161,metadata-02=127.0.0.1:50162,metadata-03=127.0.0.1:50163"
$env:CLUSTERDRIVE_METADATA_STATE_DIR = ".\data\metadata-nodes"
$env:CLUSTERDRIVE_REPLICATION_FACTOR = "2"
$env:CLUSTERDRIVE_CHUNK_SIZE_BYTES = "1048576"
$env:CLUSTERDRIVE_METADATA_PATH = ".\data\metadata.json"
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8001
```

The environment variables tell the API where to find each gRPC node, how many
replicas to write, the Raft peer addresses, the chunk size, and where to
persist the local file catalog. Successful startup prints `Uvicorn running on
http://127.0.0.1:8001`.

Open interactive API docs at <http://127.0.0.1:8001/docs>. `GET /api/nodes`
should show three healthy nodes before uploading.
Open **Distributed Algorithms** in the dashboard to inspect metadata-node
clocks and protocol events, then select **Run controlled deadlock demo** to see
the wait-for graph before and after recovery. The same deterministic demo can
be called from PowerShell with:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/api/algorithms/deadlock-demo"
```

The response reports the detected cycle, the aborted youngest transaction,
released locks, and the graph after recovery.

### 6. Start the frontend

In another PowerShell terminal:

```powershell
Set-Location .\frontend
$env:VITE_API_BASE_URL = "http://127.0.0.1:8001"
npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Open <http://127.0.0.1:5174/>. The File Manager's **Choose file** button
previews a local file. **Upload to cluster** sends that file to the API. A
successful upload appears in the file list with a replica count; Download
reconstructs it and Delete asks for confirmation before removing its copies.

### 7. Run automated tests

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

The backend tests start temporary gRPC servers using separate temporary
directories; they do not touch `data/storage` or `data/metadata.json`.

For the frontend tests:

```powershell
Set-Location .\frontend
npm test
npm run build
```

The frontend tests mock HTTP responses to verify UI states. The backend
integration tests use real local gRPC sockets.

## Docker Compose deployment

Compose starts the frontend, API, three storage nodes, three Raft metadata
nodes, and Redis on one private bridge network. Service-to-service calls use
Docker DNS names (for example `storage-node-01`, `metadata-01`, and `redis`),
not host `localhost`. The frontend uses Nginx to proxy `/api`, `/health`, and
`/docs` to the API. Replica synchronization runs in the API's background
thread pool, so it does not need a separate container.
Metadata nodes listen on all interfaces inside their containers while peers
connect using their Compose service names; local non-container runs retain
their configured bind address.

From the repository root, create the local, non-secret Compose environment
file, then build and start the stack:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

The frontend is at <http://localhost:5174/>. API docs are at
<http://localhost:8001/docs>, and Raft status is at
<http://localhost:8001/api/raft/status>. Compose waits for Redis, each storage
node, and each metadata node to pass its health check before starting the API;
it starts the frontend after the API health check passes. Raft nodes start
together and retry peer communication while they elect a leader. Compose's
metadata health check confirms the gRPC listener is accepting connections;
the Raft status endpoint separately reports the current role, leader, and
heartbeat state. The wider election and RPC timeouts in `.env.example` allow
for scheduling delays on Docker Desktop; increase `CLUSTERDRIVE_STORAGE_RPC_TIMEOUT_SECONDS`
or `CLUSTERDRIVE_METADATA_RPC_TIMEOUT_SECONDS` if your computer is under heavy
load.

The stack uses separate named volumes for the API catalog, Redis, all three
storage nodes, and all three metadata nodes. They survive container rebuilds,
`docker compose stop`, `docker compose down`, and a normal restart. Avoid
`docker compose down -v`: that explicitly deletes the named volumes and all
data they contain.

Useful safe inspection and lifecycle commands:

```powershell
docker compose ps
docker compose logs -f
docker compose logs -f api metadata-01 storage-node-01
docker compose stop
docker compose start
docker compose up --build -d
docker compose down
```

`docker compose stop` followed by `docker compose start` preserves the
containers and data. `docker compose down` removes containers and the network,
but keeps named volumes; `docker compose up --build -d` recreates containers
using those same volumes. To verify storage end to end, upload a file in the
File Manager, download it, and compare the downloaded bytes to the original.
The backend integration tests also exercise upload and reconstruction over
gRPC using temporary storage paths.

## Distributed-systems demonstrations

- **Lamport logical clocks:** attach logical timestamps to events so events
  across services can be shown in a consistent causal order. These clocks
  express ordering, not real-world elapsed time.
- **Distributed mutual exclusion:** coordinate access to a shared operation so
  only the permitted participant proceeds at a time.
- **Deadlock detection and recovery:** observe a wait-for relationship between
  participants, detect a cycle, and demonstrate an explicit recovery action.
- **Load balancing:** choose among healthy storage nodes when placing or
  reading chunks, rather than sending all work to a single node.
- **Eventual consistency:** replicate asynchronously and expose when a replica
  is pending synchronization; healthy replicas should converge after the
  system can communicate again.
- **Redis caching:** show cache hits, misses, expiration, and invalidation
  based on actual API behavior.
- **Raft consensus:** expose peer health, leader changes, heartbeats, log
  replication, and majority commits from the metadata service.
- **Distributed file storage:** distribute and replicate chunks, then
  reconstruct and checksum-verify the original file.

The Lamport clock, Ricart–Agrawala mutual exclusion, wait-for graph, and
deadlock-recovery demonstration are implemented and tested. Raft, Redis, and
asynchronous eventual-consistency synchronization remain unimplemented; their
dashboard statuses do not claim otherwise.

## Deployment and configuration

Docker Compose is the first full deployment. Each storage-node service gets a
different persistent volume. Health checks should distinguish a running
process from a service that is ready to handle requests. Logs should identify
the service and relevant operation without printing secrets or file contents.

After Compose behavior is tested, Kubernetes manifests will deploy separate
service instances and storage replicas with local persistent volumes and
health probes. Configuration is supplied through environment variables;
secrets are not committed to the repository.

## Planned repository layout

```text
ClusterDrive/
├── PROJECT_PLAN.md
├── docs/
│   └── ARCHITECTURE.md
├── frontend/                 # React + Vite dashboard
├── services/
│   ├── api/                  # FastAPI browser-facing service
│   ├── metadata/             # Educational Raft metadata service
│   └── storage/              # gRPC storage-node implementation
├── proto/                    # Shared Protocol Buffer definitions
├── tests/                    # Cross-service and end-to-end tests
├── deploy/
│   ├── compose/              # Docker Compose configuration
│   └── kubernetes/           # Local Kubernetes manifests
├── requirements.txt          # Python dependencies (added during setup)
└── .gitignore
```

This is a target layout, not an assertion that these services or features have
already been implemented.
