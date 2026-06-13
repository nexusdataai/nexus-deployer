/**
 * Single source of truth for the local backend's base URL.
 *
 * The backend runs in-process with the Electron app on the loopback
 * interface and is served over HTTPS with a self-signed certificate
 * (see `backend/app/utils/local_tls.py`). Electron's main process pins
 * that cert via Chromium's `ignore-certificate-errors-spki-list` switch
 * so renderer fetches succeed without weakening TLS for any other host.
 *
 * Override with the `VITE_API_BASE_URL` environment variable when needed
 * (e.g. running the frontend dev server against a remote backend).
 */
export const API_BASE: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  (import.meta.env.VITE_API_URL as string | undefined) ??
  'https://127.0.0.1:8001';
