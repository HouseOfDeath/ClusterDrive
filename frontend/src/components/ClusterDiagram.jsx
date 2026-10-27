import { ArrowRight, HardDrive, Network } from 'lucide-react';
import StatusBadge from './StatusBadge.jsx';

export default function ClusterDiagram({ nodes }) {
  return (
    <section className="panel cluster-panel" aria-labelledby="cluster-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">TOPOLOGY</p>
          <h2 id="cluster-title">Storage cluster</h2>
        </div>
        <span className="inline-meta"><Network size={15} /> {nodes.length} nodes</span>
      </div>
      <div className="cluster-flow">
        <div className="cluster-origin">
          <span className="origin-icon"><Network size={18} /></span>
          <span>ClusterDrive</span>
        </div>
        <div className="cluster-connector" aria-hidden="true"><ArrowRight size={16} /></div>
        {nodes.length > 0 ? (
          <div className="cluster-nodes">
            {nodes.map((node) => {
              const tone = node.status === 'healthy' ? 'green' : 'red';
              return (
                <div className="cluster-node" key={node.id}>
                  <span className={`node-icon node-icon-${tone}`}>
                    <HardDrive size={17} aria-hidden="true" />
                  </span>
                  <span className="cluster-node-name">{node.name}</span>
                  <StatusBadge tone={tone}>{node.status}</StatusBadge>
                  <span className="cluster-node-space">{formatBytes(node.storage_used_bytes)} used</span>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="cluster-empty-state">
            <HardDrive size={20} />
            <span>No storage nodes are configured.</span>
          </div>
        )}
      </div>
      <p className="panel-footnote">Node list supplied by the ClusterDrive API.</p>
    </section>
  );
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
