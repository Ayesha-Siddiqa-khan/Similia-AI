# Similia AI frontend

Next.js App Router workspace for PDF books, ingestion monitoring, chunk inspection
and retrieval testing. See [the Phase 3 implementation report](../docs/frontend-phase3.md)
for API contracts, configuration, file inventory, verification and limitations.

```powershell
npm run dev -- --hostname 127.0.0.1
```

Open http://127.0.0.1:3000/preview/dashboard for clearly labeled synthetic fixtures.
Live pages require public Supabase configuration in `.env.local` (see `.env.example`)
and a verified account with trusted `app_metadata.similia_role` set to `operator`
or `admin`. Never put service-role, secret or AI API keys in frontend configuration.

```powershell
npm test
npm run typecheck
npm run lint
npm run build
```

The FastAPI backend runs separately on port 8000. No embedding operation starts
on page load. The existing provider quota stop remains in effect.
