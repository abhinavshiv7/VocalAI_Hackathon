# Deployment

The dashboard's API URL is public client-side configuration, so it is embedded
when the frontend image is built. For a VM deployment, set both origins before
rebuilding the stack:

```env
NEXT_PUBLIC_API_URL=http://YOUR_VM_IP:8000
FRONTEND_ORIGIN=http://YOUR_VM_IP:3000
```

Then rebuild the frontend image:

```bash
docker compose up --build -d frontend backend
```

`NEXT_PUBLIC_API_URL` must be reachable from the browser. `localhost` only
works when the dashboard and browser are running on the same machine.
