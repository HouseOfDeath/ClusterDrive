export default function StatusBadge({ children, tone = 'neutral', dot = true }) {
  return (
    <span className={`status-badge status-${tone}`}>
      {dot && <span className="status-dot" aria-hidden="true" />}
      {children}
    </span>
  );
}
