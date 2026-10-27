import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App.jsx';

const dashboard = {
  storage_used_bytes: 0,
  storage_capacity_bytes: 0,
  total_files: 0,
  active_nodes: 0,
  total_nodes: 0,
  cache_hit_rate: null,
  features: {
    file_upload: { status: 'implemented', message: 'File upload is implemented.' },
    upload_availability: { status: 'implemented', message: 'A node is available.' },
    distributed_storage: { status: 'implemented', message: 'Storage nodes are implemented.' },
    replication: { status: 'implemented', message: 'Replication is implemented.' },
    raft: { status: 'implemented', message: 'Raft metadata cluster is implemented.' },
    redis_cache: { status: 'not_implemented', message: 'Redis is not implemented.' },
    lamport_clocks: { status: 'implemented', message: 'Lamport clocks are implemented.' },
    distributed_locking: { status: 'implemented', message: 'Distributed locking is implemented.' },
    deadlock_detection: { status: 'implemented', message: 'Deadlock detection is implemented.' },
    load_balancing: { status: 'implemented', message: 'Load balancing is implemented.' },
    checksum_verification: { status: 'implemented', message: 'Checksums are implemented.' },
  },
};

let files = [];
let replicationDemo = null;

const raftStatus = {
  node_count: 3,
  reachable_nodes: 3,
  quorum_required: 2,
  quorum_available: true,
  leader_id: 'metadata-01',
  implementation: 'educational-raft',
  nodes: ['metadata-01', 'metadata-02', 'metadata-03'].map((node_id, index) => ({
    node_id,
    address: `127.0.0.1:${50161 + index}`,
    reachable: true,
    role: index === 0 ? 'leader' : 'follower',
    term: 3,
    leader_id: 'metadata-01',
    commit_index: 1,
    last_applied: 1,
    last_log_index: 1,
    last_log_term: 3,
    heartbeat_age_ms: 15,
    heartbeat_state: index === 0 ? 'leader' : 'recent',
    recent_entries: [],
    error: null,
  })),
  recent_entries: [{
    index: 1,
    term: 3,
    command: {
      operation_id: 'raft-entry-1',
      kind: 'activity_append',
      event: { event: 'Raft cluster started' },
    },
    committed: true,
  }],
};

function installApiMock({ fail = false } = {}) {
  vi.stubGlobal('fetch', vi.fn(async (input, init = {}) => {
    if (fail) throw new TypeError('Network unavailable');

    const url = new URL(input);
    if (url.pathname === '/api/files' && init.method === 'POST') {
      const file = init.body.get('file');
      const uploaded = {
        id: 'uploaded-file',
        name: file.name,
        size_bytes: file.size,
        content_type: file.type,
        created_at: '2026-10-26T10:00:00Z',
        replica_count: 2,
        chunk_count: 1,
        replication_degraded: false,
        replication_status: 'synchronized',
      };
      files.push(uploaded);
      return new Response(JSON.stringify(uploaded), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.pathname === '/api/algorithms/deadlock-demo' && init.method === 'POST') {
      return new Response(JSON.stringify({
        execution_id: 'demo-1',
        cycle_detected: true,
        cycle: ['transaction-01', 'transaction-02', 'transaction-01'],
        victim: 'transaction-02',
        released_locks: ['lock-B'],
        graph_before: {
          'transaction-01': ['transaction-02'],
          'transaction-02': ['transaction-01'],
        },
        graph_after: { 'transaction-01': [] },
        lock_owners: { 'lock-A': 'transaction-01', 'lock-B': 'transaction-01' },
        victim_policy: 'Abort the youngest active transaction in the detected cycle.',
        logical_clock: 8,
        node_id: 'metadata-01',
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.pathname === '/api/replication/demo' && init.method === 'POST') {
      replicationDemo = {
        status: 'pending',
        chunk_id: 'demo-chunk',
        version: 1,
        source_node: 'node-01',
        target_node: 'node-02',
        source_status: 'synchronized',
        target_status: 'pending',
        source_version: 1,
        target_version: 0,
        error: null,
      };
      return new Response(JSON.stringify(replicationDemo), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.pathname === '/api/replication/demo/converge' && init.method === 'POST') {
      replicationDemo = { ...replicationDemo, status: 'synchronized', target_status: 'synchronized', target_version: 1 };
      return new Response(JSON.stringify(replicationDemo), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.pathname.endsWith('/download')) {
      return new Response('downloaded test content', {
        status: 200,
        headers: { 'Content-Type': 'application/octet-stream' },
      });
    }
    if (url.pathname.startsWith('/api/files/') && init.method === 'DELETE') {
      const fileId = url.pathname.split('/').pop();
      const [deleted] = files.filter((file) => file.id === fileId);
      files = files.filter((file) => file.id !== fileId);
      return new Response(JSON.stringify(deleted), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    const payloads = {
      '/health': { status: 'ok', service: 'clusterdive-api', version: '0.2.0' },
      '/api/dashboard': dashboard,
      '/api/files': { items: files, count: files.length },
      '/api/nodes': { items: [], count: 0, active_count: 0 },
      '/api/logs': { items: [], count: 0 },
      '/api/raft/status': raftStatus,
      '/api/algorithms/status': {
        nodes: [
          { node_id: 'metadata-01', logical_clock: 0, requesting: [], in_critical_section: [], deferred_requests: 0 },
          { node_id: 'metadata-02', logical_clock: 0, requesting: [], in_critical_section: [], deferred_requests: 0 },
          { node_id: 'metadata-03', logical_clock: 0, requesting: [], in_critical_section: [], deferred_requests: 0 },
        ],
        critical_section_entries: {},
        recent_protocol_events: [],
        last_deadlock_demo: null,
      },
      '/api/replication/status': {
        target_replicas: 2,
        pending: 0,
        synchronized: 0,
        failed: 0,
        files: [],
        demo: replicationDemo,
      },
      '/api/metrics': {
        cache_hits: 2,
        cache_misses: 3,
        cache_errors: 0,
        cache_hit_rate: 40,
        cache_available: true,
        cache_ttl_seconds: 60,
        placement_strategy: 'health-checked round-robin',
        placement_counts: { 'node-01': 0, 'node-02': 0 },
        request_counts: {
          'node-01': { upload: 0, replication: 0, download: 0, delete: 0 },
          'node-02': { upload: 0, replication: 0, download: 0, delete: 0 },
        },
        active_nodes: 2,
        total_nodes: 2,
      },
    };
    return new Response(JSON.stringify(payloads[url.pathname]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }));
}

function getNavigationButton(label) {
  const navigation = within(screen.getByRole('navigation', { name: 'Workspace pages' }));
  return navigation.getByRole('button', { name: new RegExp(label) });
}

beforeEach(() => {
  files = [];
  replicationDemo = null;
  installApiMock();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ClusterDrive API-connected dashboard', () => {
  it('shows backend-provided empty state rather than sample statistics', async () => {
    render(<App />);

    expect(await screen.findByText('Counts reflect backend state. Unimplemented features are identified explicitly.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument();
    expect(screen.getByText('0 B', { selector: '.metric-value' })).toBeInTheDocument();
    expect(screen.getByText('No storage nodes are registered in the backend.')).toBeInTheDocument();
    expect(screen.getByText('No activity events are available.')).toBeInTheDocument();
    expect(screen.queryByText('DEMO DATA')).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/dashboard',
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('navigates to API-backed node, Raft, replication, and algorithm pages', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(getNavigationButton('Storage Nodes'));
    expect(await screen.findByText('No storage nodes registered')).toBeInTheDocument();

    await user.click(getNavigationButton('Raft Cluster'));
    expect(await screen.findByRole('heading', { name: 'Metadata nodes' })).toBeInTheDocument();
    expect(screen.getAllByText('metadata-01').length).toBeGreaterThan(0);
    expect(screen.getByText('Raft cluster started')).toBeInTheDocument();
    expect(screen.getByText('Committed')).toBeInTheDocument();

    await user.click(getNavigationButton('Replication & Consistency'));
    expect(await screen.findByText('No file replica records')).toBeInTheDocument();

    await user.click(getNavigationButton('Distributed Algorithms'));
    expect(await screen.findByRole('heading', { name: 'Lamport logical clocks' })).toBeInTheDocument();
    expect(screen.getAllByText('Implemented')).toHaveLength(4);
    expect(await screen.findByText('metadata-01')).toBeInTheDocument();
    expect(screen.getAllByText('L: 0')).toHaveLength(3);
  });

  it('shows real cache and round-robin metrics and runs replica convergence demo', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(getNavigationButton('Replication & Consistency'));
    expect(await screen.findByText('Round-robin placement and request counts')).toBeInTheDocument();
    expect(screen.getByText('40.0%')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create replica lag' }));
    expect(await screen.findByText('Pending')).toBeInTheDocument();
    expect(screen.getByText('node-02 · v0')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Converge replicas' }));
    expect(await screen.findByText('Synchronized')).toBeInTheDocument();
    expect(screen.getByText('node-02 · v1')).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/replication/demo',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/replication/demo/converge',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('runs and displays the deterministic deadlock recovery demo', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(getNavigationButton('Distributed Algorithms'));
    await screen.findByText('metadata-01');
    await user.click(screen.getByRole('button', { name: 'Run controlled deadlock demo' }));

    expect(await screen.findByText('Cycle recovered')).toBeInTheDocument();
    expect(screen.getByText(/transaction-01 → transaction-02 → transaction-01/)).toBeInTheDocument();
    expect(screen.getByText('Aborted victim:')).toHaveTextContent('transaction-02');
    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/algorithms/deadlock-demo',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('searches and filters file records returned by the API', async () => {
    files = [
      { id: 'file-1', name: 'architecture-sketch.png', size_bytes: 2100, content_type: 'image/png', created_at: null, replica_count: 0 },
      { id: 'file-2', name: 'semester-data.csv', size_bytes: 860, content_type: 'text/csv', created_at: null, replica_count: 0 },
    ];
    installApiMock();
    const user = userEvent.setup();
    render(<App />);

    await user.click(getNavigationButton('File Manager'));
    expect(await screen.findByText('architecture-sketch.png')).toBeInTheDocument();

    const search = screen.getByRole('searchbox', { name: 'Search files' });
    await user.type(search, 'architecture');
    expect(screen.getByText('architecture-sketch.png')).toBeInTheDocument();
    expect(screen.queryByText('semester-data.csv')).not.toBeInTheDocument();

    await user.clear(search);
    await user.click(screen.getByRole('button', { name: 'Documents' }));
    expect(screen.getByText('semester-data.csv')).toBeInTheDocument();
    expect(screen.queryByText('architecture-sketch.png')).not.toBeInTheDocument();
  });

  it('previews a selected local file and uploads it through the API', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(getNavigationButton('File Manager'));
    await user.click(screen.getByRole('button', { name: 'Choose file' }));
    const input = screen.getByLabelText('Choose a file from this device');
    const file = new File(['hello'], 'notes.txt', { type: 'text/plain' });
    fireEvent.change(input, { target: { files: [file] } });

    expect(screen.getByText('notes.txt')).toBeInTheDocument();
    expect(screen.getByText('Not uploaded')).toBeInTheDocument();
    const uploadButton = screen.getByRole('button', { name: 'Upload to cluster' });
    expect(uploadButton).toBeEnabled();
    await user.click(uploadButton);
    expect(await screen.findByText('notes.txt uploaded; 2 synchronized copies.')).toBeInTheDocument();
    expect(screen.getByText('notes.txt')).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/files',
      expect.objectContaining({ method: 'POST', body: expect.any(FormData) }),
    );
  });

  it('asks for confirmation and deletes a file through the API', async () => {
    files = [{
      id: 'delete-this',
      name: 'remove.txt',
      size_bytes: 12,
      content_type: 'text/plain',
      created_at: null,
      replica_count: 2,
      chunk_count: 1,
      replication_degraded: false,
    }];
    installApiMock();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const user = userEvent.setup();
    render(<App />);

    await user.click(getNavigationButton('File Manager'));
    expect(await screen.findByText('remove.txt')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Delete remove.txt' }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('remove.txt'));
    expect(await screen.findByText('remove.txt and its replicas were deleted.')).toBeInTheDocument();
    expect(screen.queryByText('remove.txt')).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/files/delete-this',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });
  it('shows a retryable error instead of substituting mock data when the API is unavailable', async () => {
    installApiMock({ fail: true });
    render(<App />);

    expect(await screen.findByText('Could not load data')).toBeInTheDocument();
    expect(screen.getAllByText(/Cannot reach the ClusterDrive API/).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('button', { name: 'Try again' }).length).toBeGreaterThan(0);
  });

  it('shows an empty state in activity logs when the API returns no events', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(getNavigationButton('Activity Logs'));
    expect(await screen.findByText('The API currently has no activity events.')).toBeInTheDocument();
  });

  it('renders a loading state while an API response is pending', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    render(<App />);

    expect(screen.getByText('Connecting to the ClusterDrive API…')).toBeInTheDocument();
  });
});
