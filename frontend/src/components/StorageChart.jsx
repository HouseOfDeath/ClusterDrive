import { Database } from 'lucide-react';

export default function StorageChart({ dashboard }) {
  const used = dashboard.storage_used_bytes;
  const capacity = dashboard.storage_capacity_bytes;
  const percentage = capacity > 0 ? Math.min(100, (used / capacity) * 100) : 0;

  return (
    <section className="panel chart-panel" aria-labelledby="storage-chart-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">CAPACITY</p>
          <h2 id="storage-chart-title">Storage capacity</h2>
        </div>
        <span className="chart-period">Current API values</span>
      </div>
      <div className="chart-total">
        <strong>{formatBytes(used)}</strong>
        <span className="chart-total-caption">used</span>
      </div>
      <div className="capacity-summary">
        <span><Database size={15} /> Configured capacity</span>
        <strong>{capacity > 0 ? formatBytes(capacity) : 'Not configured'}</strong>
      </div>
      <div
        className="capacity-track overview-capacity-track"
        role={capacity > 0 ? 'meter' : undefined}
        aria-label={capacity > 0 ? 'Storage capacity used' : undefined}
        aria-valuemin={capacity > 0 ? 0 : undefined}
        aria-valuemax={capacity > 0 ? capacity : undefined}
        aria-valuenow={capacity > 0 ? used : undefined}
      >
        <span className="capacity-fill" style={{ width: `${percentage}%` }} />
      </div>
      <p className="chart-empty-note">
        {capacity > 0
          ? `${percentage.toFixed(1)}% of configured capacity is in use.`
          : 'No storage capacity has been configured by the backend yet.'}
      </p>
    </section>
  );
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
