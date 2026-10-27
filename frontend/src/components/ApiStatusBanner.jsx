import { AlertCircle, CheckCircle2, LoaderCircle, RefreshCw } from 'lucide-react';

export default function ApiStatusBanner({ loading, error, onRetry }) {
  if (loading) {
    return (
      <div className="api-banner api-banner-loading" role="status">
        <LoaderCircle size={15} className="loading-spinner" />
        <span>Connecting to the ClusterDrive API…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="api-banner api-banner-error" role="alert">
        <AlertCircle size={15} />
        <span><strong>API unavailable.</strong> {error.message}</span>
        <button className="api-banner-retry" type="button" onClick={onRetry} aria-label="Retry API connection">
          <RefreshCw size={14} /> Retry
        </button>
      </div>
    );
  }

  return (
    <div className="api-banner api-banner-connected" role="status">
      <CheckCircle2 size={15} />
      <span>
        <strong>API connected</strong>
        {' '}Counts reflect backend state. Unimplemented features are identified explicitly.
      </span>
    </div>
  );
}
