import {
  Activity,
  Boxes,
  ChartNoAxesCombined,
  Files,
  GitBranch,
  HardDrive,
  Layers3,
  Network,
  X,
} from 'lucide-react';

const navigation = [
  { id: 'overview', label: 'Overview', icon: ChartNoAxesCombined },
  { id: 'files', label: 'File Manager', icon: Files },
  { id: 'nodes', label: 'Storage Nodes', icon: HardDrive },
  { id: 'replication', label: 'Replication & Consistency', icon: Layers3 },
  { id: 'algorithms', label: 'Distributed Algorithms', icon: Boxes },
  { id: 'raft', label: 'Raft Cluster', icon: GitBranch },
  { id: 'activity', label: 'Activity Logs', icon: Activity },
];

export default function Sidebar({ activePage, onNavigate, isOpen, onClose, apiLoading, apiError }) {
  return (
    <>
      <button
        className={`sidebar-scrim${isOpen ? ' is-visible' : ''}`}
        type="button"
        aria-label="Close navigation"
        onClick={onClose}
        tabIndex={isOpen ? 0 : -1}
      />
      <aside className={`sidebar${isOpen ? ' sidebar-open' : ''}`} aria-label="Main navigation">
        <div className="brand">
          <span className="brand-mark"><Network size={20} strokeWidth={2.2} /></span>
          <span className="brand-name">cluster<span>drive</span></span>
          <button className="icon-button sidebar-close" type="button" aria-label="Close navigation" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <div className="workspace-switcher">
          <span className="workspace-avatar">CD</span>
          <span className="workspace-label">
            <strong>Local workspace</strong>
            <small>ClusterDrive API</small>
          </span>
          <span className="workspace-chevron" aria-hidden="true">⌄</span>
        </div>
        <p className="nav-section-label">WORKSPACE</p>
        <nav className="main-nav" aria-label="Workspace pages">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              className={`nav-item${activePage === id ? ' nav-item-active' : ''}`}
              key={id}
              type="button"
              aria-current={activePage === id ? 'page' : undefined}
              onClick={() => onNavigate(id)}
            >
              <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-status">
            <span className={`status-pulse${apiLoading ? '' : apiError ? ' status-pulse-error' : ' status-pulse-connected'}`} />
            <span>
              <strong>API connection</strong>
              <small>{apiLoading ? 'Connecting…' : apiError ? 'Unavailable' : 'Connected'}</small>
            </span>
          </div>
          <p className="sidebar-version">CLUSTERDRIVE <span>·</span> LOCAL API</p>
        </div>
      </aside>
    </>
  );
}
