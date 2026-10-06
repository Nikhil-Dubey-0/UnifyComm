# UnifyComm frontend

Agent workspace and customer simulator for UnifyComm (Next.js 16 App Router, TypeScript,
Tailwind 4, shadcn/ui, TanStack Query). The FastAPI backend in `../backend` is the only
backend; this app has no API routes. `../ARCHITECTURE.md` is the contract.

## Run

```powershell
npm install
npm run dev            # http://localhost:3000 (needs the api on :8000 and the worker)
```

`.env.local` (not committed):

```
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
```

Sign in as `agent@unifycomm.local` with the seed password (`SEED_AGENT_PASSWORD`, default
`demo1234`).

## Checks

```powershell
npm run gen:api        # openapi.json -> src/lib/api/schema.d.ts (after backend schema changes)
npx tsc --noEmit
npm run lint
npm run build
npx playwright test    # smoke test in Microsoft Edge; starts or reuses api, worker and web
```

## Layout

- `src/app/(auth)/login`, `src/app/(workspace)/{inbox,customers,simulator}`
- `src/lib/api/client.ts`: typed `openapi-fetch` client and `call()` error unwrapping
- `src/lib/queries.ts`: query hooks and keys; `src/lib/ws.ts`: one socket per session whose
  events only invalidate queries
- `src/components/`: `ui/` (shadcn), `inbox/`, `conversation/`, `customers/`
