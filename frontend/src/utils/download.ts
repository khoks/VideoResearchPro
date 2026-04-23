// Trigger a browser file download for a URL.
//
// Creates a transient <a download="..."> element, clicks it, and cleans up.
// This avoids a full page navigation (which would drop the SPA state) and
// lets us suggest a filename to the browser even when the server doesn't
// set a Content-Disposition header.
//
// The URL is expected to already carry any required auth (e.g. a ?token=
// query param appended by the caller) since <a> navigations can't set the
// Authorization header.
export function downloadUrl(url: string, filename: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
