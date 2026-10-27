import { useState } from 'react';
import { Menu } from 'lucide-react';
import ActivityLogsPage from './pages/ActivityLogsPage.jsx';
import AlgorithmsPage from './pages/AlgorithmsPage.jsx';
import FileManagerPage from './pages/FileManagerPage.jsx';
import OverviewPage from './pages/OverviewPage.jsx';
import RaftPage from './pages/RaftPage.jsx';
import ReplicationPage from './pages/ReplicationPage.jsx';
import StorageNodesPage from './pages/StorageNodesPage.jsx';
import ApiStatusBanner from './components/ApiStatusBanner.jsx';
import Sidebar from './components/Sidebar.jsx';
import { getHealth } from './api/client.js';
import useApiResource from './hooks/useApiResource.js';

const pageDetails = {
  overview: { title: 'Overview', section: 'WORKSPACE' },
  files: { title: 'File Manager', section: 'WORKSPACE' },
  nodes: { title: 'Storage Nodes', section: 'INFRASTRUCTURE' },
  replication: { title: 'Replication & Consistency', section: 'INFRASTRUCTURE' },
  algorithms: { title: 'Distributed Algorithms', section: 'SYSTEMS' },
  raft: { title: 'Raft Cluster', section: 'SYSTEMS' },
  activity: { title: 'Activity Logs', section: 'OBSERVABILITY' },
};

export default function App() {
  const [activePage, setActivePage] = useState('overview');
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const health = useApiResource(getHealth);
  const current = pageDetails[activePage] ?? pageDetails.overview;

  function navigateTo(page) {
    if (!pageDetails[page]) return;
    setActivePage(page);
    setIsMobileNavOpen(false);
  }

  function renderPage() {
    switch (activePage) {
      case 'files':
        return <FileManagerPage selectedFile={selectedFile} onSelectFile={setSelectedFile} onClearFile={() => setSelectedFile(null)} />;
      case 'nodes':
        return <StorageNodesPage />;
      case 'replication':
        return <ReplicationPage />;
      case 'algorithms':
        return <AlgorithmsPage />;
      case 'raft':
        return <RaftPage />;
      case 'activity':
        return <ActivityLogsPage />;
      default:
        return <OverviewPage onNavigate={navigateTo} />;
    }
  }

  return (
    <div className="app-shell">
      <Sidebar
        activePage={activePage}
        onNavigate={navigateTo}
        isOpen={isMobileNavOpen}
        onClose={() => setIsMobileNavOpen(false)}
        apiLoading={health.loading}
        apiError={health.error}
      />
      <main className="main-area">
        <header className="topbar">
          <button
            className="icon-button mobile-menu-button"
            type="button"
            aria-label="Open navigation"
            aria-expanded={isMobileNavOpen}
            onClick={() => setIsMobileNavOpen(true)}
          >
            <Menu size={19} />
          </button>
          <div className="breadcrumbs"><span>{current.section}</span><b>/</b><strong>{current.title}</strong></div>
          <div className="topbar-right">
            <span className={`connection-label${health.error ? ' connection-error' : ''}`}>
              <i /> {health.loading ? 'Connecting' : health.error ? 'API unavailable' : 'API connected'}
            </span>
            <span className="profile-avatar" aria-label="User profile">JD</span>
          </div>
        </header>
        <div className="content-area">
          <ApiStatusBanner loading={health.loading} error={health.error} onRetry={health.retry} />
          {renderPage()}
          <footer className="app-footer">
            <span>ClusterDrive <b>·</b> Local API foundation</span>
            <span>Unimplemented services report no data</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
