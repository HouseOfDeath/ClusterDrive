import { useCallback } from 'react';
import { Activity, Clock3, HardDrive, Network } from 'lucide-react';
import { getNodes } from '../api/client.js';
import MetricCard from '../components/MetricCard.jsx';
import PageHeader from '../components/PageHeader.jsx';
import ResourceState from '../components/ResourceState.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import useApiResource from '../hooks/useApiResource.js';

export default function StorageNodesPage() {
  const loadNodes = useCallback(getNodes, []);
  const resource = useApiResource(loadNodes);
  const nodes = resource.data?.items ?? [];
  const totalCapacity = nodes.reduce((sum, node) => sum + node.storage_capacity_bytes, 0);

  const cards = resource.data ? [
    { label: 'Registered nodes', value: String(resource.data.count), detail: 'Returned by the API', icon: 'nodes', trend: 'Current count', trendTone: 'neutral' },
    { label: 'Available capacity', value: formatBytes(totalCapacity), detail: nodes.length ? 'Sum of configured node capacity' : 'No capacity configured', icon: 'database', trend: 'Current value', trendTone: 'neutral' },
    { label: 'Healthy nodes', value: `${resource.data.active_count} / ${resource.data.count}`, detail: 'Healthy / registered', icon: 'cache', trend: resource.data.count ? 'Current count' : 'No nodes registered', trendTone: 'neutral' },
  ] : [];

  return (
    <>
      <PageHeader
        eyebrow="INFRASTRUCTURE"
        title="Storage nodes"
        description="Node inventory and health returned by the ClusterDrive API."
        action={<StatusBadge tone="blue">API state</StatusBadge>}
      />
      <ResourceState loading={resource.loading} error={resource.error} onRetry={resource.retry} label="Loading storage nodes…">
        {resource.data && (
          <>
            <section className="metric-grid metric-grid-three" aria-label="Storage node statistics">
              {cards.map((card) => <MetricCard key={card.label} {...card} />)}
            </section>
            <div className="section-heading-row">
              <div><p className="eyebrow">NODE INVENTORY</p><h2>Registered storage nodes</h2></div>
              <span className="inline-meta"><Network size={15} /> {resource.data.count} registered</span>
            </div>
            {nodes.length > 0 ? (
              <section className="node-card-grid">
                {nodes.map((node) => <NodeCard key={node.id} node={node} />)}
              </section>
            ) : (
              <section className="panel empty-state">
                <span className="empty-state-icon"><HardDrive size={22} /></span>
                <strong>No storage nodes registered</strong>
                <span>The API currently has no storage-node service instances configured.</span>
              </section>
            )}
            <p className="section-footnote">Node health is read from GET /api/nodes; the backend currently starts with an empty node list.</p>
          </>
        )}
      </ResourceState>
    </>
  );
}

function NodeCard({ node }) {
  const healthy = node.status === 'healthy';
  const tone = healthy ? 'green' : 'red';
  const capacity = node.storage_capacity_bytes;
  const used = node.storage_used_bytes;
  const usage = capacity > 0 ? Math.min(100, (used / capacity) * 100) : 0;

  return (
    <article className="panel node-detail-card">
      <div className="node-card-heading">
        <span className={`node-large-icon node-icon-${tone}`}><HardDrive size={20} /></span>
        <div><h3>{node.name}</h3><span className="node-location">{node.location || 'Location not configured'}</span></div>
        <StatusBadge tone={tone}>{node.status}</StatusBadge>
      </div>
      <div className="node-capacity-heading">
        <span>Storage capacity</span>
        <strong>{formatBytes(used)} <span>/ {capacity > 0 ? formatBytes(capacity) : 'Not configured'}</span></strong>
      </div>
      <div className="capacity-track"><span className="capacity-fill" style={{ width: `${usage}%` }} /></div>
      <div className="node-metrics">
        <div><Activity size={15} /><span>Files</span><strong>{node.file_count.toLocaleString()}</strong></div>
        <div><HardDrive size={15} /><span>Node ID</span><strong>{node.id}</strong></div>
      </div>
      <div className="node-health-note">
        <Clock3 size={14} />
        {healthy ? 'Reported healthy by the API' : 'Reported unavailable by the API'}
      </div>
      {node.error && <p className="node-error-detail" role="status">{node.error}</p>}
    </article>
  );
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
