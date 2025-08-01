# Document Manager SaaS (Aconex‑like Prototype)

This repository contains a prototype web application inspired by Oracle Aconex for document control.  It is designed to run on FastAPI with no external dependencies beyond what is already available in the environment.  The application demonstrates basic document management and transmittal functionality in a multi‑organisation context.

## Features

* **Multi‑organisation support** – Each organisation has its own private document register.  Users belong to organisations and access only their own documents.
* **Projects** – Administrators can create projects under their organisation.  Documents are uploaded within projects.
* **Document register & revisions** – Upload documents with metadata and maintain revision history.  Previous versions are retained for reference.
* **Transmittals** – Send revisions of documents to other organisations.  Transmittals automatically create or supersede documents in the recipient’s register and record events.
* **Event log** – Each document keeps an audit trail (events) showing uploads, revisions, and transmittals.
* **Role‑based access** – Three roles are supported: `superadmin` (global administrator), `org_admin` (organisation administrator), and `user` (regular user).  Role determines which pages and operations are available.

## Running Locally

1. Ensure Python 3.11 is installed.  Clone this repository and change into its directory:

   ```bash
   git clone <repo-url>
   cd document_manager
   ```

2. Start the server using `uvicorn` (already included in this environment):

   ```bash
   python -m uvicorn document_manager.main:app --reload
   ```

3. Open your browser at `http://127.0.0.1:8000`.  On the first run the app will create a default super administrator with email `admin@example.com` and password `admin`.  Please log in using these credentials and immediately create your own organisations, users and projects.

4. When deploying to a cloud provider such as Vercel or DigitalOcean, ensure that the `uploads` directory and SQLite database (`database.db`) persist between restarts.  For production use you should replace the SQLite database with a managed service such as PostgreSQL and use object storage (e.g. DigitalOcean Spaces) for file uploads.

## Security Notice

This prototype is intended as a learning tool and is **not production ready**.  Passwords are hashed using salted SHA256 but there is no password reset functionality.  Session management uses plain session IDs stored in a database.  Additional hardening (HTTPS, CSRF protection, more robust authentication) is required before exposing this application to the public.

## License

This project is provided under the MIT License.  See `LICENSE` for details.
