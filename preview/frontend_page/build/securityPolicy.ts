export function securityPolicy(): string {
  return [
    "default-src 'self'", "script-src 'self' 'unsafe-inline' blob:",
    "style-src 'self' 'unsafe-inline'", "img-src 'self' data: blob:",
    "font-src 'self' data:", "media-src 'self' data: blob:",
    "worker-src 'self' blob:", "frame-src 'self' blob: data:",
    "connect-src 'self'", "object-src 'none'", "base-uri 'self'", "form-action 'none'",
  ].join("; ");
}
