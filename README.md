# Document Manager SaaS Prototype

This repository contains a prototype web application for document control. It is designed as a Software‑as‑a‑Service (SaaS) style platform that allows multiple organisations to manage projects, upload documents with revision histories, and share documents via transmittals.  The application is built with **FastAPI** and uses SQLite for data storage.  It demonstrates core document management features in a multi‑organisation context without relying on any proprietary systems.

## Features

* **User authentication**: Users log in with an email and password.  Sessions are stored in the database and managed via a cookie.  Roles include superadministrator, organisation administrator and regular user.
* **Multi‑organisation support**: Each organisation has its own set of projects, users and document register.  Superadministrators can manage organisations and users across the entire system.
* **Document register with revision history**: Documents are identified by a number and can have multiple revisions.  Each revision stores metadata (title, type, status), the file path and who uploaded it.  The current revision is tracked automatically.
* **Transmittals**: Organisations can send one or more document revisions to another organisation using a transmittal.  Recipients receive a copy of the revisions in their register and can view and download them.  Transmittals record the sender, recipient and included revisions.
* **Role‑based access control**: Access to routes is controlled by role.  Organisation administrators manage projects and users within their organisation, while superadministrators manage all organisations.  Regular users can view and upload documents within their own organisation.
* **Event log**: Each document keeps a record of events such as uploads, downloads and transmittal sends/receives.  Events include the user, timestamp and a description of the action.

## Running locally

To run the application on your local machine, you need Python 3.11 or later.  Install the dependencies listed in `requirements.txt` and start the server with Uvicorn:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn document_manager.main:app --reload
```

Navigate to `http://127.0.0.1:8000` in your browser to access the app.  A default superadmin account is created on startup (email: `admin@example.com`, password: `admin`), which you can use to log in and set up your own organisations and users.

## Deployment to Vercel or DigitalOcean

The repository includes a `vercel.json` file and an `api/index.py` entrypoint for deploying to Vercel.  When you import this project into Vercel, select **Other** as the framework preset and set the root directory to the root of the repository.  Vercel will install the dependencies and expose the FastAPI application as a serverless function.

For DigitalOcean, you can deploy the application on an App Platform or Droplet by running Uvicorn and ensuring persistent storage for the database and uploads.  Consider switching to a managed database (e.g. PostgreSQL) and object storage (e.g. Spaces) for production use.

## License

This project is licensed under the MIT license.  See the `LICENSE` file for details.