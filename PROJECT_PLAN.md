# ClusterDrive Project Plan

## Project goal

ClusterDrive is a local, educational file-storage application. It will show how
separate services can store, find, copy, and recover files when a storage node
is unavailable. The first deployment target is Docker Compose on Windows with
Docker Desktop. Kubernetes comes after the Compose version is working.

This is a college demonstration project, not production cloud storage. Its Raft
implementation and distributed algorithms are for learning and must not be
treated as production-grade security or reliability mechanisms.

## Planned technology

- **Frontend:** React, Vite, JavaScript, custom CSS, Lucide icons, and charts
  where they make real backend data easier to understand.
- **API:** Python 3.13 and FastAPI for browser-facing HTTP endpoints.
- **Internal communication:** gRPC and Protocol Buffers for API-to-service and
  service-to-service communication.
- **Metadata:** a separate educational Raft metadata service that tracks file
  metadata and cluster state.
- **Storage:** multiple Python gRPC storage-node instances, each with its own
  storage directory or persistent volume.
- **Cache:** Redis, used with cache-aside reads, expiration, and invalidation.
- **Local deployment:** Docker Compose first, then Kubernetes manifests for
  local Kubernetes.
- **Tests:** pytest for Python services and suitable automated frontend tests.

Dependency versions will be selected and recorded in `requirements.txt` when
the implementation phase begins. Secrets and machine-specific configuration
will be provided through environment variables and excluded from Git.

## Proposed implementation roadmap

Each phase should leave the project runnable and have focused tests before the
next phase begins. A feature is complete only after its behavior is implemented
and verified; the dashboard must not present planned or mock behavior as live
cluster data.

### Phase 0 — Project foundation

- Create the frontend, API, metadata, storage-node, shared-protocol, test, and
  deployment directories.
- Add dependency manifests, environment-variable examples without secrets,
  and basic development instructions.
- Agree on service boundaries and the initial gRPC message definitions.
- **Check:** the frontend and Python test commands can run, and generated or
  local data is excluded from Git.

### Phase 1 — Frontend dashboard (implemented)

- Build the dark, responsive dashboard and seven pages: Overview, File Manager,
  Storage Nodes, Replication and Consistency, Distributed Algorithms,
  Raft Cluster, and Activity Logs.
- Connect the UI through a centralized API client with loading, empty, error,
  and success states. Do not substitute mock data for service results.
- **Check:** frontend tests cover key workflows and the production build
  succeeds.

### Phase 2 — FastAPI foundation and HTTP integration (implemented)

- Add Pydantic models, local CORS, health and dashboard endpoints, and live
  file/node/log read endpoints.
- Connect the frontend to the API and expose interactive API documentation.
- **Check:** pytest covers health and read endpoints; UI shows API errors
  rather than silently using sample data.

### Phase 3 — gRPC distributed storage (implemented)

- Define and generate Protocol Buffer code for storage operations.
- Run separate storage-node processes with unique persistent directories.
- Split uploads into chunks, replicate and checksum them, reconstruct downloads,
  and fall back when a storage node fails.
- **Check:** automated tests exercise gRPC uploads, downloads, checksums,
  reconstruction, and node failure.

### Phase 4 — Distributed algorithms (implemented)

- Implement Lamport logical clocks, Ricart–Agrawala mutual exclusion, and a
  deterministic wait-for-graph deadlock recovery demo.
- Show actual algorithm state and outcomes in the dashboard.
- **Check:** tests prove clock merging, exclusive critical-section entry, cycle
  detection, and documented victim recovery.

### Phase 5 — Eventual consistency, Redis, and load balancing (implemented)

- Synchronize replicas asynchronously and track versions and pending,
  synchronized, and failed states.
- Add Redis cache-aside reads, TTL, metrics, invalidation, and safe catalog
  fallback when Redis is unavailable.
- Balance chunk placement across healthy nodes and retry failed replica
  destinations.
- **Check:** tests cover convergence, cache invalidation/fallback, node health,
  placement distribution, and replica retry.

### Phase 6 — Educational Raft metadata cluster (implemented)

- Run three independent metadata-node processes with separate persistent
  term, vote, log, commit-index, and applied-state files.
- Use gRPC RequestVote and AppendEntries for elections, heartbeats, replication,
  and majority-based commits; apply committed metadata operations on each peer.
- Route API metadata mutations through the elected leader and return an error
  if no majority commits the update. Show live peer health and log state in
  the Raft dashboard.
- **Check:** integration tests cover voting, leader election, replication,
  leader failure, persistent state, and refusal to claim a commit without
  quorum.
- **Limitation:** this implementation is educational, not production-ready;
  migrating existing catalog records or rebuilding the API catalog from peer
  state is not implemented.

### Phase 7 — Docker Compose development deployment (implemented)

- Containerize the frontend, API, metadata peers, Redis, and multiple storage
  nodes.
- Configure health checks, service networking, environment variables, and
  distinct persistent volumes for storage-node instances.
- Document start, status, log, test, and safe stop commands.
- **Check:** the complete application can be started locally, upload and
  download files, and demonstrate a storage-node failure without deleting
  existing project data.

### Phase 8 — Kubernetes deployment (implemented)

- Add Kubernetes manifests for the frontend, API, metadata peers, Redis, and
  separate storage-node instances.
- Use appropriate persistent volumes, health probes, configuration, and
  service discovery for local Kubernetes.
- Document how to deploy and inspect the cluster.
- **Check:** the Kubernetes deployment can be exercised with the same core
  upload, download, health, replication, and recovery scenarios as Compose.

### Phase 9 — Quality, testing pass, and academic reporting (implemented)

- Verified all 10 distributed systems syllabus topics across the codebase.
- Executed full test suites: 41 backend pytest tests passing, 10 frontend Vitest tests passing, production build passing in 8.87s.
- Created report-ready test matrix and screenshot capture checklist (docs/TEST_MATRIX.md).
- Executed real local Kubernetes end-to-end verification (scratch/verify_k8s.py) testing health, Raft quorum, chunking, replica synchronization, direct and proxy downloads, node failure, and recovery.
- Generated comprehensive production README.md with architecture diagrams, setup guides, syllabus matrix, and a 5-minute demonstration script.

## Working agreements

- Implement in small phases; do not build the whole system in one step.
- Keep storage-node data separate and do not use cleanup commands that could
  erase existing project data.
- Explain new distributed-systems terms in plain language in the relevant
  documentation.
- Report test commands and their actual results; do not describe untested work
  as complete.
- Keep runtime credentials out of source control. Commit only safe examples
  such as `.env.example`.
