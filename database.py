"""
Database helper module for the document management SaaS application.

This module encapsulates all database operations using Python's built‑in
sqlite3 module. It creates all required tables on first run and provides
functions for CRUD operations on users, organizations, projects, documents
and related entities. Passwords are stored as salted SHA256 hashes to
provide basic security.

The database is stored in the same directory as this file under the name
`database.db`. Because sqlite3 is used directly without an ORM the code
remains lightweight and easy to port to other hosting environments. When
deploying to a more robust platform (e.g. DigitalOcean with Postgres) the
SQL statements defined here can be adapted accordingly.
"""

import os
import sqlite3
import hashlib
import uuid
from datetime import datetime, timedelta
from pathlib import Path

DB_FILENAME = "database.db"

def get_db_path() -> str:
    """Returns the absolute path to the SQLite database file."""
    base_dir = Path(__file__).resolve().parent
    return str(base_dir / DB_FILENAME)


def init_db() -> None:
    """Initialise the database and create tables if they do not exist."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Enable foreign key constraints
    c.execute("PRAGMA foreign_keys = ON;")

    # Create tables
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT,
            role TEXT NOT NULL,
            org_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        );
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            org_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(org_id) REFERENCES organizations(id)
        );
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_number TEXT NOT NULL,
            title TEXT NOT NULL,
            doc_type TEXT,
            status TEXT,
            org_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            current_revision_id INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE(doc_number, org_id, project_id),
            FOREIGN KEY(org_id) REFERENCES organizations(id),
            FOREIGN KEY(project_id) REFERENCES projects(id)
        );
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS document_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            revision TEXT NOT NULL,
            file_path TEXT NOT NULL,
            uploaded_by INTEGER NOT NULL,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY(document_id) REFERENCES documents(id),
            FOREIGN KEY(uploaded_by) REFERENCES users(id)
        );
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            revision_id INTEGER,
            user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY(document_id) REFERENCES documents(id),
            FOREIGN KEY(revision_id) REFERENCES document_revisions(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS transmittals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transmittal_number TEXT NOT NULL,
            description TEXT,
            sender_org_id INTEGER NOT NULL,
            recipient_org_id INTEGER NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(sender_org_id) REFERENCES organizations(id),
            FOREIGN KEY(recipient_org_id) REFERENCES organizations(id),
            FOREIGN KEY(created_by) REFERENCES users(id)
        );
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS transmittal_documents (
            transmittal_id INTEGER NOT NULL,
            revision_id INTEGER NOT NULL,
            PRIMARY KEY(transmittal_id, revision_id),
            FOREIGN KEY(transmittal_id) REFERENCES transmittals(id),
            FOREIGN KEY(revision_id) REFERENCES document_revisions(id)
        );
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """
    )

    conn.commit()
    conn.close()


def get_conn():
    """Return a new database connection with row_factory set to sqlite3.Row."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    """Return a salted SHA256 hash for the given plain text password."""
    salt = uuid.uuid4().hex
    return salt + ":" + hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def verify_password(stored_hash: str, password: str) -> bool:
    """Check if the provided password matches the stored salted hash."""
    try:
        salt, hashed = stored_hash.split(":", 1)
    except ValueError:
        return False
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest() == hashed


def create_default_superadmin() -> None:
    """Create a default superadmin user if no users exist.

    The default credentials are printed to stdout when the application starts.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    if count == 0:
        # Create a root organization to associate with superadmin
        now = datetime.utcnow().isoformat()
        c.execute(
            "INSERT INTO organizations (name, description, created_at) VALUES (?, ?, ?)",
            ("Global", "Default global organization", now),
        )
        org_id = c.lastrowid
        password = "admin"
        password_hash = hash_password(password)
        c.execute(
            "INSERT INTO users (email, password_hash, name, role, org_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("admin@example.com", password_hash, "Super Admin", "superadmin", org_id, now),
        )
        conn.commit()
        conn.close()
        print(
            "Created default superadmin user. Email: admin@example.com Password: admin"
        )
    else:
        conn.close()


def get_user_by_email(email: str):
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    conn.close()
    return user


def get_user_by_id(user_id: int):
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return user


def create_session(user_id: int, expires_minutes: int = 120) -> str:
    """Create a new session record and return the session id string."""
    session_id = uuid.uuid4().hex
    expires = datetime.utcnow() + timedelta(minutes=expires_minutes)
    conn = get_conn()
    conn.execute(
        "INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
        (session_id, user_id, expires.isoformat()),
    )
    conn.commit()
    conn.close()
    return session_id


def get_session(session_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    conn.close()
    return row


def delete_session(session_id: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()


def cleanup_sessions() -> None:
    """Remove expired sessions from the database."""
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    conn.commit()
    conn.close()


def create_organization(name: str, description: str) -> int:
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO organizations (name, description, created_at) VALUES (?, ?, ?)",
        (name, description, now),
    )
    org_id = c.lastrowid
    conn.commit()
    conn.close()
    return org_id


def get_organizations():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM organizations ORDER BY name").fetchall()
    conn.close()
    return rows


def get_organization(org_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM organizations WHERE id=?", (org_id,)).fetchone()
    conn.close()
    return row


def create_user(email: str, password: str, name: str, role: str, org_id: int) -> int:
    now = datetime.utcnow().isoformat()
    password_hash = hash_password(password)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (email, password_hash, name, role, org_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (email, password_hash, name, role, org_id, now),
    )
    user_id = c.lastrowid
    conn.commit()
    conn.close()
    return user_id


def get_users_by_org(org_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM users WHERE org_id=? ORDER BY name", (org_id,)
    ).fetchall()
    conn.close()
    return rows


def create_project(name: str, description: str, org_id: int) -> int:
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO projects (name, description, org_id, created_at) VALUES (?, ?, ?, ?)",
        (name, description, org_id, now),
    )
    project_id = c.lastrowid
    conn.commit()
    conn.close()
    return project_id


def get_projects_by_org(org_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM projects WHERE org_id=? ORDER BY name", (org_id,)
    ).fetchall()
    conn.close()
    return rows


def get_project(project_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM projects WHERE id=?", (project_id,)
    ).fetchone()
    conn.close()
    return row


def create_document(
    doc_number: str,
    title: str,
    doc_type: str,
    status: str,
    org_id: int,
    project_id: int,
    revision_label: str,
    file_path: str,
    uploaded_by: int,
) -> int:
    """
    Create a new document and its initial revision. Returns the document id.
    """
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    c = conn.cursor()
    # Insert document record
    c.execute(
        "INSERT INTO documents (doc_number, title, doc_type, status, org_id, project_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (doc_number, title, doc_type, status, org_id, project_id, now),
    )
    doc_id = c.lastrowid
    # Insert revision record
    c.execute(
        "INSERT INTO document_revisions (document_id, revision, file_path, uploaded_by, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (doc_id, revision_label, file_path, uploaded_by, now),
    )
    rev_id = c.lastrowid
    # Update current_revision_id on document
    c.execute(
        "UPDATE documents SET current_revision_id=? WHERE id=?", (rev_id, doc_id)
    )
    # Add event for upload
    c.execute(
        "INSERT INTO events (document_id, revision_id, user_id, event_type, timestamp) VALUES (?, ?, ?, ?, ?)",
        (doc_id, rev_id, uploaded_by, "Uploaded", now),
    )
    conn.commit()
    conn.close()
    return doc_id


def add_document_revision(
    document_id: int,
    revision_label: str,
    file_path: str,
    uploaded_by: int,
) -> int:
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    c = conn.cursor()
    # Insert revision
    c.execute(
        "INSERT INTO document_revisions (document_id, revision, file_path, uploaded_by, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (document_id, revision_label, file_path, uploaded_by, now),
    )
    rev_id = c.lastrowid
    # Update document current revision
    c.execute(
        "UPDATE documents SET current_revision_id=? WHERE id=?", (rev_id, document_id)
    )
    # Add event
    c.execute(
        "INSERT INTO events (document_id, revision_id, user_id, event_type, timestamp) VALUES (?, ?, ?, ?, ?)",
        (document_id, rev_id, uploaded_by, "RevisionUploaded", now),
    )
    conn.commit()
    conn.close()
    return rev_id


def get_documents_by_org_and_project(org_id: int, project_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM documents WHERE org_id=? AND project_id=? ORDER BY doc_number",
        (org_id, project_id),
    ).fetchall()
    conn.close()
    return rows


def get_document(doc_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    conn.close()
    return row


def get_revision(rev_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM document_revisions WHERE id=?", (rev_id,)
    ).fetchone()
    conn.close()
    return row


def get_revisions_for_document(doc_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM document_revisions WHERE document_id=? ORDER BY uploaded_at DESC",
        (doc_id,),
    ).fetchall()
    conn.close()
    return rows


def get_events_for_document(doc_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT events.*, users.name AS user_name FROM events JOIN users ON events.user_id = users.id "
        "WHERE events.document_id=? ORDER BY events.timestamp DESC",
        (doc_id,),
    ).fetchall()
    conn.close()
    return rows


def create_transmittal(
    transmittal_number: str,
    description: str,
    sender_org_id: int,
    recipient_org_id: int,
    document_revision_ids: list[int],
    created_by: int,
) -> int:
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO transmittals (transmittal_number, description, sender_org_id, recipient_org_id, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (transmittal_number, description, sender_org_id, recipient_org_id, created_by, now),
    )
    trans_id = c.lastrowid
    # Link documents to transmittal
    for rev_id in document_revision_ids:
        c.execute(
            "INSERT INTO transmittal_documents (transmittal_id, revision_id) VALUES (?, ?)",
            (trans_id, rev_id),
        )
        # Create events: sent on document
        # Determine document id for event
        doc_id = c.execute(
            "SELECT document_id FROM document_revisions WHERE id=?", (rev_id,)
        ).fetchone()[0]
        c.execute(
            "INSERT INTO events (document_id, revision_id, user_id, event_type, timestamp, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                doc_id,
                rev_id,
                created_by,
                "Sent",
                now,
                f"Transmittal {transmittal_number} sent to org {recipient_org_id}",
            ),
        )
        # Copy document to recipient organization if not already exists
        # We'll create a new document entry in recipient org's register if doc_number does not exist
        row = c.execute(
            "SELECT doc_number, title, doc_type, status, project_id FROM documents WHERE id=?",
            (doc_id,),
        ).fetchone()
        doc_number, title, doc_type, status, project_id = row
        # Check if document exists for recipient org in same project
        existing = c.execute(
            "SELECT id FROM documents WHERE doc_number=? AND org_id=? AND project_id=?",
            (doc_number, recipient_org_id, project_id),
        ).fetchone()
        if existing is None:
            # Create document and revision for recipient
            c.execute(
                "INSERT INTO documents (doc_number, title, doc_type, status, org_id, project_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (doc_number, title, doc_type, status, recipient_org_id, project_id, now),
            )
            new_doc_id = c.lastrowid
            # Insert revision pointing to same file_path (share file) but treat as new revision 1
            # We'll copy file path; revision label remains same
            new_rev_label = row = c.execute(
                "SELECT revision FROM document_revisions WHERE id=?", (rev_id,)
            ).fetchone()[0]
            new_file_path = c.execute(
                "SELECT file_path FROM document_revisions WHERE id=?", (rev_id,)
            ).fetchone()[0]
            c.execute(
                "INSERT INTO document_revisions (document_id, revision, file_path, uploaded_by, uploaded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (new_doc_id, new_rev_label, new_file_path, created_by, now),
            )
            new_rev_id = c.lastrowid
            c.execute(
                "UPDATE documents SET current_revision_id=? WHERE id=?", (new_rev_id, new_doc_id)
            )
        else:
            # Document exists: add revision
            existing_doc_id = existing[0]
            # create new revision with same file and revision label
            new_rev_label = c.execute(
                "SELECT revision FROM document_revisions WHERE id=?", (rev_id,)
            ).fetchone()[0]
            new_file_path = c.execute(
                "SELECT file_path FROM document_revisions WHERE id=?", (rev_id,)
            ).fetchone()[0]
            c.execute(
                "INSERT INTO document_revisions (document_id, revision, file_path, uploaded_by, uploaded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (existing_doc_id, new_rev_label, new_file_path, created_by, now),
            )
            new_rev_id = c.lastrowid
            c.execute(
                "UPDATE documents SET current_revision_id=? WHERE id=?", (new_rev_id, existing_doc_id)
            )
    conn.commit()
    conn.close()
    return trans_id


def get_transmittals_for_org(org_id: int):
    """Return transmittals sent or received by the organization."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM transmittals WHERE sender_org_id=? OR recipient_org_id=? ORDER BY created_at DESC",
        (org_id, org_id),
    ).fetchall()
    conn.close()
    return rows


def get_transmittal(trans_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM transmittals WHERE id=?",
        (trans_id,),
    ).fetchone()
    conn.close()
    return row


def get_transmittal_documents(trans_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT document_revisions.* FROM transmittal_documents JOIN document_revisions ON transmittal_documents.revision_id = document_revisions.id WHERE transmittal_documents.transmittal_id=?",
        (trans_id,),
    ).fetchall()
    conn.close()
    return rows
