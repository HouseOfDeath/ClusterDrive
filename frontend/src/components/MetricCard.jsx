import { ArrowUpRight, Database, FileStack, HardDrive, Zap } from 'lucide-react';

const icons = {
  database: Database,
  files: FileStack,
  nodes: HardDrive,
  cache: Zap,
};

export default function MetricCard({ label, value, detail, icon, trend, trendTone = 'green' }) {
  const Icon = icons[icon] ?? Database;

  return (
    <article className="metric-card panel">
      <div className="metric-topline">
        <span className={`metric-icon metric-icon-${icon}`}>
          <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
        </span>
        <span className={`metric-trend metric-trend-${trendTone}`}>
          {trendTone === 'green' && <ArrowUpRight size={13} aria-hidden="true" />}
          {trend}
        </span>
      </div>
      <p className="metric-label">{label}</p>
      <p className="metric-value">{value}</p>
      <p className="metric-detail">{detail}</p>
    </article>
  );
}
