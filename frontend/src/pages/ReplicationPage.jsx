import { useCallback, useState } from 'react';
import { ArrowDownToLine, Clock3, CopyCheck, Layers3, RefreshCw } from 'lucide-react';
import {
  convergeReplicationDemo,
  getClusterMetrics,
  getReplicationStatus,
  startReplicationDemo,
} from '../api/client.js';
import PageHeader from '../components/PageHeader.jsx';
import ResourceState from '../components/ResourceState.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import useApiResource from '../hooks/useApiResource.js';

async function loadReplication({ signal }) {
  const [replication, metrics] = await Promise.all([
    getReplicationStatus({ signal }),
    getClusterMetrics({ signal }),
  ]);
  return { replication, metrics };
}

export default function ReplicationPage() {
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState(null);
  const load = useCallback(loadReplication, []);
  const resource = useApiResource(load);
  const data = resource.data;
  const demo = data?.replication.demo;

  async function perform(action) {
    setActionLoading(true);
    setActionError(null);
    try {
      await action();
      resource.retry();
    } catch (error) {
      setActionError(error.message);
    } finally {
      setActionLoading(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="DATA SAFETY"
        title="Replication & consistency"
        description="Replica versions, asynchronous synchronization, cache health, and storage-node placement from the API."
        action={(
          <button className="secondary-button" type="button" onClick={resource.retry}>
            <RefreshCw size={15} /> Refresh status
          </button>
        )}
      />
      <ResourceState loading={resource.loading} error={resource.error} onRetry={resource.retry} label="Loading replication status…">
        {data && (
          <>
            <section className="replication-summary-grid">
              <Stat icon={CopyCheck} label="Replica target" value={`${data.replication.target_replicas} copies`} detail="Configured per chunk" />
              <Stat icon={Layers3} label="Synchronized" value={data.replication.synchronized} detail="Copies at target version" />
              <Stat icon={Clock3} label="Pending / failed" value={`${data.replication.pending} / ${data.replication.failed}`} detail="Actual replica copies" />
            </section>

            <section className="panel replication-panel">
              <div className="panel-heading">
                <div><p className="eyebrow">REPLICA HEALTH</p><h2>File and chunk synchronization</h2></div>
                <StatusBadge tone={data.replication.failed ? 'red' : data.replication.pending ? 'amber' : 'green'}>
                  {data.replication.failed ? 'Replication failed' : data.replication.pending ? 'Synchronization pending' : 'In sync'}
                </StatusBadge>
              </div>
              {data.replication.files.length === 0
                ? <div className="empty-state"><span className="empty-state-icon"><Layers3 size={22} /></span><strong>No file replica records</strong><span>Upload a file to see the real versions and synchronization state of each copy.</span></div>
                : (
                  <div className="replication-file-list">
                    {data.replication.files.map((file) => (
                      <article className="replication-file-row" key={file.file_id}>
                        <div className="replication-file-heading">
                          <span><strong>{file.name}</strong><small>{file.chunks.length} chunks · {file.file_id}</small></span>
                          <StateBadge state={file.status} />
                        </div>
                        <div className="replica-chunk-list">
                          {file.chunks.map((chunk) => (
                            <div className="replica-chunk-row" key={chunk.chunk_id}>
                              <span>Chunk {chunk.index}</span>
                              <div>
                                {chunk.replicas.map((replica) => (
                                  <span className="replica-version" key={replica.node_id}>
                                    <StateBadge state={replica.status} />
                                    <small>{replica.node_id} · v{replica.version}/{replica.target_version}</small>
                                    {replica.error && <small className="replication-error">{replica.error}</small>}
                                  </span>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              <div className="panel-footnote replication-footnote">
                <ArrowDownToLine size={14} />
                A replica is marked synchronized only after its version is written and checksum-verified on its storage node.
              </div>
            </section>
          </>
        )}
      </ResourceState>

      <section className="replication-extra-grid">
        <article className="panel replication-demo-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">CONTROLLED EVENTUAL-CONSISTENCY DEMO</p><h2>Observe lag, then converge</h2></div>
            {demo && <StateBadge state={demo.status} />}
          </div>
          <p className="replication-help">Creates a small real gRPC chunk on one healthy node while its peer replica remains pending. Convergence copies and verifies the chunk before reporting synchronized.</p>
          {actionError && <p className="inline-error" role="alert">{actionError}</p>}
          {demo && (
            <div className="replication-demo-state">
              <span>Source <strong>{demo.source_node} · v{demo.source_version}</strong></span>
              <span>Target <strong>{demo.target_node} · v{demo.target_version}</strong></span>
              {demo.error && <span className="replication-error">{demo.error}</span>}
            </div>
          )}
          <div className="replication-demo-actions">
            <button
              className="secondary-button"
              type="button"
              disabled={actionLoading}
              onClick={() => perform(startReplicationDemo)}
            >
              <Layers3 size={15} /> {actionLoading ? 'Working…' : 'Create replica lag'}
            </button>
            <button
              className="primary-button"
              type="button"
              disabled={actionLoading || !demo || demo.status !== 'pending'}
              onClick={() => perform(convergeReplicationDemo)}
            >
              <RefreshCw size={15} /> Converge replicas
            </button>
          </div>
        </article>
        <article className="panel replication-demo-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">REDIS CACHE-ASIDE</p><h2>Metadata cache metrics</h2></div>
            <StatusBadge tone={data?.metrics.cache_available ? 'green' : data?.metrics.cache_available === false ? 'amber' : 'neutral'}>
              {data?.metrics.cache_available ? 'Redis online' : data?.metrics.cache_available === false ? 'Catalog fallback' : 'Not checked'}
            </StatusBadge>
          </div>
          <div className="cache-metric-grid">
            <span>Hit rate<strong>{data?.metrics.cache_hit_rate == null ? '—' : `${data.metrics.cache_hit_rate.toFixed(1)}%`}</strong></span>
            <span>Hits / misses<strong>{data?.metrics.cache_hits} / {data?.metrics.cache_misses}</strong></span>
            <span>Redis errors<strong>{data?.metrics.cache_errors}</strong></span>
            <span>TTL<strong>{data?.metrics.cache_ttl_seconds}s</strong></span>
          </div>
          <p className="replication-help">On cache misses or Redis errors, metadata is read from the local catalog. Writes invalidate the file record and file-list keys.</p>
        </article>
      </section>

      <section className="panel placement-panel">
        <div className="panel-heading">
          <div><p className="eyebrow">STORAGE LOAD BALANCING</p><h2>Round-robin placement and request counts</h2></div>
          <StatusBadge tone="blue">{data?.metrics.active_nodes} / {data?.metrics.total_nodes} healthy</StatusBadge>
        </div>
        <p className="replication-help">Each chunk starts at the next node in a health-checked round-robin sequence. Replica destinations use subsequent healthy nodes; unhealthy nodes are skipped.</p>
        <div className="placement-node-grid">
          {Object.entries(data?.metrics.placement_counts || {}).map(([nodeId, placements]) => (
            <article className="placement-node" key={nodeId}>
              <strong>{nodeId}</strong>
              <span>Primary placements <b>{placements}</b></span>
              <span>Writes / replication / reads / deletes <b>{Object.values(data.metrics.request_counts[nodeId]).join(' / ')}</b></span>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}

function Stat({ icon: Icon, label, value, detail }) {
  return (
    <article className="panel replication-stat">
      <span className="replication-stat-icon icon-blue"><Icon size={18} /></span>
      <span><small>{label}</small><strong>{value}</strong><em>{detail}</em></span>
    </article>
  );
}

function StateBadge({ state }) {
  const tone = state === 'synchronized' ? 'green' : state === 'pending' ? 'amber' : state === 'failed' ? 'red' : 'neutral';
  const label = state === 'synchronized' ? 'Synchronized' : state === 'pending' ? 'Pending' : state === 'failed' ? 'Failed' : 'Degraded';
  return <StatusBadge tone={tone}>{label}</StatusBadge>;
}
