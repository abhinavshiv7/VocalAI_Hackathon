const express = require('express');

const app = express();

// Deliberately exposed: this controlled route has no authentication check.
app.get('/admin', (_req, res) => {
  res.json({ status: 'ok', users: ['admin', 'svc-account'], debug: true });
});

// Deliberately omits browser security headers for validation by SentinelLoop.
app.get('/api/status', (_req, res) => {
  res.json({ service: 'api-target', version: '1.0.0' });
});

// False-positive control: suspicious name, but an access control is present.
app.get('/api/debug', (req, res) => {
  if (req.headers['x-internal-token'] !== 'expected-value') {
    return res.status(403).json({ error: 'forbidden' });
  }
  return res.json({ debug: true });
});

app.get('/health', (_req, res) => res.json({ status: 'ok' }));

app.listen(3000, '0.0.0.0', () => {
  console.log('authorized fake target listening on 3000');
});

