# SEHCS React frontend

This directory contains the only active browser UI for SEHCS.

## Development

Start Flask on port `5000`, then run:

```powershell
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies API requests to Flask.

## Production build

```powershell
npm run build
```

The Flask application serves the generated `dist/` directory, including the
React shell for client-side routes and the generated assets.