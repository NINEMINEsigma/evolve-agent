export const EXPORT_LIMITS = {
  snapshotBytes: 96 * 1024 * 1024,
  resourceBytes: 32 * 1024 * 1024,
  resourceTotalBytes: 128 * 1024 * 1024,
  resources: 1024,
  depth: 16,
  archiveInputBytes: 192 * 1024 * 1024,
  viewerBytes: 16 * 1024 * 1024,
  verifyBytes: 2 * 1024 * 1024,
  requestMs: 30_000,
  totalMs: 180_000,
  concurrency: 2,
  scriptBytes: 2 * 1024 * 1024,
  renderBatch: 50,
  downloadRevokeMs: 60_000,
} as const;
export const EXPORT_VIEWER_PREFIX = "/api/session-export/viewer";
export const EXPORT_DATA_ID = "session-export-data";
export const EXPORT_CSP = "default-src 'none'; script-src 'unsafe-inline' blob:; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data: blob:; connect-src 'none'; frame-src blob:; child-src blob:; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
export const EXPORT_FRAME_CSP = EXPORT_CSP.replace("frame-src blob:", "frame-src 'none'").replace("child-src blob:", "child-src 'none'");
