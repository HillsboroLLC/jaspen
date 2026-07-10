# JASPEN Platform

Jaspen — a thought partner for prioritization and decision-making.

- **Local development:** see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
  Quick start: `./scripts/dev_setup.sh`, then `./scripts/dev_backend.sh` and
  `cd frontend && npm start`.
- **Frontend:** React (CRA) in `frontend/` → Vercel (jaspen.ai)
- **Backend:** Flask in `backend/` → DigitalOcean (api.jaspen.ai)
- **Deploys:** GitHub Actions — push to `main` deploys production, `develop`
  deploys staging. Working locally never touches production.
