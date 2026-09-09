#!/usr/bin/env python3
"""
AcademiQ — Database Setup & OKF Knowledge Ingestion
Upgrades the database schema to support Open Knowledge Format (OKF),
Parent-Child hierarchical units, pgvector similarity, Full-Text Search (GIN),
and Feedback/Reward Logging.

Usage:
    python setup_db.py
"""

import os
import sys
import json
import re
import urllib.request
import urllib.error

# ── Try importing optional dependencies ──────────────────────────────────────
try:
    import psycopg2
    from pgvector.psycopg2 import register_vector
except ImportError:
    print("ERROR: psycopg2 or pgvector not installed.")
    print("Run:  pip install -r requirements.txt")
    sys.exit(1)

try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False
    print("WARNING: PyPDF2 not found — PDF files will be skipped.")

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    print("WARNING: beautifulsoup4 not found — HTML files will be skipped.")

from okf_engine import OKFExtractor

# ── Configuration ─────────────────────────────────────────────────────────────
PG_HOST          = os.environ.get("PG_HOST", "127.0.0.1")
PG_PORT          = int(os.environ.get("PG_PORT", 5433))  # Docker maps container 5432 → host 5433
PG_DB            = os.environ.get("PG_DB", "academiq")
PG_USER          = os.environ.get("PG_USER", "postgres")
PG_PASS          = os.environ.get("PG_PASS", "postgres")

OLLAMA_BASE_URL  = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL      = "nomic-embed-text"
EMBED_DIM        = 768

KB_DIR           = "knowledge_base"
SUPPORTED_EXTS   = {".txt", ".md", ".html", ".htm", ".pdf"}

# ── Text extraction ───────────────────────────────────────────────────────────
def extract_text_txt(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def extract_text_md(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def extract_text_html(path):
    if not HAS_BS4:
        return None
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f.read(), "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n")

def extract_text_pdf(path):
    if not HAS_PDF:
        return None
    text_parts = []
    try:
        reader = PyPDF2.PdfReader(path)
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    except Exception as e:
        print(f"  WARNING: Could not read PDF '{path}': {e}")
        return None
    return "\n".join(text_parts)

def extract_text(path, ext):
    if ext in (".txt",):
        return extract_text_txt(path)
    elif ext == ".md":
        return extract_text_md(path)
    elif ext in (".html", ".htm"):
        return extract_text_html(path)
    elif ext == ".pdf":
        return extract_text_pdf(path)
    return None

# ── Ollama embedding ──────────────────────────────────────────────────────────
def get_embedding(text):
    """Call Ollama's embed API and return a float list."""
    payload = json.dumps({
        "model": EMBED_MODEL,
        "prompt": text
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("embedding", [])
    except Exception as e:
        print(f"  ERROR calling Ollama embed API: {e}")
        return None

def check_ollama():
    """Return True if Ollama is reachable and the embed model is available."""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            if not any(EMBED_MODEL in m for m in models):
                print(f"WARNING: Model '{EMBED_MODEL}' not found in Ollama.")
                print(f"Run:  ollama pull {EMBED_MODEL}")
                return False
            return True
    except Exception:
        return False

# ── Database setup ────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB,
        user=PG_USER, password=PG_PASS
    )

def setup_schema(conn):
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

        # 1. Users Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            SERIAL PRIMARY KEY,
                username      VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role          VARCHAR(20) NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
                created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # 2. Sessions Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token         VARCHAR(64) PRIMARY KEY,
                user_id       INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at    TIMESTAMP WITH TIME ZONE NOT NULL,
                created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # 3. Groups Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id          SERIAL PRIMARY KEY,
                name        VARCHAR(100) UNIQUE NOT NULL,
                is_system   BOOLEAN NOT NULL DEFAULT FALSE,
                created_by  INT REFERENCES users(id) ON DELETE SET NULL,
                created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # 4. Group Members Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS group_members (
                id          SERIAL PRIMARY KEY,
                group_id    INT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                joined_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                CONSTRAINT uq_group_user UNIQUE (group_id, user_id)
            );
        """)

        # 5. Documents Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id              SERIAL PRIMARY KEY,
                user_id         INT REFERENCES users(id) ON DELETE CASCADE,
                group_id        INT REFERENCES groups(id) ON DELETE SET NULL,
                filename        TEXT UNIQUE NOT NULL,
                title           TEXT NOT NULL,
                category        TEXT NOT NULL,
                authority       TEXT NOT NULL,
                version         TEXT NOT NULL DEFAULT '1.0',
                effective_date  TEXT,
                expiry_date     TEXT,
                is_active       BOOLEAN NOT NULL DEFAULT TRUE,
                file_hash       TEXT,
                created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # Ensure user_id and group_id columns exist on existing documents table
        cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id) ON DELETE CASCADE;")
        cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS group_id INT REFERENCES groups(id) ON DELETE SET NULL;")

        # 6. Structured Knowledge Units (OKF)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS knowledge_units (
                id              SERIAL PRIMARY KEY,
                document_id     INT REFERENCES documents(id) ON DELETE CASCADE,
                user_id         INT REFERENCES users(id) ON DELETE CASCADE,
                group_id        INT REFERENCES groups(id) ON DELETE SET NULL,
                parent_id       INT,
                unit_code       TEXT,
                chunk_type      TEXT NOT NULL,
                entity_type     TEXT NOT NULL,
                section_title   TEXT,
                content         TEXT NOT NULL,
                summary         TEXT,
                rules_json      JSONB,
                table_data_json JSONB,
                metadata_json   JSONB,
                embedding       VECTOR({EMBED_DIM}),
                tsv_content     TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', coalesce(section_title, '') || ' ' || content)) STORED,
                feedback_score  FLOAT NOT NULL DEFAULT 0.0,
                created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)

        # Ensure new columns exist on existing knowledge_units table
        cur.execute("ALTER TABLE knowledge_units ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id) ON DELETE CASCADE;")
        cur.execute("ALTER TABLE knowledge_units ADD COLUMN IF NOT EXISTS group_id INT REFERENCES groups(id) ON DELETE SET NULL;")
        cur.execute("ALTER TABLE knowledge_units ADD COLUMN IF NOT EXISTS feedback_score FLOAT NOT NULL DEFAULT 0.0;")

        # 7. Feedback / Reward Logging Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feedback_logs (
                id                  SERIAL PRIMARY KEY,
                user_id             INT REFERENCES users(id) ON DELETE SET NULL,
                query               TEXT NOT NULL,
                response            TEXT NOT NULL,
                rating              INT NOT NULL, -- +1 for upvote, -1 for downvote
                feedback_notes      TEXT,
                retrieved_unit_ids  TEXT,
                model               TEXT,
                created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        cur.execute("ALTER TABLE feedback_logs ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id) ON DELETE SET NULL;")

        # 8. Backward Compatibility Table
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id        SERIAL PRIMARY KEY,
                user_id   INT REFERENCES users(id) ON DELETE CASCADE,
                group_id  INT REFERENCES groups(id) ON DELETE SET NULL,
                source    TEXT NOT NULL,
                file_type TEXT NOT NULL,
                content   TEXT NOT NULL,
                embedding VECTOR({EMBED_DIM})
            );
        """)
        cur.execute("ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id) ON DELETE CASCADE;")
        cur.execute("ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS group_id INT REFERENCES groups(id) ON DELETE SET NULL;")

        # 9. Indexes
        cur.execute("""
            CREATE INDEX IF NOT EXISTS ku_vector_idx
            ON knowledge_units
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 10);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS ku_fts_idx
            ON knowledge_units
            USING gin (tsv_content);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS docs_active_idx
            ON documents (is_active, category);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_group_members_user_group
            ON group_members(user_id, group_id);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_group_members_group_user
            ON group_members(group_id, user_id);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_docs_scoping
            ON documents(user_id, group_id, is_active);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ku_scoping
            ON knowledge_units(user_id, group_id, chunk_type);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ku_feedback_score
            ON knowledge_units(feedback_score);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_user_id
            ON sessions(user_id);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_expires_at
            ON sessions(expires_at);
        """)

        # 10. Groups and Ownership Migration (Fix 1 Applied)
        cur.execute("""
            DO $$
            DECLARE
                admin_id INT;
                everyone_id INT;
            BEGIN
                -- Check for existing admin account provisioned via create_admin.py
                SELECT id INTO admin_id FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1;
                IF admin_id IS NULL THEN
                    RAISE EXCEPTION 'Migration failed: No admin account found. Please run create_admin.py to provision an admin account before running this migration.';
                END IF;

                -- Ensure system 'Everyone' group exists
                INSERT INTO groups (name, is_system, created_by) VALUES ('Everyone', TRUE, admin_id)
                ON CONFLICT (name) DO NOTHING;
                SELECT id INTO everyone_id FROM groups WHERE name = 'Everyone';

                -- Enroll all existing users into 'Everyone'
                INSERT INTO group_members (group_id, user_id)
                SELECT everyone_id, u.id FROM users u
                ON CONFLICT (group_id, user_id) DO NOTHING;

                -- Assign un-scoped documents to admin and the 'Everyone' group
                UPDATE documents SET user_id = admin_id, group_id = everyone_id WHERE user_id IS NULL;
                UPDATE knowledge_units ku
                SET user_id = d.user_id, group_id = d.group_id
                FROM documents d
                WHERE ku.document_id = d.id AND ku.user_id IS NULL;
                UPDATE document_chunks SET user_id = admin_id, group_id = everyone_id WHERE user_id IS NULL;
            END $$;
        """)

    conn.commit()
    print("[OK] Database schema initialized with OKF, Users, Sessions, Groups, and Scoping.")

def clear_tables(conn):
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE knowledge_units, documents, document_chunks, feedback_logs RESTART IDENTITY CASCADE;")
    conn.commit()
    print("[OK] Cleared existing tables.")

def ingest_okf_document(conn, filename, text, ext, user_id=None, group_id=None):
    metadata = OKFExtractor.extract_document_metadata(text, filename)
    units = OKFExtractor.process_document(text, filename)
    
    file_bytes = text.encode("utf-8", errors="ignore")
    file_hash = OKFExtractor.compute_file_hash(file_bytes)

    with conn.cursor() as cur:
        # Resolve default admin and Everyone group if not passed
        if user_id is None:
            cur.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1;")
            admin_row = cur.fetchone()
            user_id = admin_row[0] if admin_row else 1
        
        if group_id is None:
            cur.execute("SELECT id FROM groups WHERE name = 'Everyone' LIMIT 1;")
            grp_row = cur.fetchone()
            group_id = grp_row[0] if grp_row else None

        # Insert or update document master
        cur.execute("""
            INSERT INTO documents (user_id, group_id, filename, title, category, authority, version, effective_date, file_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (filename) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                group_id = EXCLUDED.group_id,
                title = EXCLUDED.title,
                category = EXCLUDED.category,
                authority = EXCLUDED.authority,
                version = EXCLUDED.version,
                effective_date = EXCLUDED.effective_date,
                file_hash = EXCLUDED.file_hash,
                is_active = TRUE
            RETURNING id;
        """, (user_id, group_id, filename, metadata.title, metadata.category, metadata.authority, metadata.version, metadata.effective_date, file_hash))
        doc_id = cur.fetchone()[0]

        # Clean existing units for this doc
        cur.execute("DELETE FROM knowledge_units WHERE document_id = %s;", (doc_id,))
        cur.execute("DELETE FROM document_chunks WHERE source = %s;", (filename,))

        # Map parent unit_code to inserted DB ID
        parent_id_map = {}

        # 1. Insert Parent Units first
        parent_units = [u for u in units if u.chunk_type == "parent"]
        for pu in parent_units:
            rules_val = json.dumps(pu.rules) if pu.rules else None
            table_val = json.dumps(pu.table_data) if pu.table_data else None
            meta_val = json.dumps(pu.metadata) if pu.metadata else None

            cur.execute("""
                INSERT INTO knowledge_units 
                (document_id, user_id, group_id, parent_id, unit_code, chunk_type, entity_type, section_title, content, summary, rules_json, table_data_json, metadata_json, embedding, feedback_score)
                VALUES (%s, %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, 0.0)
                RETURNING id;
            """, (doc_id, user_id, group_id, pu.unit_id, pu.chunk_type, pu.entity_type, pu.section_title, pu.content, pu.summary, rules_val, table_val, meta_val))
            inserted_id = cur.fetchone()[0]
            parent_id_map[pu.unit_id] = inserted_id

        # 2. Insert Child Units with Embeddings
        child_units = [u for u in units if u.chunk_type == "child"]
        stored_count = 0
        for cu in child_units:
            embedding = get_embedding(cu.content)
            emb_vector = embedding if (embedding and len(embedding) == EMBED_DIM) else None

            db_parent_id = parent_id_map.get(cu.parent_id)
            rules_val = json.dumps(cu.rules) if cu.rules else None
            table_val = json.dumps(cu.table_data) if cu.table_data else None
            meta_val = json.dumps(cu.metadata) if cu.metadata else None

            cur.execute("""
                INSERT INTO knowledge_units 
                (document_id, user_id, group_id, parent_id, unit_code, chunk_type, entity_type, section_title, content, summary, rules_json, table_data_json, metadata_json, embedding, feedback_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0.0);
            """, (doc_id, user_id, group_id, db_parent_id, cu.unit_id, cu.chunk_type, cu.entity_type, cu.section_title, cu.content, cu.summary, rules_val, table_val, meta_val, emb_vector))

            # Backward compatibility insert
            cur.execute("""
                INSERT INTO document_chunks (user_id, group_id, source, file_type, content, embedding)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (user_id, group_id, filename, ext.lstrip("."), cu.content, emb_vector))

            stored_count += 1

    conn.commit()
    return len(parent_units), stored_count

# ── Main ingestion ────────────────────────────────────────────────────────────
def ingest():
    print("\n" + "="*55)
    print("  AcademiQ — Open Knowledge Format (OKF) Ingestion")
    print("="*55)

    # 1. Check Ollama
    print("\n[1/4] Checking Ollama...")
    if not check_ollama():
        print("ERROR: Ollama is not running or model not pulled.")
        print(f"Start Ollama, then run:  ollama pull {EMBED_MODEL}")
        sys.exit(1)
    print(f"  [OK] Ollama running, model '{EMBED_MODEL}' found.")

    # 2. Connect to DB
    print("\n[2/4] Connecting to PostgreSQL...")
    try:
        conn = get_conn()
        register_vector(conn)
        print(f"  [OK] Connected to {PG_DB} on {PG_HOST}:{PG_PORT}")
    except Exception as e:
        print(f"  ERROR: Cannot connect to PostgreSQL: {e}")
        print(f"  Make sure the Docker container is running on port {PG_PORT}.")
        sys.exit(1)

    # 3. Setup schema
    print("\n[3/4] Initializing OKF Schema & Full-Text Indexes...")
    setup_schema(conn)
    clear_tables(conn)

    # 4. Ingest files
    print(f"\n[4/4] Processing files from '{KB_DIR}/' into OKF Knowledge Units...")
    if not os.path.exists(KB_DIR):
        print(f"  ERROR: '{KB_DIR}/' directory not found.")
        sys.exit(1)

    total_parents = 0
    total_children = 0
    total_files = 0

    for filename in sorted(os.listdir(KB_DIR)):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTS:
            continue

        path = os.path.join(KB_DIR, filename)
        print(f"\n  -> {filename} ({ext})")

        text = extract_text(path, ext)
        if not text or not text.strip():
            print("    SKIP: No readable text extracted.")
            continue

        p_count, c_count = ingest_okf_document(conn, filename, text, ext)
        print(f"    [OK] Extracted {p_count} Parent Section(s) & {c_count} Child Unit(s)")
        total_parents += p_count
        total_children += c_count
        total_files += 1

    conn.close()

    print("\n" + "="*55)
    print(f"  DONE: Ingested {total_files} file(s) -> {total_parents} Parent Sections, {total_children} Child Units")
    print("  You can now start the server: python server.py")
    print("="*55 + "\n")

if __name__ == "__main__":
    ingest()
