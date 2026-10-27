import { useCallback, useEffect } from 'react';
import { Clock3, GitBranch, Heart, Radio, RefreshCw, ShieldCheck } from 'lucide-react';
import { getRaftStatus } from '../api/client.js';
import PageHeader from '../components/PageHeader.jsx';
import ResourceState from '../components/ResourceState.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import useApiResource from '../hooks/useApiResource.js';

function roleTone(node) {
  if (!node.reachable) return 'red';
  if (node.role === 'leader') return 'green';
  if (node.heartbeat_state === 'stale') return 'amber';
  return 'blue';
}

function operationSummary(command) {
  if (command.kind === 'file_upsert') return `File metadata: ${command.record?.name ?? command.record?.id ?? 'file'}`;
  if (command.kind === 'file_delete') return `Delete file metadata: ${command.file_id}`;
  if (command.kind === 'replica_update') return `Replica ${command.status}: ${command.chunk_id}`;
  if (command.kind === 'activity_append') return command.event?.event ?? 'Activity event';
  return command.kind ?? 'Metadata operation';
}

export default function RaftPage() {
  const loadRaftStatus = useCallback(getRaftStatus, []);
  const resource = useApiResource(loadRaftStatus);
  const cluster = resource.data;

  useEffect(() => {
    const refreshTimer = window.setInterval(resource.retry, 5000);
    return () => window.clearInterval(refreshTimer);
  }, [resource.retry]);

  const reachable = cluster?.reachable_nodes ?? 0;
  const nodeCount = cluster?.node_count ?? 0;
  const quorumPercent = nodeCount ? Math.min(100, (reachable / nodeCount) * 100) : 0;
  const reachableCommitIndexes = cluster?.nodes
    .filter((node) => node.reachable)
    .map((node) => node.commit_index) ?? [];
  const minimumCommitIndex = reachableCommitIndexes.length
    ? Math.min(...reachableCommitIndexes)
    : 0;

  return (
    <>
      <PageHeader
        eyebrow="METADATA CONSENSUS"
        title="Raft cluster"
        description="Live role, term, heartbeat, and replicated-log state queried from the metadata peers. Refreshes every 5 seconds."
        action={(
          <div className="raft-header-actions">
            {cluster && (
              <StatusBadge tone={cluster.leader_id && cluster.quorum_available ? 'green' : 'amber'}>
                {cluster.leader_id ? `Leader ${cluster.leader_id}` : 'No leader'}
              </StatusBadge>
            )}
            <button className="secondary-button" type="button" onClick={resource.retry} disabled={resource.loading}>
              <RefreshCw size={14} /> Refresh
            </button>
          </div>
        )}
      />
      <ResourceState
        loading={resource.loading && !cluster}
        error={cluster ? null : resource.error}
        onRetry={resource.retry}
        label="Reading metadata peers over gRPC…"
      >
        {cluster && (
          <>
            {resource.error && (
              <p className="inline-error" role="alert">
                The latest peer refresh failed; showing the last successful status. {resource.error.message}
              </p>
            )}
            <section className="raft-overview-grid">
              <article className="panel raft-leader-card">
                <div className="raft-leader-head">
                  <span className="raft-leader-icon"><GitBranch size={20} /></span>
                  <StatusBadge tone={cluster.leader_id ? 'green' : 'red'}>
                    {cluster.leader_id ? 'Leader elected' : 'No elected leader'}
                  </StatusBadge>
                </div>
                <p className="eyebrow">CURRENT LEADER</p>
                <h2>{cluster.leader_id || 'Unavailable'}</h2>
                <p className="raft-term">Leader identity is reported by the running Raft peers.</p>
                <div className="raft-leader-stats">
                  <div><small>Reachable peers</small><strong>{reachable} / {nodeCount}</strong></div>
                  <div><small>Lowest reachable commit</small><strong>{minimumCommitIndex}</strong></div>
                </div>
              </article>
              <article className="panel raft-quorum-card">
                <div className="panel-heading">
                  <div><p className="eyebrow">MAJORITY COMMIT</p><h2>{cluster.quorum_available ? 'Quorum reachable' : 'Quorum unavailable'}</h2></div>
                  <ShieldCheck size={19} className={cluster.quorum_available ? 'text-green' : 'text-amber'} />
                </div>
                <div className="quorum-count">
                  <strong>{reachable} / {cluster.quorum_required}</strong>
                  <span>reachable / required for a commit</span>
                </div>
                <div className="quorum-track" role="progressbar" aria-label="Reachable metadata peers" aria-valuenow={reachable} aria-valuemin={0} aria-valuemax={nodeCount}>
                  <span style={{ width: `${quorumPercent}%` }} />
                </div>
                <p className="panel-footnote">
                  {cluster.quorum_available
                    ? 'An update is reported committed only after a majority acknowledges its log entry.'
                    : 'Metadata writes fail explicitly until a majority of metadata peers is reachable.'}
                </p>
              </article>
            </section>

            <section className="panel raft-peers-panel">
              <div className="panel-heading">
                <div><p className="eyebrow">PEER STATUS</p><h2>Metadata nodes</h2></div>
                <span className="inline-meta"><Heart size={14} /> gRPC peer health</span>
              </div>
              <div className="raft-peer-list">
                {cluster.nodes.map((node) => (
                  <article className="raft-peer raft-peer-detail" key={node.node_id}>
                    <span className={`raft-peer-icon ${node.role === 'leader' ? 'raft-peer-green' : 'raft-peer-blue'}`}>
                      <GitBranch size={16} />
                    </span>
                    <div className="raft-peer-info">
                      <strong>{node.node_id}</strong>
                      <span>{node.address} · term {node.term} · leader {node.leader_id || 'unknown'}</span>
                    </div>
                    <div className="raft-peer-metrics">
                      <span><small>Log</small> {node.last_log_index}</span>
                      <span><small>Commit</small> {node.commit_index}</span>
                      <span><small>Applied</small> {node.last_applied}</span>
                    </div>
                    <div className="raft-peer-status">
                      <StatusBadge tone={roleTone(node)}>{node.reachable ? node.role : 'unavailable'}</StatusBadge>
                      <span className="heartbeat-indicator">
                        <i className={node.heartbeat_state === 'stale' || !node.reachable ? 'heartbeat-stale' : ''} />
                        {node.heartbeat_age_ms == null
                          ? 'No heartbeat'
                          : node.role === 'leader'
                            ? 'Leader active'
                            : `${node.heartbeat_age_ms} ms ago`}
                      </span>
                    </div>
                    {node.error && <p className="raft-peer-error">{node.error}</p>}
                  </article>
                ))}
              </div>
            </section>

            <section className="panel raft-log-panel">
              <div className="panel-heading">
                <div><p className="eyebrow">REPLICATED LOG</p><h2>Recent metadata entries</h2></div>
                <span className="inline-meta"><Radio size={14} /> From peer status RPCs</span>
              </div>
              {cluster.recent_entries.length ? (
                <div className="raft-log-list">
                  {cluster.recent_entries.map((entry) => (
                    <article className="raft-log-entry" key={`${entry.index}-${entry.term}`}>
                      <span className="raft-log-index">#{entry.index}</span>
                      <div className="raft-log-description">
                        <strong>{operationSummary(entry.command)}</strong>
                        <span>Term {entry.term} · operation {entry.command.operation_id ?? 'recorded'}</span>
                      </div>
                      <StatusBadge tone={entry.committed ? 'green' : 'amber'}>
                        {entry.committed ? 'Committed' : 'Uncommitted'}
                      </StatusBadge>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="empty-state compact-empty">
                  <span className="empty-state-icon"><Clock3 size={21} /></span>
                  <strong>No metadata operations are in the Raft log yet</strong>
                  <span>Committed file and activity metadata operations will appear here.</span>
                </div>
              )}
            </section>
            <p className="raft-education-note">
              Educational Raft implementation for a local project; it is not production-ready and does not replicate file bytes.
            </p>
          </>
        )}
      </ResourceState>
    </>
  );
}
