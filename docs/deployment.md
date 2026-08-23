# Deployment

The published dashboard image derives its API URL from the browser address. If
you open `http://YOUR_VM_IP:3000`, it calls `http://YOUR_VM_IP:8000`; no
frontend rebuild is required. Ensure the VM firewall permits TCP 3000 and 8000.

For a production DNS name or a separately hosted API, pin both origins before
building the stack:

```env
NEXT_PUBLIC_API_URL=http://YOUR_VM_IP:8000
FRONTEND_ORIGIN=http://YOUR_VM_IP:3000
```

Then rebuild the frontend image:

```bash
docker compose up --build -d frontend backend
```

`NEXT_PUBLIC_API_URL` must be reachable from the browser. `localhost` only
works when the dashboard and browser are running on the same machine. Set
`FRONTEND_ORIGIN` to restrict API CORS to the dashboard's public origin; it may
contain comma-separated origins.

## Deploy published GHCR images

Images are published from `main` and can be deployed without building on the
VM:

```bash
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```
