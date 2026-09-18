# Learning Context frontend

React + TypeScript + Vite application for the redesigned knowledge space.

```powershell
cd frontend
npm install
npm run dev       # Vite on :5173, /api proxied to FastAPI :8000
npm run build     # writes app/web/static/app for the FastAPI entry
```

The production bundle is intentionally generated into `app/web/static/app` so the Python server can serve a reproducible local build. Runtime API requests stay under `/api/v1`; model keys never enter this bundle.
