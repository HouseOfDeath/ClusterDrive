import { useCallback } from 'react';
import { ArrowRight, Clock3, HardDrive } from 'lucide-react';
import { getDashboard, getLogs, getNodes } from '../api/client.js';
import ActivityTable from '../components/ActivityTable.jsx';
import ClusterDiagram from '../components/ClusterDiagram.jsx';
import MetricCard from '../components/MetricCard.jsx';
import PageHeader from '../components/PageHeader.jsx';
import ResourceState from '../components/ResourceState.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import StorageChart from '../components/StorageChart.jsx';
import useApiResource from '../hooks/useApiResource.js';

async function fetchOverview({ signal }) {
  const [dashboard, nodes, logs] = await Promise.all([
    getDashboard({ signal }),
    getNodes({ signal }),
    getLogs({ signal }),
  ]);
  return { dashboard, nodes: nodes.items, logs: logs.items };
}

export default function OverviewPage({ onNavigate }) {
  const loadOverview = useCallback(fetchOverview, []);
  const overview = useApiResource(loadOverview);

  return (
    <>
      <PageHeader
        eyebrow="CLUSTER STATUS"
        title="Overview"
        description="Current counts and feature status reported by the ClusterDrive API."
      />
      <ResourceState loading={overview.loading} error={overview.error} onRetry={overview.retry}>
        {overview.data && (
          <>
            <section className="metric-grid" aria-label="Backend storage statistics">
              {createStats(overview.data.dashboard).map((stat) => (
                <MetricCard key={stat.label} {...stat} />
              ))}
            </section>
            <div className="overview-grid">
              <StorageChart dashboard={overview.data.dashboard} />
              <section className="panel quick-panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">CLUSTER HEALTH</p>
                    <h2>Storage nodes</h2>
                  </div>
                  <button className="text-button" type="button" onClick={() => onNavigate('nodes')}>
                    View nodes <ArrowRight size={14} />
                  </button>
                </div>
                <div className="health-summary">
                  <span className="health-number">
                    {overview.data.dashboard.active_nodes}
                    <span> / {overview.data.dashboard.total_nodes} online</span>
                  </span>
                  <span className="inline-meta"><HardDrive size={15} /> API state</span>
                </div>
                {overview.data.nodes.length > 0 ? (
                  <div className="quick-node-list">
                    {overview.data.nodes.slice(0, 4).map((node) => (
                      <div className="quick-node-row" key={node.id}>
                        <span className="node-mini-icon">
                          <i className={`health-dot ${node.status === 'healthy' ? 'dot-green' : 'dot-red'}`} />
                          {node.name}
                        </span>
                        <span className="quick-node-meta">
                          {node.location || 'Location not set'}
                          <b>{node.status}</b>
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="api-empty-inline">
                    <HardDrive size={17} />
                    <span>No storage nodes are registered in the backend.</span>
                  </div>
                )}
                {overview.data.nodes.some((node) => node.status !== 'healthy') && (
                  <div className="warning-note">
                    <span className="warning-icon">!</span>
                    <span><strong>Unavailable node</strong><small>At least one configured node is not healthy.</small></span>
                    <Clock3 size={15} className="warning-clock" />
                  </div>
                )}
              </section>
            </div>
            <div className="overview-grid overview-grid-bottom">
              <ClusterDiagram nodes={overview.data.nodes} />
              <section className="panel recent-panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">WHAT’S HAPPENING</p>
                    <h2>Recent activity</h2>
                  </div>
                  <button className="text-button" type="button" onClick={() => onNavigate('activity')}>
                    View all <ArrowRight size={14} />
                  </button>
                </div>
                <ActivityTable activities={overview.data.logs.slice(0, 3)} compact />
                <p className="panel-footnote">Events returned by the API · no generated sample entries</p>
              </section>
            </div>
          </>
        )}
      </ResourceState>
    </>
  );
}

function createStats(dashboard) {
  const used = formatBytes(dashboard.storage_used_bytes);
  const capacity = dashboard.storage_capacity_bytes > 0
    ? formatBytes(dashboard.storage_capacity_bytes)
    : 'Not configured';

  return [
    {
      label: 'Storage used',
      value: used,
      detail: `${capacity} capacity`,
      icon: 'database',
      trend: dashboard.storage_capacity_bytes > 0
        ? `${((dashboard.storage_used_bytes / dashboard.storage_capacity_bytes) * 100).toFixed(1)}% used`
        : 'No capacity set',
      trendTone: dashboard.storage_capacity_bytes > 0 ? 'green' : 'neutral',
    },
    {
      label: 'Total files',
      value: dashboard.total_files.toLocaleString(),
      detail: 'Reported by the API',
      icon: 'files',
      trend: 'Current count',
      trendTone: 'neutral',
    },
    {
      label: 'Active nodes',
      value: `${dashboard.active_nodes} / ${dashboard.total_nodes}`,
      detail: 'Healthy nodes / configured nodes',
      icon: 'nodes',
      trend: dashboard.total_nodes === 0 ? 'No nodes registered' : 'Current count',
      trendTone: dashboard.total_nodes === 0 ? 'neutral' : 'green',
    },
    {
      label: 'Cache hit rate',
      value: dashboard.cache_hit_rate == null ? '—' : `${dashboard.cache_hit_rate.toFixed(1)}%`,
      detail: dashboard.cache_available === true
        ? `Redis metadata cache · ${dashboard.cache_hits ?? 0} hits`
        : dashboard.cache_available === false
          ? 'Redis unavailable · catalog fallback active'
          : 'Waiting for cache health report',
      icon: 'cache',
      trend: dashboard.cache_available === false
        ? 'Fallback active'
        : dashboard.cache_hit_rate == null ? 'No cache hits yet' : 'Current metric',
      trendTone: dashboard.cache_available === false ? 'amber' : 'neutral',
    },
  ];
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
