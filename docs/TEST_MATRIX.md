# ClusterDrive: Test Matrix & Verification Checklist

This document provides a report-ready verification checklist covering all ten distributed systems syllabus topics, automated test results, end-to-end deployment verification (Docker Compose & Kubernetes), and a screenshot capture guide for academic reporting.

---

## 1. Ten Syllabus Topics Verification Matrix

| # | Syllabus Topic | Key Implementation Files | Verification Mechanism | Status |
|---|---|---|---|---|
| **1** | **gRPC & Protocol Buffers** | `proto/storage.proto`<br>`proto/raft.proto`<br>`backend/storage/node.py`<br>`backend/app/storage_client.py` | Storage chunk store/retrieve/replicate/delete RPCs, Raft RequestVote & AppendEntries RPCs. Unit tests in `backend/tests/test_distributed_storage.py`. | **VERIFIED** |
| **2** | **Lamport Logical Clocks** | `backend/algorithms/lamport.py`<br>`backend/tests/test_algorithms.py` | Monotonic clock tick on events, `max(local, received) + 1` merge on message reception. Verified by unit tests. | **VERIFIED** |
| **3** | **Distributed Mutual Exclusion** | `backend/algorithms/ricart_agrawala.py`<br>`backend/tests/test_algorithms.py` | Ricart–Agrawala algorithm with REQUEST/REPLY exchanges, deferred replies, timestamp ordering, and node ID tie-breaking. Verified by concurrent simulation tests. | **VERIFIED** |
| **4** | **Deadlock Detection & Recovery** | `backend/algorithms/deadlock.py`<br>`backend/app/routes.py`<br>`backend/tests/test_algorithms.py` | Resource wait-for graph with Tarjan/DFS cycle detection, deterministic victim selection (youngest transaction), lock abort and release. Interactive demo at `/api/algorithms/deadlock-demo`. | **VERIFIED** |
| **5** | **Load Balancing** | `backend/app/storage_service.py`<br>`backend/tests/test_distributed_storage.py` | Round-robin chunk distribution across available storage nodes. Skips unhealthy nodes dynamically. Verified by chunk distribution assertions. | **VERIFIED** |
| **6** | **Eventual Consistency** | `backend/app/replication.py`<br>`backend/app/storage_service.py`<br>`backend/tests/test_distributed_storage.py` | Asynchronous replica synchronization, tracking `pending`, `synchronized`, `degraded`, and `failed` states. Interactive lag induction and convergence demo at `/api/replication/demo`. | **VERIFIED** |
| **7** | **Redis Caching** | `backend/app/metadata_cache.py`<br>`backend/tests/test_metadata_cache.py` | Cache-aside metadata reads with TTL, cache hit/miss/error telemetry, cache invalidation on write/delete, and transparent fallback to disk catalog during Redis outages. | **VERIFIED** |
| **8** | **Raft Consensus** | `backend/metadata/raft_node.py`<br>`backend/metadata/server.py`<br>`backend/tests/test_raft_cluster.py` | 3-node metadata cluster, leader election, randomized election timeouts (5.0s–8.0s), AppendEntries heartbeats (0.5s), log replication, majority commit quorum (2/3), persistent state across node restarts. | **VERIFIED** |
| **9** | **Kubernetes Pod Deployment** | `k8s/*.yaml`<br>`docs/KUBERNETES.md`<br>`scratch/verify_k8s.py` | Deployments, 3-replica StatefulSet with headless service and volumeClaimTemplates, dedicated PVCs per node, NodePort services, tcpSocket/httpGet probes, resource limits. Live verification on Docker Desktop K8s. | **VERIFIED** |
| **10** | **Distributed File Storage** | `backend/app/storage_service.py`<br>`backend/storage/node.py`<br>`backend/tests/test_distributed_storage.py` | File chunking (1 MB default), SHA-256 chunk checksumming, multi-replica placement, fault-tolerant reconstruction fallback when nodes fail, and byte-for-byte SHA-256 integrity verification. | **VERIFIED** |

---

## 2. Automated Test Execution Results

### 2.1 Backend Test Suite (Pytest)
- **Command:** `.venv\Scripts\python.exe -m pytest backend/tests -v`
- **Result:** **41 passed in 29.61s**
- **Platform:** Windows 11 (Python 3.14 / pytest 9.1.1)

#### Test Breakdown by Module:
1. `backend/tests/test_algorithms.py` (5 tests):
   - `test_lamport_clock_ticks_sends_and_merges_received_timestamps`: **PASSED**
   - `test_simultaneous_ricart_agrawala_requests_never_overlap`: **PASSED**
   - `test_ricart_agrawala_uses_node_id_to_break_equal_timestamp_ties`: **PASSED**
   - `test_wait_for_graph_detects_cycle_aborts_youngest_and_releases_locks`: **PASSED**
   - `test_wait_for_graph_returns_no_victim_without_a_cycle`: **PASSED**

2. `backend/tests/test_api.py` (12 tests):
   - `test_health_returns_api_status`: **PASSED**
   - `test_dashboard_returns_live_empty_counts_and_feature_statuses`: **PASSED**
   - `test_files_returns_an_empty_list`: **PASSED**
   - `test_nodes_returns_an_empty_list_when_no_nodes_are_configured`: **PASSED**
   - `test_logs_returns_an_empty_list`: **PASSED**
   - `test_algorithm_status_returns_live_metadata_node_clocks`: **PASSED**
   - `test_controlled_deadlock_endpoint_recovers_and_logs_recovery`: **PASSED**
   - `test_metrics_reports_live_cache_and_unavailable_node_counts`: **PASSED**
   - `test_replication_status_reports_empty_actual_state`: **PASSED**
   - `test_raft_status_reports_the_metadata_cluster`: **PASSED**
   - `test_metadata_write_is_sent_through_the_consensus_client`: **PASSED**
   - `test_cors_allows_the_local_vite_origin`: **PASSED**

3. `backend/tests/test_distributed_storage.py` (15 tests):
   - `test_upload_splits_file_replicates_chunks_and_reconstructs_original`: **PASSED**
   - `test_upload_failure_rolls_back_chunks_written_to_storage_nodes`: **PASSED**
   - `test_secondary_replica_is_pending_until_asynchronous_sync_completes`: **PASSED**
   - `test_round_robin_placement_distributes_chunks_across_healthy_nodes`: **PASSED**
   - `test_file_list_cache_is_invalidated_after_upload`: **PASSED**
   - `test_round_robin_skips_a_node_that_becomes_unhealthy`: **PASSED**
   - `test_replica_reports_failed_when_destination_fails_during_sync`: **PASSED**
   - `test_replica_retries_an_alternate_destination_after_sync_failure`: **PASSED**
   - `test_controlled_replication_demo_exposes_lag_then_real_convergence`: **PASSED**
   - `test_download_falls_back_to_another_replica_when_one_node_fails`: **PASSED**
   - `test_download_falls_back_when_first_replica_checksum_is_corrupt`: **PASSED**
   - `test_download_reports_chunk_number_if_all_replicas_are_corrupt`: **PASSED**
   - `test_delete_removes_all_chunk_replicas_and_metadata`: **PASSED**
   - `test_single_healthy_node_upload_is_marked_as_degraded`: **PASSED**
   - `test_upload_requires_at_least_one_healthy_storage_node`: **PASSED**

4. `backend/tests/test_metadata_cache.py` (3 tests):
   - `test_cache_aside_tracks_miss_hit_and_configured_ttl`: **PASSED**
   - `test_cache_invalidation_forces_fresh_metadata_after_a_change`: **PASSED**
   - `test_redis_outage_logs_and_falls_back_to_metadata_loader`: **PASSED**

5. `backend/tests/test_raft_cluster.py` (6 tests):
   - `test_three_nodes_elect_one_leader_and_only_grant_one_vote_per_term`: **PASSED**
   - `test_proposal_is_committed_on_a_majority_and_applied_on_each_node`: **PASSED**
   - `test_cluster_elects_a_new_leader_after_the_current_leader_fails`: **PASSED**
   - `test_single_survivor_does_not_claim_metadata_commit_without_quorum`: **PASSED**
   - `test_api_returns_503_and_rolls_back_chunk_if_raft_cannot_commit`: **PASSED**
   - `test_term_vote_log_and_applied_state_survive_node_restart`: **PASSED**

---

### 2.2 Frontend Test Suite (Vitest)
- **Command:** `npm test --prefix frontend`
- **Result:** **10 passed in 24.65s** (100% passing)
- **Production Build:** `npm run build --prefix frontend` -> **Built in 8.87s**

#### Test Breakdown (`frontend/src/App.test.jsx`):
1. `shows backend-provided empty state rather than sample statistics`: **PASSED** (1978ms)
2. `navigates to API-backed node, Raft, replication, and algorithm pages`: **PASSED** (2106ms)
3. `shows real cache and round-robin metrics and runs replica convergence demo`: **PASSED** (1242ms)
4. `runs and displays the deterministic deadlock recovery demo`: **PASSED** (632ms)
5. `searches and filters file records returned by the API`: **PASSED** (1538ms)
6. `previews a selected local file and uploads it through the API`: **PASSED** (988ms)
7. `asks for confirmation and deletes a file through the API`: **PASSED** (637ms)
8. `shows a retryable error instead of substituting mock data when the API is unavailable`: **PASSED** (444ms)
9. `shows an empty state in activity logs when the API returns no events`: **PASSED** (468ms)

---

## 3. End-to-End Live Deployment Verification

### 3.1 Docker Compose Flow
- **Execution:** `docker compose up --build -d`
- **Containers Verified (9/9 healthy):**
  - `clusterdive-frontend-1` (`http://localhost:5173`)
  - `clusterdive-api-1` (`http://localhost:8000`)
  - `clusterdive-redis-1` (port 6379)
  - `clusterdive-storage-node-01-1`, `02-1`, `03-1` (port 50051)
  - `clusterdive-metadata-01-1`, `02-1`, `03-1` (port 50161)
- **E2E Scenario:**
  - 2.5 MB random payload uploaded across 3 storage nodes (3 chunks, 6 replicas).
  - Replica synchronization verified (`synchronized` status).
  - Direct API download and Frontend proxy download verified with byte-for-byte SHA-256 match.
  - Fault tolerance tested: stopped `storage-node-02`, verified `/api/nodes` reported unavailable, downloaded file via replica failover, restarted node with data intact.

### 3.2 Kubernetes Flow (Local Docker Desktop Cluster)
- **Execution:** `python scratch/verify_k8s.py` against live cluster in namespace `clusterdrive`.
- **Pods Verified (9/9 Running, 0 restarts):**
  - `api-7b9db6976f-pnt5c` (`1/1 Running`, NodePort 30081)
  - `frontend-64b5dd8967-hvlck` (`1/1 Running`, NodePort 30080)
  - `metadata-0`, `metadata-1`, `metadata-2` (`1/1 Running`, StatefulSet + headless service)
  - `redis-7cfd48f866-hhcqz` (`1/1 Running`, ClusterIP 6379)
  - `storage-node-01-85f97579fc-7th88`, `storage-node-02-7b9cd4fbbd-sf4lt`, `storage-node-03-67f6954867-hwthc` (`1/1 Running`, ClusterIP 50051)
- **PVCs Verified (8/8 Bound on hostpath):**
  - `api-catalog-pvc`, `redis-data-pvc`, `storage-node-01-pvc`, `storage-node-02-pvc`, `storage-node-03-pvc`
  - `metadata-data-metadata-0`, `metadata-data-metadata-1`, `metadata-data-metadata-2`
- **Live Test Log:**
  ```text
  [TEST] === Starting Kubernetes E2E Verification ===
  [TEST] Checking API health...
  [TEST] API health OK: {'status': 'ok', 'service': 'clusterdive-api', 'version': '0.2.0'}
  [TEST] Checking Raft status and active nodes...
  [TEST] Raft quorum available: Leader=metadata-01, term=410
  [TEST] All 3 storage nodes healthy: ['node-01', 'node-02', 'node-03']
  [TEST] Generating 2.5 MB test payload...
  [TEST] Uploading 2.5 MB file to API NodePort 30081...
  [TEST] Uploaded successfully! File ID: e18a7efae8b4458ca4e1fffafd5963d2, Chunks: 3
  [TEST] Files in catalog: 3
  [TEST] File confirmed in catalog: k8s_e2e_test.dat (2500000 bytes, 3 chunks)
  [TEST] Downloading file directly from API NodePort 30081...
  [TEST] API Download byte-for-byte SHA-256 match verified!
  [TEST] Downloading file through Frontend proxy NodePort 30080...
  [TEST] Frontend Proxy Download byte-for-byte SHA-256 match verified!
  [TEST] Testing node resilience: scaling storage-node-02 to 0 replicas...
  deployment.apps/storage-node-02 scaled
  [TEST] Waiting for node-02 to report unavailable...
  [TEST] Downloading file with storage-node-02 down (replica failover verification)...
  [TEST] Failover download succeeded! File was reconstructed from surviving replicas.
  [TEST] Restoring storage-node-02: scaling back to 1 replica...
  deployment.apps/storage-node-02 scaled
  [TEST] Waiting for storage-node-02 to recover...
  [TEST] Verified: storage-node-02 restored and healthy!
  [TEST] === All Kubernetes Verification Steps Passed! ===
  ```

---

## 4. Academic Report Screenshot Checklist

When taking screenshots for reports, presentation slides, or submissions, use the following checklist to capture key states:

- [ ] **Screenshot 1: Overview Dashboard**
  - **URL:** `http://localhost:30080` (or `http://localhost:5173`)
  - **Content to capture:** Live cluster metrics card, storage utilization bar, 3 active storage nodes indicator, Redis cache hit/miss statistics, and system health status.
- [ ] **Screenshot 2: File Manager & Multi-Chunk Redundancy**
  - **URL:** Dashboard -> "File Manager" page
  - **Content to capture:** Uploaded file table showing File ID, size, chunk count (3 chunks for 2.5 MB), replication status badge (`synchronized`), download button, and delete action.
- [ ] **Screenshot 3: Storage Nodes Health Monitor**
  - **URL:** Dashboard -> "Storage Nodes" page
  - **Content to capture:** Node cards for `node-01`, `node-02`, and `node-03` showing `healthy` status, gRPC port `50051`, chunk storage counts, and latency metrics.
- [ ] **Screenshot 4: Raft Consensus Cluster Monitor**
  - **URL:** Dashboard -> "Raft Cluster" page
  - **Content to capture:** 3 metadata peers (`metadata-01`, `metadata-02`, `metadata-03`), elected Leader badge, current Term number, Quorum Available (`true`), and commit index progression.
- [ ] **Screenshot 5: Replication & Eventual Consistency Demo**
  - **URL:** Dashboard -> "Replication & Consistency" page
  - **Content to capture:** Triggering the "Induce Lag" demo showing a degraded replica, followed by clicking "Converge" showing synchronization completion and version vector updates.
- [ ] **Screenshot 6: Deadlock Detection & Victim Abort Graph**
  - **URL:** Dashboard -> "Distributed Algorithms" page
  - **Content to capture:** "Run Deadlock Demo" visualization displaying the wait-for cycle between transactions, the chosen victim transaction (youngest timestamp), and the resolved acyclic graph after recovery.
- [ ] **Screenshot 7: Lamport Logical Clocks Display**
  - **URL:** Dashboard -> "Distributed Algorithms" page
  - **Content to capture:** Logical clock counters across metadata nodes showing monotonic timestamp increments and Ricart–Agrawala mutual exclusion permission grants.
- [ ] **Screenshot 8: Kubernetes CLI Pod & PVC Status**
  - **Terminal Command:** `kubectl get pods,pvc,svc -n clusterdrive`
  - **Content to capture:** All 9 pods in `Running` status with 0 restarts, all 8 PVCs `Bound`, and NodePort services (30080 and 30081) exposed.
- [ ] **Screenshot 9: Terminal Test Suite Run**
  - **Terminal Command:** `pytest backend/tests -v`
  - **Content to capture:** Terminal output showing `41 passed` across algorithms, api, distributed storage, cache, and raft tests.

