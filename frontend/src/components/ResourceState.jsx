import { AlertCircle, LoaderCircle, RefreshCw } from 'lucide-react';

export function LoadingState({ label = 'Loading data from the API…' }) {
  return (
    <div className="resource-state resource-loading" role="status">
      <LoaderCircle size={19} className="loading-spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ error, onRetry }) {
  return (
    <div className="resource-state resource-error" role="alert">
      <AlertCircle size={19} aria-hidden="true" />
      <div>
        <strong>Could not load data</strong>
        <p>{error.message}</p>
        <button className="secondary-button" type="button" onClick={onRetry}>
          <RefreshCw size={14} /> Try again
        </button>
      </div>
    </div>
  );
}

export default function ResourceState({ loading, error, onRetry, children, label }) {
  if (loading) return <LoadingState label={label} />;
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  return children;
}
