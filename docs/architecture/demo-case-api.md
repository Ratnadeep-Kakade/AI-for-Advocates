# Demo case API configuration

The case API is deliberately disabled unless the single-tenant demo identity is
explicitly configured. This is a hackathon demonstration mechanism, not user
authentication. Do not enable it in a production environment.

Add these environment variables to the existing `cicero-database` Modal Secret:

```text
CICERO_DEMO_MODE=true
CICERO_DEMO_USER_ID=347ee843-8cad-4063-a2ae-919648eaf093
CICERO_DEMO_ORGANIZATION_ID=8879a27d-a980-4b05-bccd-843c2d169f58
```

For local testing, put the same values in the backend `.env` file. Keep
`CICERO_DEMO_MODE=false` unless deliberately running the isolated demo setup.

Endpoints:

- `GET /api/cases`: cases in the configured organization for which the demo user
  has an explicit case membership.
- `GET /api/cases/{case_id}`: one case, only if it belongs to the configured
  organization and the demo user is a case member.
- `POST /api/cases`: create a case for the configured organization and add the
  demo user as its owner. Organization roles `owner`, `admin`, and `lawyer` may
  create cases.

The API returns HTTP 503 when demo mode or either UUID is missing, and also
refuses to enable the demo identity when `CICERO_ENVIRONMENT=production`.
