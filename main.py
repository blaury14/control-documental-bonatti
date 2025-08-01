"""
Entry point of the document management SaaS application.

This FastAPI application implements a minimal but functional document control
system inspired by Oracle Aconex. It supports multiple organisations and
projects, document registers with revision history, transmittal of document
revisions between organisations, and basic role‑based access control.

Users authenticate via email and password. Sessions are stored in the
database and managed via a cookie. The app renders HTML pages using
Jinja2 templates. All routes beginning with "/" except the login/logout
are protected by authentication middleware which validates the session
cookie and populates the current_user context.

To run the application locally execute `uvicorn main:app --reload` from
within the `document_manager` directory. Uploaded files are stored under
the `uploads` directory relative to this script. When deploying to
Vercel or DigitalOcean ensure persistent storage is configured for
uploads and the SQLite database.
"""

import os
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import (
    FastAPI,
    Request,
    Form,
    UploadFile,
    File,
    HTTPException,
    Depends,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import database as db
import sqlite3  # needed for catching integrity errors


app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

# Ensure upload directory exists
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Mount static directory to serve CSS/JS
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Jinja2 templating engine
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.on_event("startup")
async def startup_event():
    """Initialisation tasks executed when the application starts."""
    db.init_db()
    # Ensure default admin exists
    db.create_default_superadmin()
    # Clean up expired sessions periodically
    db.cleanup_sessions()


def get_current_user(request: Request):
    """Retrieve the currently logged in user based on the session cookie.

    If the session is missing or expired, raises HTTPException to
    redirect to the login page.
    """
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    session = db.get_session(session_id)
    if not session:
        # invalid or expired session
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    # Check expiry
    expires_at = datetime.fromisoformat(session["expires_at"])
    if expires_at < datetime.utcnow():
        # Delete session and redirect
        db.delete_session(session_id)
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    user = db.get_user_by_id(session["user_id"])
    if not user:
        db.delete_session(session_id)
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    return user


def require_role(user, allowed: List[str]):
    """Ensure the user's role is in the allowed list or raise HTTPException 403."""
    if user["role"] not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Redirect to dashboard or login depending on session."""
    session_id = request.cookies.get("session_id")
    if session_id:
        session = db.get_session(session_id)
        if session:
            return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/login")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login_action(request: Request):
    # Parse form body manually (application/x-www-form-urlencoded)
    body = await request.body()
    from urllib.parse import parse_qs

    data = parse_qs(body.decode())
    email = data.get("email", [""])[0]
    password = data.get("password", [""])[0]
    user = db.get_user_by_email(email)
    if not user or not db.verify_password(user["password_hash"], password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Credenciales inválidas"},
        )
    # Create session
    session_id = db.create_session(user["id"])
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    # Set cookie (httponly for security)
    response.set_cookie(
        key="session_id", value=session_id, httponly=True, max_age=60 * 60 * 2
    )
    return response


@app.get("/logout")
async def logout(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id:
        db.delete_session(session_id)
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_id")
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user=Depends(get_current_user)):
    # Determine info to show based on role
    role = user["role"]
    context = {"request": request, "user": user}
    if role == "superadmin":
        orgs = db.get_organizations()
        context["organizations"] = orgs
    else:
        # For org admins and regular users show projects in their org
        projects = db.get_projects_by_org(user["org_id"])
        context["projects"] = projects
    return templates.TemplateResponse("dashboard.html", context)


@app.get("/organizations", response_class=HTMLResponse)
async def list_organizations(request: Request, user=Depends(get_current_user)):
    require_role(user, ["superadmin"])
    orgs = db.get_organizations()
    return templates.TemplateResponse(
        "organizations.html", {"request": request, "user": user, "organizations": orgs}
    )


@app.get("/organizations/new", response_class=HTMLResponse)
async def new_organization_form(request: Request, user=Depends(get_current_user)):
    require_role(user, ["superadmin"])
    return templates.TemplateResponse(
        "organization_form.html",
        {"request": request, "user": user, "error": None},
    )


@app.post("/organizations/new")
async def create_organization_action(request: Request, user=Depends(get_current_user)):
    require_role(user, ["superadmin"])
    body = await request.body()
    from urllib.parse import parse_qs
    data = parse_qs(body.decode())
    name = data.get("name", [""])[0]
    description = data.get("description", [""])[0]
    if not name:
        return templates.TemplateResponse(
            "organization_form.html",
            {
                "request": request,
                "user": user,
                "error": "Debe ingresar un nombre",
            },
        )
    try:
        org_id = db.create_organization(name, description)
    except sqlite3.IntegrityError:
        return templates.TemplateResponse(
            "organization_form.html",
            {
                "request": request,
                "user": user,
                "error": "Nombre de organización ya existe",
            },
        )
    return RedirectResponse("/organizations", status_code=status.HTTP_302_FOUND)


@app.get("/organizations/{org_id}/users", response_class=HTMLResponse)
async def list_users(org_id: int, request: Request, user=Depends(get_current_user)):
    # superadmin can view any; org_admin can view own org; others forbidden
    if user["role"] not in ["superadmin", "org_admin"]:
        raise HTTPException(status_code=403)
    if user["role"] == "org_admin" and user["org_id"] != org_id:
        raise HTTPException(status_code=403)
    org = db.get_organization(org_id)
    if not org:
        raise HTTPException(status_code=404)
    users = db.get_users_by_org(org_id)
    return templates.TemplateResponse(
        "users.html",
        {"request": request, "user": user, "org": org, "users": users},
    )


@app.get("/organizations/{org_id}/users/new", response_class=HTMLResponse)
async def new_user_form(org_id: int, request: Request, user=Depends(get_current_user)):
    if user["role"] == "superadmin" or (
        user["role"] == "org_admin" and user["org_id"] == org_id
    ):
        org = db.get_organization(org_id)
        if not org:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            "user_form.html",
            {"request": request, "user": user, "org": org, "error": None},
        )
    raise HTTPException(status_code=403)


@app.post("/organizations/{org_id}/users/new")
async def create_user_action(org_id: int, request: Request, user=Depends(get_current_user)):
    if user["role"] == "superadmin" or (
        user["role"] == "org_admin" and user["org_id"] == org_id
    ):
        body = await request.body()
        from urllib.parse import parse_qs

        data = parse_qs(body.decode())
        email = data.get("email", [""])[0]
        name_field = data.get("name", [""])[0]
        password = data.get("password", [""])[0]
        role_field = data.get("role", ["user"])[0]
        # Restrict roles: only superadmin can create org_admin
        if user["role"] == "org_admin" and role_field == "org_admin":
            raise HTTPException(status_code=403)
        if role_field not in ["org_admin", "user"]:
            role_field = "user"
        try:
            db.create_user(email, password, name_field, role_field, org_id)
        except Exception as e:
            return templates.TemplateResponse(
                "user_form.html",
                {
                    "request": request,
                    "user": user,
                    "org": db.get_organization(org_id),
                    "error": "No se pudo crear el usuario. Puede que el email ya exista.",
                },
            )
        return RedirectResponse(
            f"/organizations/{org_id}/users", status_code=status.HTTP_302_FOUND
        )
    raise HTTPException(status_code=403)


@app.get("/organizations/{org_id}/projects", response_class=HTMLResponse)
async def list_projects(org_id: int, request: Request, user=Depends(get_current_user)):
    # Only users belonging to the org or superadmin can view
    if user["role"] != "superadmin" and user["org_id"] != org_id:
        raise HTTPException(status_code=403)
    org = db.get_organization(org_id)
    if not org:
        raise HTTPException(status_code=404)
    projects = db.get_projects_by_org(org_id)
    return templates.TemplateResponse(
        "projects.html",
        {"request": request, "user": user, "org": org, "projects": projects},
    )


@app.get("/organizations/{org_id}/projects/new", response_class=HTMLResponse)
async def new_project_form(org_id: int, request: Request, user=Depends(get_current_user)):
    # Only org admins or superadmin can create
    if user["role"] not in ["superadmin", "org_admin"]:
        raise HTTPException(status_code=403)
    if user["role"] == "org_admin" and user["org_id"] != org_id:
        raise HTTPException(status_code=403)
    org = db.get_organization(org_id)
    if not org:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "project_form.html",
        {"request": request, "user": user, "org": org, "error": None},
    )


@app.post("/organizations/{org_id}/projects/new")
async def create_project_action(org_id: int, request: Request, user=Depends(get_current_user)):
    if user["role"] not in ["superadmin", "org_admin"]:
        raise HTTPException(status_code=403)
    if user["role"] == "org_admin" and user["org_id"] != org_id:
        raise HTTPException(status_code=403)
    body = await request.body()
    from urllib.parse import parse_qs
    data = parse_qs(body.decode())
    name_field = data.get("name", [""])[0]
    description_field = data.get("description", [""])[0]
    if not name_field:
        return templates.TemplateResponse(
            "project_form.html",
            {
                "request": request,
                "user": user,
                "org": db.get_organization(org_id),
                "error": "El nombre es obligatorio.",
            },
        )
    try:
        db.create_project(name_field, description_field, org_id)
    except Exception:
        return templates.TemplateResponse(
            "project_form.html",
            {
                "request": request,
                "user": user,
                "org": db.get_organization(org_id),
                "error": "No se pudo crear el proyecto. Verifique los datos.",
            },
        )
    return RedirectResponse(
        f"/organizations/{org_id}/projects", status_code=status.HTTP_302_FOUND
    )


@app.get(
    "/organizations/{org_id}/projects/{project_id}/documents",
    response_class=HTMLResponse,
)
async def list_documents(
    org_id: int,
    project_id: int,
    request: Request,
    user=Depends(get_current_user),
):
    if user["role"] != "superadmin" and user["org_id"] != org_id:
        raise HTTPException(status_code=403)
    project = db.get_project(project_id)
    if not project or project["org_id"] != org_id:
        raise HTTPException(status_code=404)
    documents = db.get_documents_by_org_and_project(org_id, project_id)
    # Build a mapping of document id to current revision label
    rev_labels = {}
    for doc in documents:
        rev_id = doc["current_revision_id"]
        if rev_id:
            rev_row = db.get_revision(rev_id)
            if rev_row:
                rev_labels[doc["id"]] = rev_row["revision"]
    return templates.TemplateResponse(
        "documents.html",
        {
            "request": request,
            "user": user,
            "org_id": org_id,
            "project": project,
            "documents": documents,
            "rev_labels": rev_labels,
        },
    )


@app.get(
    "/organizations/{org_id}/projects/{project_id}/documents/new",
    response_class=HTMLResponse,
)
async def new_document_form(
    org_id: int,
    project_id: int,
    request: Request,
    user=Depends(get_current_user),
):
    # Only users from this org can upload
    if user["role"] != "superadmin" and user["org_id"] != org_id:
        raise HTTPException(status_code=403)
    project = db.get_project(project_id)
    if not project or project["org_id"] != org_id:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "upload_document.html",
        {
            "request": request,
            "user": user,
            "org_id": org_id,
            "project": project,
            "error": None,
        },
    )


@app.post(
    "/organizations/{org_id}/projects/{project_id}/documents/new",
    response_class=HTMLResponse,
)
async def upload_document_action(org_id: int, project_id: int, request: Request, user=Depends(get_current_user)):
    if user["role"] != "superadmin" and user["org_id"] != org_id:
        raise HTTPException(status_code=403)
    # Determine content type
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    if content_type.startswith("multipart/form-data"):
        # Parse multipart manually using cgi
        import cgi, io
        environ = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": content_type,
        }
        fp = io.BytesIO(body)
        fs = cgi.FieldStorage(fp=fp, environ=environ, keep_blank_values=True)
        doc_number = fs.getvalue("doc_number") or ""
        title = fs.getvalue("title") or ""
        doc_type = fs.getvalue("doc_type") or ""
        status_field = fs.getvalue("status_field") or ""
        revision = fs.getvalue("revision") or ""
        fileitem = fs["file"] if "file" in fs else None
        if not doc_number or not title or not revision or not fileitem:
            return templates.TemplateResponse(
                "upload_document.html",
                {
                    "request": request,
                    "user": user,
                    "org_id": org_id,
                    "project": db.get_project(project_id),
                    "error": "Todos los campos son obligatorios",
                },
            )
        # Save file
        filename = f"{uuid.uuid4().hex}_{fileitem.filename}"
        file_path = os.path.join(UPLOAD_DIR, filename)
        with open(file_path, "wb") as out:
            out.write(fileitem.file.read())
    else:
        # Not multipart; unsupported
        raise HTTPException(status_code=400, detail="Formato no soportado")
    # Determine if document already exists
    existing_docs = db.get_documents_by_org_and_project(org_id, project_id)
    existing_doc = None
    for d in existing_docs:
        if d["doc_number"] == doc_number:
            existing_doc = d
            break
    if existing_doc:
        db.add_document_revision(existing_doc["id"], revision, file_path, user["id"])
    else:
        db.create_document(
            doc_number,
            title,
            doc_type,
            status_field,
            org_id,
            project_id,
            revision,
            file_path,
            user["id"],
        )
    return RedirectResponse(
        f"/organizations/{org_id}/projects/{project_id}/documents", status_code=302
    )


@app.get(
    "/organizations/{org_id}/projects/{project_id}/documents/{doc_id}",
    response_class=HTMLResponse,
)
async def document_detail(
    org_id: int,
    project_id: int,
    doc_id: int,
    request: Request,
    user=Depends(get_current_user),
):
    # Users must belong to org
    if user["role"] != "superadmin" and user["org_id"] != org_id:
        raise HTTPException(status_code=403)
    doc = db.get_document(doc_id)
    if not doc or doc["org_id"] != org_id or doc["project_id"] != project_id:
        raise HTTPException(status_code=404)
    revisions = db.get_revisions_for_document(doc_id)
    events = db.get_events_for_document(doc_id)
    return templates.TemplateResponse(
        "document_detail.html",
        {
            "request": request,
            "user": user,
            "doc": doc,
            "revisions": revisions,
            "events": events,
            "org_id": org_id,
            "project_id": project_id,
        },
    )


@app.get("/download/{revision_id}")
async def download_file(revision_id: int, user=Depends(get_current_user)):
    revision = db.get_revision(revision_id)
    if not revision:
        raise HTTPException(status_code=404)
    # Check user has access: must belong to document's org or be superadmin
    document = db.get_document(revision["document_id"])
    if user["role"] != "superadmin" and user["org_id"] != document["org_id"]:
        raise HTTPException(status_code=403)
    path = revision["file_path"]
    filename = os.path.basename(path)
    return FileResponse(path, filename=filename)


@app.get("/transmittals", response_class=HTMLResponse)
async def list_transmittals(request: Request, user=Depends(get_current_user)):
    trans = db.get_transmittals_for_org(user["org_id"])
    return templates.TemplateResponse(
        "transmittals.html",
        {
            "request": request,
            "user": user,
            "transmittals": trans,
        },
    )


@app.get("/transmittals/new", response_class=HTMLResponse)
async def new_transmittal_form(request: Request, user=Depends(get_current_user)):
    # Must be org_admin or superadmin to send transmittals
    if user["role"] not in ["superadmin", "org_admin"]:
        raise HTTPException(status_code=403)
    # Get organizations excluding current
    all_orgs = db.get_organizations()
    orgs = [o for o in all_orgs if o["id"] != user["org_id"]]
    # Documents across all projects of current org
    projects = db.get_projects_by_org(user["org_id"])
    docs = []
    for p in projects:
        docs.extend(db.get_documents_by_org_and_project(user["org_id"], p["id"]))
    # For each doc, we want current revision id
    doc_options = []
    for d in docs:
        doc_options.append(
            {
                "id": d["id"],
                "doc_number": d["doc_number"],
                "title": d["title"],
                "current_revision": d["current_revision_id"],
            }
        )
    return templates.TemplateResponse(
        "transmittal_form.html",
        {
            "request": request,
            "user": user,
            "orgs": orgs,
            "docs": doc_options,
            "error": None,
        },
    )


@app.post("/transmittals/new")
async def create_transmittal_action(request: Request, user=Depends(get_current_user)):
    if user["role"] not in ["superadmin", "org_admin"]:
        raise HTTPException(status_code=403)
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    # We'll parse application/x-www-form-urlencoded because file upload is not used here
    from urllib.parse import parse_qs
    if content_type.startswith("application/x-www-form-urlencoded"):
        data = parse_qs(body.decode())
    else:
        # fallback: attempt parse as form encoded anyway
        data = parse_qs(body.decode())
    trans_number = data.get("trans_number", [""])[0]
    description = data.get("description", [""])[0]
    recipient_org_id = int(data.get("recipient_org_id", ["0"])[0] or 0)
    selected_docs = data.get("selected_docs", [])
    try:
        revision_ids = [int(x) for x in selected_docs]
    except Exception:
        revision_ids = []
    if not trans_number or not recipient_org_id or not revision_ids:
        # Rebuild form lists to display again
        all_orgs = db.get_organizations()
        orgs = [o for o in all_orgs if o["id"] != user["org_id"]]
        projects = db.get_projects_by_org(user["org_id"])
        docs = []
        for p in projects:
            docs.extend(db.get_documents_by_org_and_project(user["org_id"], p["id"]))
        doc_options = []
        for d in docs:
            doc_options.append(
                {
                    "id": d["id"],
                    "doc_number": d["doc_number"],
                    "title": d["title"],
                    "current_revision": d["current_revision_id"],
                }
            )
        return templates.TemplateResponse(
            "transmittal_form.html",
            {
                "request": request,
                "user": user,
                "orgs": orgs,
                "docs": doc_options,
                "error": "Complete todos los campos y seleccione al menos un documento.",
            },
        )
    try:
        db.create_transmittal(
            trans_number,
            description,
            user["org_id"],
            recipient_org_id,
            revision_ids,
            user["id"],
        )
    except Exception as e:
        # On error return to form
        all_orgs = db.get_organizations()
        orgs = [o for o in all_orgs if o["id"] != user["org_id"]]
        projects = db.get_projects_by_org(user["org_id"])
        docs = []
        for p in projects:
            docs.extend(db.get_documents_by_org_and_project(user["org_id"], p["id"]))
        doc_options = []
        for d in docs:
            doc_options.append(
                {
                    "id": d["id"],
                    "doc_number": d["doc_number"],
                    "title": d["title"],
                    "current_revision": d["current_revision_id"],
                }
            )
        return templates.TemplateResponse(
            "transmittal_form.html",
            {
                "request": request,
                "user": user,
                "orgs": orgs,
                "docs": doc_options,
                "error": "No se pudo crear el transmittal. Revise los datos.",
            },
        )
    return RedirectResponse("/transmittals", status_code=302)


@app.get("/transmittals/{trans_id}", response_class=HTMLResponse)
async def transmittal_detail(trans_id: int, request: Request, user=Depends(get_current_user)):
    trans = db.get_transmittal(trans_id)
    if not trans:
        raise HTTPException(status_code=404)
    # Only sender or recipient org can view
    if user["role"] != "superadmin" and user["org_id"] not in [
        trans["sender_org_id"],
        trans["recipient_org_id"],
    ]:
        raise HTTPException(status_code=403)
    docs = db.get_transmittal_documents(trans_id)
    return templates.TemplateResponse(
        "transmittal_detail.html",
        {
            "request": request,
            "user": user,
            "trans": trans,
            "docs": docs,
        },
    )
