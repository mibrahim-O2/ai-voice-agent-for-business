// Static, public configuration. NEVER put an API key or any secret here: this file is published.
// The dashboard only reads the recorded demo snapshot; it never calls OpenAI or the backend.
window.DASHBOARD_CONFIG = Object.freeze({
  mode: "demo",
  snapshotUrl: "demo/snapshot.json",
});
