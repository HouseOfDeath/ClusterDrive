import { useCallback, useState } from 'react';
import { Activity, GitCommitHorizontal, LockKeyhole, Network, SearchCheck, Shuffle } from 'lucide-react';
import { getAlgorithmStatus, getDashboard, runDeadlockDemo } from '../api/client.js';
import PageHeader from '../components/PageHeader.jsx';
import ResourceState from '../components/ResourceState.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import useApiResource from '../hooks/useApiResource.js';

const algorithms = [
  {
    key: 'lamport_clocks',
    icon: Activity,
    title: 'Lamport logical clocks',
    short: 'Order events across services',
    description: 'Each metadata node increments its own counter and merges received message timestamps. The counter describes logical order, not wall-clock time.',
  },
  {
    key: 'distributed_locking',
    icon: LockKeyhole,
    title: 'Distributed mutual exclusion',
    short: 'Coordinate access to shared work',
    description: 'Ricart–Agrawala requests permission from every peer before a metadata write. Equal timestamps are ordered by metadata node ID.',
  },
  {
    key: 'deadlock_detection',
    icon: SearchCheck,
    title: 'Deadlock detection',
    short: 'Find circular waiting',
    description: 'The controlled scenario creates two transactions holding one lock each and waiting for the other lock.',
  },
  {
    key: 'load_balancing',
    icon: Shuffle,
    title: 'Load balancing',
    short: 'Select a healthy storage node',
    description: 'Chunk placement rotates across the healthy storage nodes.',
  },
];

export default function AlgorithmsPage() {
  const [demoResult, setDemoResult] = useState(null);
  const [demoError, setDemoError] = useState(null);
  const [demoLoading, setDemoLoading] = useState(false);
  const loadDashboard = useCallback(getDashboard, []);
  const loadStatus = useCallback(getAlgorithmStatus, []);
  const dashboard = useApiResource(loadDashboard);
  const status = useApiResource(loadStatus);

  async function runDemo() {
    setDemoLoading(true);
    setDemoError(null);
    try {
      const result = await runDeadlockDemo();
      setDemoResult(result);
      status.retry();
    } catch (error) {
      setDemoError(error.message);
    } finally {
      setDemoLoading(false);
    }
  }

  const latestDemo = demoResult || status.data?.last_deadlock_demo;

  return (
    <>
      <PageHeader
        eyebrow="DISTRIBUTED SYSTEMS"
        title="Distributed algorithms"
        description="Live Lamport clocks and Ricart–Agrawala protocol state from the metadata-node simulation."
        action={<StatusBadge tone="blue">Algorithm telemetry</StatusBadge>}
      />
      <div className="algorithm-notice">
        <span className="notice-icon"><GitCommitHorizontal size={17} /></span>
        <p><strong>Educational metadata cluster.</strong> Three logical metadata nodes exchange protocol messages in this API process. File metadata writes enter the mutual-exclusion protocol before updating the catalog.</p>
      </div>
      <ResourceState loading={dashboard.loading} error={dashboard.error} onRetry={dashboard.retry} label="Loading algorithm status…">
        {dashboard.data && (
          <section className="algorithm-grid">
            {algorithms.map(({ key, icon: Icon, title, short, description }) => {
              const feature = dashboard.data.features[key];
              const implemented = feature?.status === 'implemented';
              return (
                <article className="panel algorithm-card" key={key}>
                  <div className="algorithm-card-top">
                    <span className="algorithm-icon"><Icon size={19} /></span>
                    <StatusBadge tone={implemented ? 'green' : 'neutral'}>
                      {implemented ? 'Implemented' : 'Not implemented'}
                    </StatusBadge>
                  </div>
                  <p className="eyebrow">{short}</p>
                  <h2>{title}</h2>
                  <p className="algorithm-description">{description}</p>
                  <p className="feature-api-message">{feature?.message || 'The API has no implementation status for this feature.'}</p>
                  {key === 'deadlock_detection' && (
                    <button className="secondary-button algorithm-action" type="button" disabled={demoLoading} onClick={runDemo}>
                      <Network size={15} /> {demoLoading ? 'Running recovery…' : 'Run controlled deadlock demo'}
                    </button>
                  )}
                </article>
              );
            })}
          </section>
        )}
      </ResourceState>
      <section className="algorithm-runtime-grid">
        <article className="panel algorithm-runtime-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">LAMPORT CLOCKS</p><h2>Metadata-node counters</h2></div>
            <button className="secondary-button algorithm-action" type="button" onClick={status.retry}>Refresh</button>
          </div>
          <ResourceState loading={status.loading} error={status.error} onRetry={status.retry} label="Loading metadata-node clocks…">
            {status.data && (
              <div className="clock-node-list">
                {status.data.nodes.map((node) => (
                  <div className="clock-node-row" key={node.node_id}>
                    <span><i className="health-dot dot-green" />{node.node_id}</span>
                    <strong>L: {node.logical_clock}</strong>
                  </div>
                ))}
              </div>
            )}
          </ResourceState>
          {status.data && (
            <>
              <p className="algorithm-runtime-copy">Mutual-exclusion entries by resource</p>
              <div className="clock-node-list">
                {Object.entries(status.data.critical_section_entries).length === 0
                  ? <p className="algorithm-runtime-copy">No metadata write has entered a critical section in this process yet.</p>
                  : Object.entries(status.data.critical_section_entries).map(([resource, entries]) => (
                    <div className="clock-node-row" key={resource}><span>{resource}</span><strong>{entries}</strong></div>
                  ))}
              </div>
            </>
          )}
        </article>
        <article className="panel algorithm-runtime-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">PROTOCOL MESSAGES</p><h2>Recent coordination events</h2></div>
          </div>
          {status.data?.recent_protocol_events.length
            ? <ul className="protocol-event-list">
              {status.data.recent_protocol_events.slice(-8).reverse().map((event, index) => (
                <li key={`${event.node_id}-${event.logical_clock}-${index}`}>
                  <span>{event.event.replaceAll('_', ' ')}</span>
                  <small>{event.node_id} · L: {event.logical_clock} · {event.description}</small>
                </li>
              ))}
            </ul>
            : <p className="algorithm-runtime-copy">Protocol events will appear after a file metadata write requests the distributed critical section.</p>}
        </article>
      </section>
      <section className="panel deadlock-result-panel">
        <div className="panel-heading">
          <div><p className="eyebrow">DETERMINISTIC DEADLOCK RECOVERY</p><h2>Wait-for graph and outcome</h2></div>
          {latestDemo && <StatusBadge tone={latestDemo.cycle_detected ? 'amber' : 'green'}>{latestDemo.cycle_detected ? 'Cycle recovered' : 'No cycle'}</StatusBadge>}
        </div>
        {demoError && <p className="inline-error" role="alert">{demoError}</p>}
        {!latestDemo
          ? <p className="algorithm-runtime-copy">Run the demo to create a repeatable two-transaction cycle. It does not depend on thread timing.</p>
          : (
            <>
              <p className="deadlock-policy">Victim policy: {latestDemo.victim_policy}</p>
              <div className="deadlock-graphs">
                <GraphView title="Before recovery" graph={latestDemo.graph_before} />
                <GraphView title="After recovery" graph={latestDemo.graph_after} />
              </div>
              <div className="deadlock-outcome">
                <span>Cycle: <strong>{latestDemo.cycle.join(' → ') || 'None'}</strong></span>
                <span>Aborted victim: <strong>{latestDemo.victim || 'None'}</strong></span>
                <span>Released locks: <strong>{latestDemo.released_locks.join(', ') || 'None'}</strong></span>
                <span>Recovery event: <strong>{latestDemo.node_id} · L: {latestDemo.logical_clock}</strong></span>
              </div>
            </>
          )}
      </section>
      <section className="panel algorithm-glossary">
        <span className="glossary-icon"><Network size={18} /></span>
        <div>
          <p className="eyebrow">FILE-WRITE INTEGRATION</p>
          <h2>Permission first, then update metadata</h2>
          <p>Uploads and deletes request the file-write critical section from every logical metadata peer. Only after all permissions arrive does the API update the local catalog. The local catalog still is not replicated consensus storage, and the educational peer messages are in-process rather than network RPCs.</p>
        </div>
      </section>
    </>
  );
}

function GraphView({ title, graph }) {
  return (
    <div className="deadlock-graph">
      <h3>{title}</h3>
      {Object.entries(graph).map(([transaction, waitsFor]) => (
        <p key={transaction}>
          <strong>{transaction}</strong>
          <span>{waitsFor.length ? ` waits for ${waitsFor.join(', ')}` : ' has no waits'}</span>
        </p>
      ))}
    </div>
  );
}
