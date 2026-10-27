import { useCallback, useMemo, useRef, useState } from 'react';
import { Download, FileText, FolderOpen, Search, Trash2, Upload, X } from 'lucide-react';
import { deleteFile, downloadFile, getFiles, uploadFile } from '../api/client.js';
import PageHeader from '../components/PageHeader.jsx';
import ResourceState from '../components/ResourceState.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import useApiResource from '../hooks/useApiResource.js';

const filters = ['All files', 'Documents', 'Images', 'Media'];

function matchesFilter(file, filter) {
  const extension = file.name.split('.').pop()?.toUpperCase();
  if (filter === 'Documents') return ['PDF', 'CSV', 'TXT', 'DOC', 'DOCX'].includes(extension);
  if (filter === 'Images') return ['PNG', 'JPG', 'JPEG', 'GIF', 'SVG'].includes(extension);
  if (filter === 'Media') return ['MP4', 'WAV', 'MP3', 'MOV'].includes(extension);
  return true;
}

export default function FileManagerPage({ selectedFile, onSelectFile, onClearFile }) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('All files');
  const [isUploading, setIsUploading] = useState(false);
  const [activeFileId, setActiveFileId] = useState(null);
  const [operationError, setOperationError] = useState(null);
  const [notice, setNotice] = useState(null);
  const inputRef = useRef(null);
  const loadFiles = useCallback(getFiles, []);
  const resource = useApiResource(loadFiles);
  const files = resource.data?.items ?? [];
  const filteredFiles = useMemo(() => files.filter((file) => (
    file.name.toLowerCase().includes(query.trim().toLowerCase()) &&
    matchesFilter(file, filter)
  )), [files, query, filter]);

  function handleFileChange(event) {
    const [file] = event.target.files ?? [];
    if (file) {
      onSelectFile(file);
      setOperationError(null);
      setNotice(null);
    }
    event.target.value = '';
  }

  async function handleUpload() {
    if (!selectedFile) return;
    setIsUploading(true);
    setOperationError(null);
    setNotice(null);
    try {
      const uploaded = await uploadFile(selectedFile);
      onClearFile();
      const copies = uploaded.replica_count === 1 ? 'copy' : 'copies';
      const message = `${uploaded.name} uploaded; ${uploaded.replica_count} synchronized ${copies}.`;
      setNotice(uploaded.replication_status === 'pending'
        ? `${message} Additional replica copies are syncing asynchronously.`
        : uploaded.replication_status === 'failed'
          ? `${message} One or more replicas failed to synchronize. Check Replication & Consistency.`
          : message);
      resource.retry();
    } catch (error) {
      setOperationError(error.message);
    } finally {
      setIsUploading(false);
    }
  }

  async function handleDownload(file) {
    setActiveFileId(file.id);
    setOperationError(null);
    try {
      const blob = await downloadFile(file.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = file.name;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setNotice(`${file.name} downloaded.`);
    } catch (error) {
      setOperationError(error.message);
    } finally {
      setActiveFileId(null);
    }
  }

  async function handleDelete(file) {
    if (!window.confirm(`Delete "${file.name}" and its stored replicas? This cannot be undone.`)) return;
    setActiveFileId(file.id);
    setOperationError(null);
    setNotice(null);
    try {
      await deleteFile(file.id);
      setNotice(`${file.name} and its replicas were deleted.`);
      resource.retry();
    } catch (error) {
      setOperationError(error.message);
    } finally {
      setActiveFileId(null);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="YOUR STORAGE"
        title="File manager"
        description="Browse file records returned by the ClusterDrive API."
        action={
          <button className="primary-button" type="button" onClick={() => inputRef.current?.click()}>
            <Upload size={16} /> Choose file
          </button>
        }
      />
      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        aria-label="Choose a file from this device"
        onChange={handleFileChange}
      />
      {selectedFile && (
        <section className="selected-file-card panel" aria-live="polite">
          <span className="selected-file-icon"><FileText size={19} /></span>
          <span className="selected-file-info">
            <strong>{selectedFile.name}</strong>
            <small>{formatBytes(selectedFile.size)} · Selected on this device only</small>
          </span>
          <StatusBadge tone="amber">Not uploaded</StatusBadge>
          <button className="icon-button" type="button" aria-label="Remove selected file" onClick={onClearFile}>
            <X size={17} />
          </button>
        </section>
      )}
      {operationError && <div className="file-operation-error" role="alert">{operationError}</div>}
      {notice && <div className="file-operation-success" role="status">{notice}</div>}
      <section className="panel file-manager-panel">
        <div className="file-toolbar">
          <div className="file-tabs" role="group" aria-label="Filter files by type">
            {filters.map((item) => (
              <button
                type="button"
                className={`file-tab${filter === item ? ' file-tab-active' : ''}`}
                key={item}
                aria-pressed={filter === item}
                onClick={() => setFilter(item)}
              >
                {item}
              </button>
            ))}
          </div>
          <label className="search-box">
            <Search size={16} aria-hidden="true" />
            <input
              type="search"
              placeholder="Search files"
              value={query}
              aria-label="Search files"
              onChange={(event) => setQuery(event.target.value)}
            />
            {query && (
              <button type="button" className="search-clear" aria-label="Clear search" onClick={() => setQuery('')}>
                <X size={14} />
              </button>
            )}
          </label>
        </div>
        <ResourceState loading={resource.loading} error={resource.error} onRetry={resource.retry} label="Loading file records from the API…">
          {filteredFiles.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table files-table">
                <thead>
                  <tr>
                    <th scope="col">Name</th>
                    <th scope="col">Size</th>
                    <th scope="col">Created</th>
                    <th scope="col">Replicas</th>
                    <th scope="col">Type</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredFiles.map((file) => (
                    <tr key={file.id}>
                      <td>
                        <div className="file-name-cell">
                          <span className={`file-type-icon file-icon-${getFileColor(file.name)}`}>{getExtension(file.name)}</span>
                          <span><span className="table-main">{file.name}</span><span className="table-sub">{file.id}</span></span>
                        </div>
                      </td>
                      <td className="table-muted">{formatBytes(file.size_bytes)}</td>
                      <td className="table-muted">{file.created_at ? formatTimestamp(file.created_at) : 'Not available'}</td>
                      <td>
                        <div className="file-replica-status">
                          <span className={`replica-count${file.replication_degraded ? ' replica-count-degraded' : ''}`}>
                            <span className="tiny-replica-dot" />
                            {file.replica_count} synchronized {file.replica_count === 1 ? 'copy' : 'copies'}
                          </span>
                          <StatusBadge tone={
                            file.replication_status === 'failed' ? 'red'
                              : file.replication_status === 'pending' ? 'amber' : 'green'
                          }>
                            {file.replication_status || 'synchronized'}
                          </StatusBadge>
                        </div>
                      </td>
                      <td className="table-muted">{file.content_type || 'Unknown'}</td>
                      <td>
                        <div className="file-row-actions">
                          <button
                            className="icon-button"
                            type="button"
                            aria-label={`Download ${file.name}`}
                            title="Download file"
                            disabled={activeFileId !== null}
                            onClick={() => handleDownload(file)}
                          >
                            <Download size={15} />
                          </button>
                          <button
                            className="icon-button file-delete-button"
                            type="button"
                            aria-label={`Delete ${file.name}`}
                            title="Delete file and all stored replicas"
                            disabled={activeFileId !== null}
                            onClick={() => handleDelete(file)}
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty-state">
              <span className="empty-state-icon"><FolderOpen size={22} /></span>
              <strong>{files.length === 0 ? 'No files stored yet' : 'No files match these filters'}</strong>
              <span>
                {files.length === 0
                  ? 'The API currently reports zero files. Upload requires at least one healthy storage node.'
                  : 'Try another search or choose a different file type.'}
              </span>
              {(query || filter !== 'All files') && (
                <button className="text-button" type="button" onClick={() => { setQuery(''); setFilter('All files'); }}>
                  Clear filters
                </button>
              )}
            </div>
          )}
          <div className="file-panel-footer">
            <span>Showing {filteredFiles.length} matching of {resource.data?.count ?? 0} API file records</span>
            <span>File bytes are stored by configured gRPC storage nodes.</span>
          </div>
        </ResourceState>
      </section>
      <section className="upload-info panel">
        <span className="upload-info-icon"><Upload size={18} /></span>
        <div>
          <strong>Local file preview</strong>
          <p>Choose a file and upload it to store checksummed chunks on healthy gRPC storage nodes.</p>
        </div>
        <button
          className="secondary-button"
          type="button"
          disabled={!selectedFile || isUploading}
          title={selectedFile ? 'Upload file chunks to healthy storage nodes' : 'Choose a file first'}
          onClick={handleUpload}
        >
          <Upload size={14} /> {isUploading ? 'Uploading…' : 'Upload to cluster'}
        </button>
      </section>
    </>
  );
}

function getExtension(name) {
  return name.split('.').pop()?.slice(0, 3).toUpperCase() || 'FILE';
}

function getFileColor(name) {
  const extension = name.split('.').pop()?.toLowerCase();
  if (['pdf', 'doc', 'docx'].includes(extension)) return 'violet';
  if (['mp4', 'wav', 'mp3', 'mov'].includes(extension)) return 'pink';
  if (['png', 'jpg', 'jpeg', 'gif', 'svg'].includes(extension)) return 'cyan';
  if (['csv', 'xls', 'xlsx'].includes(extension)) return 'green';
  return 'blue';
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function formatTimestamp(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
