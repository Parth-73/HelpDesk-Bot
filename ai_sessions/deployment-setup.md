# Deployment setup — visible work record

11 November 2026. User request: host the complete existing website; user reported needing hosting setup help.

This records work in the actual session and is not a complete client-exported chat transcript. No credentials or hidden reasoning are included.

- Checked available hosting tools and runtime requirements. Worker/JavaScript hosting cannot run the existing FastAPI/ONNX/PostgreSQL backend unchanged.
- Render access, a production database URL, and a Gemini key were not configured. Owner account setup and private key entry remain required.
- Prepared a free Render Blueprint that hosts frontend/backend at one HTTPS origin and provisions a private PostgreSQL database, with the URL wired automatically. Documented that the free database expires after 30 days.
- Added a no-live-Gemini production image smoke workflow and an owner setup guide with the deployment link.
- The local Docker build ran out of VFS storage; the unchanged production Dockerfile then built successfully on a clean GitHub runner. Its real container/PostgreSQL checks passed.
- Verification run: https://github.com/Parth-73/HelpDesk-Bot/actions/runs/42978702000

No public hosting success or valid live Gemini key is claimed before the owner deploys in Render and the assigned public URL is checked.
