// Trigger a browser file download for a URL.
//
// Creates a transient <a download="..."> element, clicks it, and cleans up.
// This avoids a full page navigation (which would drop the SPA state) and
// lets us suggest a filename to the browser even when the server doesn't
// set a Content-Disposition header.
//
// An <a> navigation cannot send the Authorization header, so an API file is
// fetched first and this is given its blob: URL (services/apiFiles.ts). Never
// pass a URL carrying the JWT: no HTTP route accepts `?token=` (T-8.8.1.5).
export function downloadUrl(url: string, filename: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
