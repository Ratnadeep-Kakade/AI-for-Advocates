Cicero Milestone 4.1 - Demo Data Bootstrap

Purpose
-------
Creates/reuses a synthetic demo user, organization, organization-owner
membership, demo case, and case-owner membership in the existing Cloud SQL
schema. It does not create or alter tables and does not weaken constraints.

Files
-----
scripts/bootstrap_demo_data.py

Run from the backend project root in Windows CMD
------------------------------------------------
uv run modal run scripts/bootstrap_demo_data.py

The script uses the existing Modal secret named cicero-database and runs the
remote function with the existing Modal function name fastapi_app so that the
current Workload Identity Federation attribute condition continues to match.

Synthetic identity
------------------
Firebase UID: demo-cicero-hackathon-user-v1
Email: demo.user@cicero.example
Organization: Cicero Demo Law Firm
Case: Zepto IPO Due Diligence

Safety
------
This is a one-off demo-data bootstrap, NOT an authentication mechanism. The
synthetic Firebase UID does not prove a user is authenticated. Do not expose
this identity as a production login or use this script as a substitute for
Firebase/Auth token verification. The script is idempotent for its fixed seed
identifiers and refuses to silently reuse the demo email if it belongs to a
record with a different Firebase UID.
