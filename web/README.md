# BLACKBOX web interface

Start the application with `serve_application(store, auth, host, port)` from `blackbox.application`. It serves `/` and `/index.html`, authenticated `GET /incidents/{incident_id}`, and authenticated `POST /incidents/{incident_id}/actions`.

The server requires explicit users and a signing secret. Missing or invalid tokens return `401`; authenticated users without the required role return `403`; malformed request bodies return `400`; unknown routes return `404`.

The browser view renders returned data with text-only DOM APIs. It is a minimal authenticated incident view, not a complete administrative dashboard. The API proposes sensitive actions and records approvals; it does not execute infrastructure changes.
