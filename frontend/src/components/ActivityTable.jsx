import { ArrowUpRight } from 'lucide-react';
import StatusBadge from './StatusBadge.jsx';

export default function ActivityTable({ activities, compact = false, emptyMessage, emptyDescription }) {
  if (activities.length === 0) {
    return (
      <div className="empty-state compact-empty">
        <p>{emptyMessage || 'No activity events are available.'}</p>
        <span>{emptyDescription || 'The API returned an empty event list.'}</span>
      </div>
    );
  }

  return (
    <div className={`table-wrap${compact ? ' table-wrap-compact' : ''}`}>
      <table className="data-table activity-table">
        <thead>
          <tr>
            <th scope="col">Event</th>
            <th scope="col">Logical clock</th>
            <th scope="col">Time</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {activities.map((activity, index) => (
            <tr key={`${activity.time}-${index}`}>
              <td>
                <div className="table-main">{activity.event}</div>
                <div className="table-sub">{activity.description}</div>
              </td>
              <td>
                {activity.logical_clock == null
                  ? <span className="table-muted">Not available</span>
                  : <span className="clock-value">L: {activity.logical_clock}{activity.node_id ? ` · ${activity.node_id}` : ''}</span>}
              </td>
              <td className="time-value">{formatTimestamp(activity.timestamp)}</td>
              <td><StatusBadge tone={statusTone(activity.status)}>{activity.status}</StatusBadge></td>
            </tr>
          ))}
        </tbody>
      </table>
      {compact && <span className="table-end-icon"><ArrowUpRight size={14} /></span>}
    </div>
  );
}

function formatTimestamp(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function statusTone(status) {
  if (status === 'success') return 'green';
  if (status === 'warning') return 'amber';
  if (status === 'error') return 'red';
  return 'blue';
}
