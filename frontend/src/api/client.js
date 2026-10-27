const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
).replace(/\/+$/, '');

async function request(path, { method = 'GET', body, signal, responseType = 'json' } = {}) {
  let response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: {
        Accept: responseType === 'blob' ? 'application/octet-stream' : 'application/json',
      },
      body,
      signal,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error(`Cannot reach the ClusterDrive API at ${API_BASE_URL}. Start the backend and try again.`);
  }

  let payload;
  try {
    payload = responseType === 'blob' && response.ok
      ? await response.blob()
      : await response.json();
  } catch {
    throw new Error(`The API returned an invalid response for ${path}.`);
  }

  if (!response.ok) {
    const detail = typeof payload.detail === 'string'
      ? payload.detail
      : `Request failed with status ${response.status}.`;
    throw new Error(detail);
  }

  return payload;
}

export const getHealth = ({ signal } = {}) => request('/health', { signal });
export const getDashboard = ({ signal } = {}) => request('/api/dashboard', { signal });
export const getFiles = ({ signal } = {}) => request('/api/files', { signal });
export const getNodes = ({ signal } = {}) => request('/api/nodes', { signal });
export const getLogs = ({ signal } = {}) => request('/api/logs', { signal });
export const getReplicationStatus = ({ signal } = {}) => request('/api/replication/status', { signal });
export const getClusterMetrics = ({ signal } = {}) => request('/api/metrics', { signal });
export const startReplicationDemo = ({ signal } = {}) => request(
  '/api/replication/demo',
  { method: 'POST', signal },
);
export const convergeReplicationDemo = ({ signal } = {}) => request(
  '/api/replication/demo/converge',
  { method: 'POST', signal },
);
export const getAlgorithmStatus = ({ signal } = {}) => request('/api/algorithms/status', { signal });
export const getRaftStatus = ({ signal } = {}) => request('/api/raft/status', { signal });
export const runDeadlockDemo = ({ signal } = {}) => request(
  '/api/algorithms/deadlock-demo',
  { method: 'POST', signal },
);
export const uploadFile = (file, { signal } = {}) => {
  const body = new FormData();
  body.append('file', file);
  return request('/api/files', { method: 'POST', body, signal });
};
export const downloadFile = (fileId, { signal } = {}) => request(
  `/api/files/${encodeURIComponent(fileId)}/download`,
  { responseType: 'blob', signal },
);
export const deleteFile = (fileId, { signal } = {}) => request(
  `/api/files/${encodeURIComponent(fileId)}`,
  { method: 'DELETE', signal },
);
