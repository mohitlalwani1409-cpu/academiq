#!/usr/bin/env python3
"""
AcademiQ — Institutional AI Knowledge Platform Server
Powered by Open Knowledge Format (OKF), Parallel Hybrid Search (Vector + Full-Text RRF),
Deterministic Pure Math Reranking, Three-Tier Groups Scoping, Token Streaming,
and Role-Gated Admin Analytics.

Run:  python server.py
Open: http://localhost:3001
"""

import http.server
import socketserver
import urllib.request
import time
import urllib.error
import json
import os
import mimetypes
import re
import base64
import io
import hashlib
import sys
import secrets
import datetime
import concurrent.futures
import math

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import bcrypt
from okf_engine import OKFExtractor, KnowledgeUnit

PORT = 3001

# ── Configuration ─────────────────────────────────────────────────────────────
OLLAMA_BASE_URL  = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_MODEL  = "llama3.2:3b"
OLLAMA_EMBED_MODEL = "nomic-embed-text"
EMBED_DIM        = 768

PG_HOST = os.environ.get("PG_HOST", "127.0.0.1")
PG_PORT = int(os.environ.get("PG_PORT", 5433))   # Docker container mapped to host port 5433
PG_DB   = os.environ.get("PG_DB", "academiq")
PG_USER = os.environ.get("PG_USER", "postgres")
PG_PASS = os.environ.get("PG_PASS", "postgres")

REDIS_HOST = os.environ.get("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_DB   = 0
EMBED_CACHE_TTL   = 604800  # 7 days
CHAT_CACHE_TTL    = 86400   # 24 hours
RATE_LIMIT_WINDOW = 60      # 1 minute
RATE_LIMIT_MAX    = 30      # Max chat requests per minute per IP

TOP_K   = 3    # Number of RAG units to retrieve per query
SIMILARITY_THRESHOLD = 0.45
WARMUP_ON_START = True
KB_DIR  = "knowledge_base"

# ── Cloud Provider API Keys (loaded from .env) ──
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY      = os.environ.get("GROQ_API_KEY", "")

GEMINI_API_URL    = "https://generativelanguage.googleapis.com/v1beta/models"
GROQ_API_URL      = "https://api.groq.com/openai/v1/chat/completions"

GEMINI_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
GROQ_MODELS   = ["groq/compound-mini", "groq/compound", "openai/gpt-oss-20b", "allam-2-7b"]

# ── Optional imports ──────────────────────────────────────────────────────────
try:
    import psycopg2
    from pgvector.psycopg2 import register_vector
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

try:
    import redis
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        socket_timeout=0.3,
        socket_connect_timeout=0.3
    )
    redis_client.ping()
    HAS_REDIS = True
except Exception:
    HAS_REDIS = False
    redis_client = None

try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# ── System prompts per topic ──────────────────────────────────────────────────
SYSTEM_PROMPTS = {
    "general": (
        "You are AcademiQ, a verified institutional intelligence system and knowledge advisor. "
        "You provide clear, accurate, and directly grounded answers to user questions, "
        "including policy guidelines, compliance rules, procedures, and technical documentation. "
        "Format responses cleanly with markdown."
    ),
    "study": (
        "You are AcademiQ, an expert in study strategies, time management, and learning techniques. "
        "You help with study schedules, focus methods (Pomodoro, active recall, spaced repetition), "
        "and productivity habits. Give practical, actionable advice."
    ),
    "exams": (
        "You are AcademiQ, an expert in exam preparation and test-taking strategies. "
        "You help students with revision planning, managing exam anxiety, understanding question patterns, "
        "and time management during tests."
    ),
    "career": (
        "You are AcademiQ, an advisor for career pathways, college majors, resume feedback, "
        "internships, and job market skills. Provide realistic, actionable guidance."
    ),
    "writing": (
        "You are AcademiQ, specializing in academic and professional writing, SOP structuring, citations (APA, MLA), "
        "and editing. Provide concrete examples and well-structured suggestions."
    ),
    "stress": (
        "You are AcademiQ, focused on wellbeing and stress management. "
        "Help with burnout recovery, motivation, and healthy habits with an empathetic and supportive tone."
    ),
}

# ── Health checks ─────────────────────────────────────────────────────────────
def check_ollama():
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            has_chat  = any(OLLAMA_CHAT_MODEL.split(":")[0] in m for m in models)
            has_embed = any(OLLAMA_EMBED_MODEL.split(":")[0] in m for m in models)
            return has_chat and has_embed
    except Exception:
        return False

def get_db_conn():
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB,
        user=PG_USER, password=PG_PASS,
        connect_timeout=3
    )
    if HAS_PSYCOPG2:
        register_vector(conn)
    return conn

def check_db():
    if not HAS_PSYCOPG2:
        return False
    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM knowledge_units;")
            count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False

def check_redis():
    if not HAS_REDIS or not redis_client:
        return False
    try:
        return redis_client.ping()
    except Exception:
        return False

def is_rate_limited(ip_address):
    if not HAS_REDIS or not redis_client:
        return False
    try:
        key = f"ratelimit:{ip_address}"
        requests = redis_client.incr(key)
        if requests == 1:
            redis_client.expire(key, RATE_LIMIT_WINDOW)
        return requests > RATE_LIMIT_MAX
    except Exception as e:
        print(f"  [REDIS] Rate limit check error: {e}")
        return False

def init_db_schema_if_needed():
    """Ensures core auth, sessions, groups, and scoping tables exist."""
    if not HAS_PSYCOPG2:
        return
    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            SERIAL PRIMARY KEY,
                    username      VARCHAR(50) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    role          VARCHAR(20) NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
                    created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token         VARCHAR(64) PRIMARY KEY,
                    user_id       INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at    TIMESTAMP WITH TIME ZONE NOT NULL,
                    created_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    id          SERIAL PRIMARY KEY,
                    name        VARCHAR(100) UNIQUE NOT NULL,
                    is_system   BOOLEAN NOT NULL DEFAULT FALSE,
                    created_by  INT REFERENCES users(id) ON DELETE SET NULL,
                    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS group_members (
                    id          SERIAL PRIMARY KEY,
                    group_id    INT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    joined_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    CONSTRAINT uq_group_user UNIQUE (group_id, user_id)
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_group_members_user_group ON group_members(user_id, group_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_group_members_group_user ON group_members(group_id, user_id);")

            # Ensure system Everyone group exists
            cur.execute("""
                INSERT INTO groups (name, is_system)
                VALUES ('Everyone', TRUE)
                ON CONFLICT (name) DO NOTHING;
            """)

            # Ensure documents and knowledge_units scoping and feedback columns exist
            cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id) ON DELETE CASCADE;")
            cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS group_id INT REFERENCES groups(id) ON DELETE SET NULL;")

            cur.execute("ALTER TABLE knowledge_units ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id) ON DELETE CASCADE;")
            cur.execute("ALTER TABLE knowledge_units ADD COLUMN IF NOT EXISTS group_id INT REFERENCES groups(id) ON DELETE SET NULL;")
            cur.execute("ALTER TABLE knowledge_units ADD COLUMN IF NOT EXISTS feedback_score FLOAT NOT NULL DEFAULT 0.0;")

            # Ensure feedback_logs table exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS feedback_logs (
                    id                  SERIAL PRIMARY KEY,
                    user_id             INT REFERENCES users(id) ON DELETE SET NULL,
                    query               TEXT NOT NULL,
                    response            TEXT NOT NULL,
                    rating              INT NOT NULL,
                    feedback_notes      TEXT,
                    retrieved_unit_ids  TEXT,
                    model               TEXT,
                    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
            """)
            cur.execute("ALTER TABLE feedback_logs ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id) ON DELETE SET NULL;")

            # Migrate unassigned documents and knowledge units to Everyone group & default admin
            cur.execute("""
                DO $$
                DECLARE
                    admin_id INT;
                    everyone_id INT;
                BEGIN
                    SELECT id INTO admin_id FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1;
                    SELECT id INTO everyone_id FROM groups WHERE name = 'Everyone' LIMIT 1;
                    
                    IF everyone_id IS NOT NULL THEN
                        UPDATE documents SET group_id = everyone_id WHERE group_id IS NULL;
                        IF admin_id IS NOT NULL THEN
                            UPDATE documents SET user_id = admin_id WHERE user_id IS NULL;
                        END IF;
                        UPDATE knowledge_units ku
                        SET group_id = COALESCE(ku.group_id, d.group_id, everyone_id),
                            user_id = COALESCE(ku.user_id, d.user_id, admin_id)
                        FROM documents d
                        WHERE ku.document_id = d.id;
                    END IF;
                END $$;
            """)
        conn.commit()
        conn.close()
        print("  [DB SCHEMA] Core auth, sessions, groups, and scoping columns verified.")
    except Exception as e:
        print(f"  [DB SCHEMA INIT] Warning: {e}")

# ── Session & Authentication Management ───────────────────────────────────────
def get_authenticated_user(headers):
    if not HAS_PSYCOPG2:
        return None
    cookie_header = headers.get("Cookie", "")
    token = None
    if "session_token=" in cookie_header:
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("session_token="):
                token = part.split("=", 1)[1]
                break
    if not token:
        auth_header = headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None

    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.id, u.username, u.role
                FROM sessions s
                JOIN users u ON s.user_id = u.id
                WHERE s.token = %s AND s.expires_at > NOW();
            """, (token,))
            row = cur.fetchone()
        conn.close()
        if row:
            return {"id": row[0], "username": row[1], "role": row[2]}
    except Exception as e:
        print(f"  [AUTH ERROR] {e}")
    return None

def create_session(user_id):
    token = secrets.token_hex(32)
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO sessions (token, user_id, expires_at)
            VALUES (%s, %s, NOW() + INTERVAL '7 days');
        """, (token, user_id))
    conn.commit()
    conn.close()
    return token

def delete_session(token):
    if not token:
        return
    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token = %s;", (token,))
        conn.commit()
        conn.close()
    except Exception:
        pass

# ── Text Extraction ───────────────────────────────────────────────────────────
def extract_text_from_bytes(file_bytes, filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".txt",):
        return file_bytes.decode("utf-8", errors="ignore")
    elif ext == ".md":
        return file_bytes.decode("utf-8", errors="ignore")
    elif ext in (".html", ".htm"):
        if not HAS_BS4:
            return file_bytes.decode("utf-8", errors="ignore")
        soup = BeautifulSoup(file_bytes.decode("utf-8", errors="ignore"), "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator="\n")
    elif ext == ".pdf":
        if not HAS_PDF:
            raise ValueError("PyPDF2 library not installed on server.")
        text_parts = []
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
        return "\n".join(text_parts)
    else:
        return file_bytes.decode("utf-8", errors="ignore")

# ── In-Memory Embedding Cache ──────────────────────────────────────────────────
_MEMORY_EMBED_CACHE = {}

# ── Embedding with In-Memory & Redis Caching ──────────────────────────────────
def get_embedding(text):
    if not text:
        return None

    cache_hash = hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()
    if cache_hash in _MEMORY_EMBED_CACHE:
        return _MEMORY_EMBED_CACHE[cache_hash]

    if HAS_REDIS and redis_client:
        try:
            cached_bytes = redis_client.get(f"embed:{cache_hash}")
            if cached_bytes:
                emb = json.loads(cached_bytes.decode("utf-8"))
                _MEMORY_EMBED_CACHE[cache_hash] = emb
                return emb
        except Exception:
            pass

    try:
        payload = json.dumps({
            "model": OLLAMA_EMBED_MODEL,
            "prompt": text,
            "keep_alive": "30m"
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            embedding = data.get("embedding", [])

            if embedding:
                _MEMORY_EMBED_CACHE[cache_hash] = embedding
                if HAS_REDIS and redis_client:
                    try:
                        redis_client.set(f"embed:{cache_hash}", json.dumps(embedding), ex=EMBED_CACHE_TTL)
                    except Exception:
                        pass
                return embedding
    except Exception as e:
        print(f"  [EMBED] Note/fallback: {e}")

    return None

# ── Ingest Single Uploaded Document (OKF Pipeline with Scoping) ───────────────
def process_uploaded_file(filename, file_bytes, user_id=None, group_id=None):
    if not HAS_PSYCOPG2:
        raise ValueError("PostgreSQL driver (psycopg2) is not available.")

    os.makedirs(KB_DIR, exist_ok=True)
    save_path = os.path.join(KB_DIR, filename)
    with open(save_path, "wb") as f:
        f.write(file_bytes)

    ext  = os.path.splitext(filename)[1].lower()
    text = extract_text_from_bytes(file_bytes, filename)
    if not text or not text.strip():
        raise ValueError("No readable text could be extracted from file.")

    metadata = OKFExtractor.extract_document_metadata(text, filename)
    units = OKFExtractor.process_document(text, filename)
    file_hash = OKFExtractor.compute_file_hash(file_bytes)

    conn = get_db_conn()

    with conn.cursor() as cur:
        if user_id is None:
            cur.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1;")
            admin_row = cur.fetchone()
            user_id = admin_row[0] if admin_row else 1

        if group_id is None:
            cur.execute("SELECT id FROM groups WHERE name = 'Everyone' LIMIT 1;")
            grp_row = cur.fetchone()
            group_id = grp_row[0] if grp_row else None

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

        cur.execute("DELETE FROM knowledge_units WHERE document_id = %s;", (doc_id,))
        cur.execute("DELETE FROM document_chunks WHERE source = %s;", (filename,))

        parent_id_map = {}

        for pu in [u for u in units if u.chunk_type == "parent"]:
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

        stored_chunks = 0
        for cu in [u for u in units if u.chunk_type == "child"]:
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

            cur.execute("""
                INSERT INTO document_chunks (user_id, group_id, source, file_type, content, embedding)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (user_id, group_id, filename, ext.lstrip("."), cu.content, emb_vector))

            stored_chunks += 1

    conn.commit()
    conn.close()
    return stored_chunks

# ── List & Delete Documents (Scoped) ──────────────────────────────────────────
def list_documents(user=None):
    if not HAS_PSYCOPG2:
        return []
    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            if user:
                user_id = user["id"]
                cur.execute("""
                    SELECT d.id, d.filename, d.title, d.category, d.authority, d.version, d.is_active,
                           COUNT(ku.id) AS chunk_count,
                           d.user_id, d.group_id, g.name AS group_name,
                           (d.user_id = %s) AS is_mine
                    FROM documents d
                    LEFT JOIN groups g ON d.group_id = g.id
                    LEFT JOIN knowledge_units ku ON d.id = ku.document_id AND ku.chunk_type = 'child'
                    WHERE d.user_id = %s 
                       OR d.user_id IS NULL
                       OR d.group_id IS NULL
                       OR d.group_id IN (
                           SELECT gm.group_id FROM group_members gm WHERE gm.user_id = %s
                       )
                       OR EXISTS (SELECT 1 FROM users u WHERE u.id = %s AND u.role = 'admin')
                    GROUP BY d.id, d.filename, d.title, d.category, d.authority, d.version, d.is_active, d.user_id, d.group_id, g.name
                    ORDER BY d.title ASC;
                """, (user_id, user_id, user_id, user_id))
            else:
                cur.execute("""
                    SELECT d.id, d.filename, d.title, d.category, d.authority, d.version, d.is_active,
                           COUNT(ku.id) AS chunk_count,
                           d.user_id, d.group_id, g.name AS group_name,
                           FALSE AS is_mine
                    FROM documents d
                    LEFT JOIN groups g ON d.group_id = g.id
                    LEFT JOIN knowledge_units ku ON d.id = ku.document_id AND ku.chunk_type = 'child'
                    WHERE g.name = 'Everyone' OR d.group_id IS NULL OR d.user_id IS NULL
                    GROUP BY d.id, d.filename, d.title, d.category, d.authority, d.version, d.is_active, d.user_id, d.group_id, g.name
                    ORDER BY d.title ASC;
                """)
            rows = cur.fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "source": r[1],
                "title": r[2],
                "category": r[3],
                "authority": r[4],
                "version": r[5],
                "is_active": r[6],
                "chunks": r[7],
                "user_id": r[8],
                "group_id": r[9],
                "group_name": r[10] or "Everyone",
                "is_mine": bool(r[11]),
                "file_type": os.path.splitext(r[1])[1].lstrip(".")
            } for r in rows
        ]
    except Exception as e:
        print(f"Error listing documents: {e}")
        return []

def delete_document(filename, user=None):
    if not HAS_PSYCOPG2:
        return False
    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            if user and user["role"] != "admin":
                cur.execute("SELECT id FROM documents WHERE filename = %s AND user_id = %s;", (filename, user["id"]))
                if not cur.fetchone():
                    conn.close()
                    return "forbidden"
            cur.execute("DELETE FROM documents WHERE filename = %s;", (filename,))
            cur.execute("DELETE FROM document_chunks WHERE source = %s;", (filename,))
        conn.commit()
        conn.close()

        filePath = os.path.join(KB_DIR, filename)
        if os.path.exists(filePath):
            os.remove(filePath)
        return True
    except Exception as e:
        print(f"Error deleting document {filename}: {e}")
        return False

# ── Parallel Hybrid Retrieval & Math-Based Deterministic Reranker ─────────────
def _query_dense_candidates(query_embedding, user_id, limit=20):
    if not query_embedding or len(query_embedding) != EMBED_DIM:
        return []
    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ku.id, ku.parent_id, ku.document_id, ku.unit_code, ku.entity_type,
                       ku.section_title, ku.content, ku.summary, ku.rules_json, ku.table_data_json,
                       d.filename AS source, d.title AS doc_title, d.authority, d.version,
                       ku.feedback_score,
                       (1 - (ku.embedding <=> %s::vector)) AS score
                FROM knowledge_units ku
                JOIN documents d ON ku.document_id = d.id
                WHERE ku.chunk_type = 'child'
                  AND d.is_active = TRUE
                  AND ku.embedding IS NOT NULL
                  AND (
                      d.user_id = %s
                      OR d.user_id IS NULL
                      OR d.group_id IS NULL
                      OR d.group_id IN (SELECT gm.group_id FROM group_members gm WHERE gm.user_id = %s)
                      OR EXISTS (SELECT 1 FROM users u WHERE u.id = %s AND u.role = 'admin')
                  )
                ORDER BY ku.embedding <=> %s::vector ASC
                LIMIT %s;
            """, (query_embedding, user_id, user_id, user_id, query_embedding, limit))
            rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"Dense Query Error: {e}")
        return []

def _query_sparse_candidates(query, user_id, limit=20):
    stop_words = {'what', 'are', 'the', 'is', 'a', 'an', 'in', 'on', 'for', 'and', 'with', 'from', 'about', 'tell', 'me', 'list', 'show', 'give', 'any', 'my', 'your', 'his', 'her', 'their', 'which', 'who', 'how', 'when', 'why', 'can', 'you', 'please'}
    words = [w.lower() for w in re.findall(r'\w+', query) if len(w) > 2 and w.lower() not in stop_words]
    clean_query = " ".join(words) if words else query.strip()
    heading_patterns = [f"%{w}%" for w in words] if words else [f"%{query.strip()}%"]
    content_like = f"%{words[0]}%" if words else f"%{query.strip()}%"

    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ku.id, ku.parent_id, ku.document_id, ku.unit_code, ku.entity_type,
                       ku.section_title, ku.content, ku.summary, ku.rules_json, ku.table_data_json,
                       d.filename AS source, d.title AS doc_title, d.authority, d.version,
                       ku.feedback_score,
                       (
                           ts_rank_cd(ku.tsv_content, plainto_tsquery('english', %s)) +
                           CASE WHEN ku.section_title ILIKE ANY(%s) THEN 0.6 ELSE 0.0 END
                       ) AS score
                FROM knowledge_units ku
                JOIN documents d ON ku.document_id = d.id
                WHERE ku.chunk_type = 'child'
                  AND d.is_active = TRUE
                  AND (
                      d.user_id = %s
                      OR d.user_id IS NULL
                      OR d.group_id IS NULL
                      OR d.group_id IN (SELECT gm.group_id FROM group_members gm WHERE gm.user_id = %s)
                      OR EXISTS (SELECT 1 FROM users u WHERE u.id = %s AND u.role = 'admin')
                  )
                  AND (
                      ku.tsv_content @@ plainto_tsquery('english', %s)
                      OR ku.section_title ILIKE ANY(%s)
                      OR ku.content ILIKE %s
                  )
                ORDER BY score DESC
                LIMIT %s;
            """, (clean_query, heading_patterns, user_id, user_id, user_id, clean_query, heading_patterns, content_like, limit))
            rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"Sparse Query Error: {e}")
        return []

def _format_ku_dict(r):
    return {
        "id": r[0],
        "parent_id": r[1],
        "unit_code": r[3],
        "entity_type": r[4],
        "section_title": r[5] or "General",
        "content": r[6],
        "summary": r[7] or "",
        "rules": r[8] if isinstance(r[8], list) else (json.loads(r[8]) if r[8] else []),
        "table_data": r[9] if isinstance(r[9], dict) else (json.loads(r[9]) if r[9] else None),
        "source": r[10],
        "doc_title": r[11],
        "authority": r[12],
        "version": r[13],
        "feedback_score": float(r[14]) if r[14] is not None else 0.0,
        "raw_score": round(float(r[15]) if len(r) > 15 and r[15] else 0.5, 3)
    }

def retrieve_context(query, user, top_k=TOP_K):
    if not HAS_PSYCOPG2 or not query:
        return []
    user_id = user["id"] if user else 1
    t0 = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_embed = executor.submit(get_embedding, query)
        future_sparse = executor.submit(_query_sparse_candidates, query, user_id, 20)

        sparse_rows = future_sparse.result()
        query_embedding = future_embed.result()

    dense_rows = _query_dense_candidates(query_embedding, user_id, 20)

    dense_ranks = {r[0]: idx for idx, r in enumerate(dense_rows, 1)}
    sparse_ranks = {r[0]: idx for idx, r in enumerate(sparse_rows, 1)}

    candidates = {}
    for r in dense_rows:
        candidates[r[0]] = _format_ku_dict(r)
    for r in sparse_rows:
        if r[0] not in candidates:
            candidates[r[0]] = _format_ku_dict(r)

    if not candidates:
        try:
            conn = get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ku.id, ku.parent_id, ku.document_id, ku.unit_code, ku.entity_type,
                           ku.section_title, ku.content, ku.summary, ku.rules_json, ku.table_data_json,
                           d.filename AS source, d.title AS doc_title, d.authority, d.version,
                           ku.feedback_score, 0.5 AS score
                    FROM knowledge_units ku
                    JOIN documents d ON ku.document_id = d.id
                    WHERE ku.chunk_type = 'child' AND d.is_active = TRUE
                      AND (
                          d.user_id = %s
                          OR d.user_id IS NULL
                          OR d.group_id IS NULL
                          OR d.group_id IN (SELECT gm.group_id FROM group_members gm WHERE gm.user_id = %s)
                          OR EXISTS (SELECT 1 FROM users u WHERE u.id = %s AND u.role = 'admin')
                      )
                    LIMIT 2;
                """, (user_id, user_id, user_id))
                fallback_rows = cur.fetchall()
            conn.close()
            return [_format_ku_dict(r) for r in fallback_rows]
        except Exception:
            return []

    K = 60
    query_lower = query.lower()
    for uid, item in candidates.items():
        r_d = dense_ranks.get(uid, 999)
        r_s = sparse_ranks.get(uid, 999)
        rrf = (1.0 / (K + r_d)) + (1.0 / (K + r_s))
        rrf_norm = rrf * 30.0

        fb_score = item.get("feedback_score", 0.0)
        fb_boost = math.tanh(fb_score / 3.0)

        content_lower = item.get("content", "").lower()
        title_lower = item.get("section_title", "").lower()
        exact_match = 0.15 if (query_lower in title_lower or query_lower in content_lower) else 0.0

        final_score = (1.0 * rrf_norm) + (0.25 * fb_boost) + (exact_match)
        item["rrf_score"] = round(rrf, 4)
        item["score"] = round(final_score, 3)
        item["final_score"] = round(final_score, 4)

    sorted_candidates = sorted(candidates.values(), key=lambda x: x["final_score"], reverse=True)
    t_total = int((time.time() - t0) * 1000)
    print(f"  [RETRIEVAL] {len(sorted_candidates)} candidates fused & math-reranked in {t_total}ms")
    return sorted_candidates[:top_k]

# ── High-Density Grounded Prompt with Full Context ────────────────────────────
def build_augmented_system(topic, okf_units):
    base = SYSTEM_PROMPTS.get(topic, SYSTEM_PROMPTS["general"])
    if not okf_units:
        return base

    context_blocks = []
    for i, unit in enumerate(okf_units[:3], 1):
        src_title = unit.get("doc_title") or unit.get("source")
        sec_title = unit.get("section_title", "Section")

        block = f"[DOCUMENT: {src_title} | SECTION: {sec_title}]\n"
        
        rules = unit.get("rules", [])
        if rules:
            for r in rules[:4]:
                thresh_str = f" [Limit: {r.get('threshold')}]" if r.get("threshold") else ""
                block += f"• Policy Rule: If {r.get('condition')} -> {r.get('action')}{thresh_str}\n"

        table_data = unit.get("table_data")
        if table_data and "headers" in table_data and "rows" in table_data:
            block += "Table: " + " | ".join(table_data["headers"]) + "\n"
            for row in table_data["rows"][:5]:
                block += " | ".join(row) + "\n"

        content_txt = unit.get('content', '').strip()
        block += f"Content:\n{content_txt}\n"
        context_blocks.append(block)

    joined_context = "\n---\n".join(context_blocks)

    return (
        f"{base}\n\n"
        f"### VERIFIED KNOWLEDGE BASE CONTEXT:\n"
        f"{joined_context}\n\n"
        f"### INSTRUCTIONS:\n"
        f"1. Answer the user's question directly, accurately, and thoroughly based on the verified context above.\n"
        f"2. When asked about projects, experience, or skills, list the exact items with technologies and details.\n"
        f"3. Always cite the document and section: `[Source: <Doc Title> > <Section Title>]`."
    )

# ── LLM Chat Callers (Streaming Generators) ───────────────────────────────────
def ollama_chat_stream(system_prompt, messages, model_name=OLLAMA_CHAT_MODEL):
    ollama_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages[-2:]:
        ollama_messages.append({
            "role": msg.get("role", "user"),
            "content": msg.get("content", "")
        })

    payload = json.dumps({
        "model": model_name,
        "messages": ollama_messages,
        "stream": True,
        "keep_alive": "30m",
        "options": {
            "temperature": 0.0,
            "num_predict": 800,
            "num_ctx": 4096
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        for line in resp:
            if line:
                chunk = json.loads(line.decode("utf-8"))
                msg = chunk.get("message", {})
                token = msg.get("content", "")
                if token:
                    yield token
                if chunk.get("done", False):
                    break

def gemini_chat_stream(system_prompt, messages, model="gemini-2.0-flash"):
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not configured in .env file.")

    contents = []
    for msg in messages:
        role = "user" if msg.get("role") == "user" else "model"
        contents.append({
            "role": role,
            "parts": [{"text": msg.get("content", "")}]
        })

    payload = json.dumps({
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 1000}
    }).encode("utf-8")

    url = f"{GEMINI_API_URL}/{model}:streamGenerateContent?key={GEMINI_API_KEY}"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        for line in resp:
            line_str = line.decode("utf-8").strip()
            if line_str.startswith("{") or line_str.startswith("["):
                try:
                    data = json.loads(line_str.strip(","))
                    if isinstance(data, dict):
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            for p in parts:
                                if "text" in p:
                                    yield p["text"]
                except Exception:
                    pass

def groq_chat_stream(system_prompt, messages, model="groq/compound-mini"):
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not configured in .env file.")

    api_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        api_messages.append({
            "role": msg.get("role", "user"),
            "content": msg.get("content", "")
        })

    payload = json.dumps({
        "model": model,
        "messages": api_messages,
        "temperature": 0.0,
        "max_tokens": 500,
        "stream": True
    }).encode("utf-8")

    req = urllib.request.Request(
        GROQ_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "User-Agent": "Mozilla/5.0"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        for line in resp:
            line_str = line.decode("utf-8").strip()
            if line_str.startswith("data: ") and line_str != "data: [DONE]":
                try:
                    data = json.loads(line_str[6:])
                    choices = data.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        if "content" in delta:
                            yield delta["content"]
                except Exception:
                    pass

def dispatch_chat_stream(provider, model_name, system_prompt, messages):
    if provider == "gemini":
        yield from gemini_chat_stream(system_prompt, messages, model=model_name)
    elif provider == "groq":
        yield from groq_chat_stream(system_prompt, messages, model=model_name)
    else:
        yield from ollama_chat_stream(system_prompt, messages, model_name=model_name)

def warm_up_model():
    if not WARMUP_ON_START:
        return
    try:
        dummy_system = "You are a verified knowledge assistant."
        dummy_messages = [{"role": "user", "content": "Hello"}]
        for _ in ollama_chat_stream(dummy_system, dummy_messages):
            pass
        print("  WARM-UP: Ollama model loaded successfully.")
    except Exception as e:
        print(f"  WARM-UP note: {e}")

# ── Standalone Query Resolution ───────────────────────────────────────────────
def generate_standalone_query(messages, provider="ollama", model_name=OLLAMA_CHAT_MODEL):
    if not messages:
        return ""
    latest_query = messages[-1].get("content", "").strip()
    if len(messages) <= 1:
        return latest_query

    words = latest_query.split()
    if len(words) <= 5 and any(w.lower() in {"it", "this", "that", "them", "what", "how", "and", "why", "who", "when"} for w in words):
        for msg in reversed(messages[:-1]):
            if msg.get("role") == "user":
                prior = msg.get("content", "").strip()
                prior_summary = " ".join(prior.split()[:8])
                return f"{prior_summary} {latest_query}"

    return latest_query

# ── HTTP Request Handler ──────────────────────────────────────────────────────
class AcademiqHandler(http.server.SimpleHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"  [{self.address_string()}] {format % args}")

    def send_json(self, status, data, cookie=None):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/status":
            self.handle_status()
        elif self.path == "/api/documents":
            self.handle_list_documents()
        elif self.path == "/api/models":
            self.handle_models()
        elif self.path == "/api/auth/me":
            self.handle_auth_me()
        elif self.path == "/api/groups":
            self.handle_list_groups()
        elif self.path == "/api/admin/stats":
            self.handle_admin_stats()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/chat":
            self.handle_chat()
        elif self.path == "/api/upload":
            self.handle_upload()
        elif self.path == "/api/delete_document":
            self.handle_delete_document()
        elif self.path == "/api/feedback":
            self.handle_feedback()
        elif self.path == "/api/auth/signup":
            self.handle_signup()
        elif self.path == "/api/auth/login":
            self.handle_login()
        elif self.path == "/api/auth/logout":
            self.handle_logout()
        elif self.path == "/api/groups":
            self.handle_create_group()
        elif self.path == "/api/groups/members":
            self.handle_add_group_member()
        else:
            self.send_response(404)
            self.end_headers()

    # ── Auth Handlers ──
    def handle_auth_me(self):
        user = get_authenticated_user(self.headers)
        if user:
            self.send_json(200, {"authenticated": True, "user": user})
        else:
            self.send_json(401, {"authenticated": False, "error": "Not authenticated"})

    def handle_signup(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            username = payload.get("username", "").strip()
            password = payload.get("password", "").strip()

            if not username or not password:
                self.send_json(400, {"error": {"message": "Username and password are required."}})
                return
            if len(username) < 3 or not re.match(r'^[a-zA-Z0-9_\-]+$', username):
                self.send_json(400, {"error": {"message": "Username must be at least 3 characters (letters, numbers, underscores, hyphens)."}})
                return
            if len(password) < 6:
                self.send_json(400, {"error": {"message": "Password must be at least 6 characters."}})
                return

            hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")

            conn = get_db_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE username = %s;", (username,))
                if cur.fetchone():
                    conn.close()
                    self.send_json(400, {"error": {"message": "Username already exists."}})
                    return

                # Public signup always enforces role = 'user'
                cur.execute("""
                    INSERT INTO users (username, password_hash, role)
                    VALUES (%s, %s, 'user')
                    RETURNING id, role;
                """, (username, hashed))
                row = cur.fetchone()
                user_id, role = row[0], row[1]

                # Automatically enroll new user into Everyone group
                cur.execute("SELECT id FROM groups WHERE name = 'Everyone' LIMIT 1;")
                grp_row = cur.fetchone()
                if grp_row:
                    cur.execute("""
                        INSERT INTO group_members (group_id, user_id)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING;
                    """, (grp_row[0], user_id))

            conn.commit()
            conn.close()

            token = create_session(user_id)
            cookie = f"session_token={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800"
            self.send_json(200, {
                "success": True,
                "user": {"id": user_id, "username": username, "role": role}
            }, cookie=cookie)
        except Exception as e:
            self.send_json(500, {"error": {"message": str(e)}})

    def handle_login(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            username = payload.get("username", "").strip()
            password = payload.get("password", "").strip()

            if not username or not password:
                self.send_json(400, {"error": {"message": "Username and password required."}})
                return

            conn = get_db_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT id, password_hash, role FROM users WHERE username = %s;", (username,))
                row = cur.fetchone()
            conn.close()

            if not row or not bcrypt.checkpw(password.encode("utf-8"), row[1].encode("utf-8")):
                self.send_json(401, {"error": {"message": "Invalid username or password."}})
                return

            user_id, role = row[0], row[2]
            token = create_session(user_id)
            cookie = f"session_token={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800"
            self.send_json(200, {
                "success": True,
                "user": {"id": user_id, "username": username, "role": role}
            }, cookie=cookie)
        except Exception as e:
            self.send_json(500, {"error": {"message": str(e)}})

    def handle_logout(self):
        cookie_header = self.headers.get("Cookie", "")
        token = None
        if "session_token=" in cookie_header:
            for part in cookie_header.split(";"):
                if part.strip().startswith("session_token="):
                    token = part.strip().split("=", 1)[1]
                    break
        delete_session(token)
        cookie = "session_token=; Path=/; HttpOnly; Max-Age=0"
        self.send_json(200, {"success": True}, cookie=cookie)

    # ── Groups Handlers ──
    def handle_list_groups(self):
        user = get_authenticated_user(self.headers)
        if not user:
            self.send_json(401, {"error": {"message": "Authentication required."}})
            return

        try:
            conn = get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT g.id, g.name, g.is_system, g.created_by,
                           COUNT(gm.user_id) AS member_count,
                           (g.created_by = %s OR %s = 'admin') AS can_manage
                    FROM groups g
                    JOIN group_members gm_user ON g.id = gm_user.group_id AND gm_user.user_id = %s
                    LEFT JOIN group_members gm ON g.id = gm.group_id
                    GROUP BY g.id, g.name, g.is_system, g.created_by
                    ORDER BY g.is_system DESC, g.name ASC;
                """, (user["id"], user["role"], user["id"]))
                rows = cur.fetchall()
            conn.close()

            groups = [
                {
                    "id": r[0],
                    "name": r[1],
                    "is_system": r[2],
                    "created_by": r[3],
                    "member_count": r[4],
                    "can_manage": r[5]
                } for r in rows
            ]
            self.send_json(200, {"groups": groups})
        except Exception as e:
            self.send_json(500, {"error": {"message": str(e)}})

    def handle_create_group(self):
        user = get_authenticated_user(self.headers)
        if not user:
            self.send_json(401, {"error": {"message": "Authentication required."}})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            name = payload.get("name", "").strip()

            if not name:
                self.send_json(400, {"error": {"message": "Group name is required."}})
                return

            conn = get_db_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO groups (name, is_system, created_by)
                    VALUES (%s, FALSE, %s)
                    RETURNING id;
                """, (name, user["id"]))
                group_id = cur.fetchone()[0]

                cur.execute("""
                    INSERT INTO group_members (group_id, user_id)
                    VALUES (%s, %s);
                """, (group_id, user["id"]))
            conn.commit()
            conn.close()

            self.send_json(200, {"success": True, "group": {"id": group_id, "name": name}})
        except Exception as e:
            self.send_json(500, {"error": {"message": str(e)}})

    def handle_add_group_member(self):
        user = get_authenticated_user(self.headers)
        if not user:
            self.send_json(401, {"error": {"message": "Authentication required."}})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            group_id = payload.get("group_id")
            username = payload.get("username", "").strip()

            if not group_id or not username:
                self.send_json(400, {"error": {"message": "Group ID and username are required."}})
                return

            conn = get_db_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT created_by, is_system FROM groups WHERE id = %s;", (group_id,))
                grp = cur.fetchone()
                if not grp:
                    conn.close()
                    self.send_json(404, {"error": {"message": "Group not found."}})
                    return

                if grp[0] != user["id"] and user["role"] != "admin":
                    conn.close()
                    self.send_json(403, {"error": {"message": "Only group creator or admin can add members."}})
                    return

                cur.execute("SELECT id FROM users WHERE username = %s;", (username,))
                target_user = cur.fetchone()
                if not target_user:
                    conn.close()
                    self.send_json(404, {"error": {"message": f"User '{username}' not found."}})
                    return

                cur.execute("""
                    INSERT INTO group_members (group_id, user_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING;
                """, (group_id, target_user[0]))
            conn.commit()
            conn.close()

            self.send_json(200, {"success": True, "message": f"Added '{username}' to group."})
        except Exception as e:
            self.send_json(500, {"error": {"message": str(e)}})

    # ── Admin Dashboard Handler ──
    def handle_admin_stats(self):
        user = get_authenticated_user(self.headers)
        if not user or user["role"] != "admin":
            self.send_json(403, {"error": {"message": "Admin privileges required."}})
            return

        try:
            conn = get_db_conn()
            with conn.cursor() as cur:
                # 1. Overall Feedback
                cur.execute("""
                    SELECT 
                        COUNT(*) AS total_feedback,
                        COALESCE(SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END), 0) AS upvotes,
                        COALESCE(SUM(CASE WHEN rating = -1 THEN 1 ELSE 0 END), 0) AS downvotes,
                        ROUND(COALESCE(SUM(CASE WHEN rating = 1 THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0) * 100, 0), 1) AS satisfaction_rate
                    FROM feedback_logs;
                """)
                ov = cur.fetchone()
                overall = {
                    "total": ov[0] or 0,
                    "upvotes": ov[1] or 0,
                    "downvotes": ov[2] or 0,
                    "satisfaction_rate": float(ov[3]) if ov[3] is not None else 0.0
                }

                # 2. Per-Document Breakdown
                cur.execute("""
                    SELECT 
                        d.id AS document_id,
                        d.title AS document_title,
                        d.filename,
                        d.category,
                        COUNT(fl.id) AS total_feedback_events,
                        SUM(CASE WHEN fl.rating = 1 THEN 1 ELSE 0 END) AS upvotes,
                        SUM(CASE WHEN fl.rating = -1 THEN 1 ELSE 0 END) AS downvotes,
                        ROUND(SUM(CASE WHEN fl.rating = 1 THEN 1.0 ELSE 0.0 END) / COUNT(fl.id) * 100, 1) AS doc_satisfaction_rate,
                        ROUND(AVG(ku.feedback_score)::numeric, 2) AS avg_chunk_score
                    FROM feedback_logs fl
                    CROSS JOIN LATERAL unnest(string_to_array(fl.retrieved_unit_ids, ',')::int[]) AS unit_id
                    JOIN knowledge_units ku ON ku.id = unit_id
                    JOIN documents d ON ku.document_id = d.id
                    GROUP BY d.id, d.title, d.filename, d.category
                    ORDER BY total_feedback_events DESC, doc_satisfaction_rate ASC;
                """)
                doc_rows = cur.fetchall()
                documents = [
                    {
                        "id": r[0],
                        "title": r[1],
                        "filename": r[2],
                        "category": r[3],
                        "total_events": r[4],
                        "upvotes": r[5],
                        "downvotes": r[6],
                        "satisfaction_rate": float(r[7]) if r[7] is not None else 0.0,
                        "avg_chunk_score": float(r[8]) if r[8] is not None else 0.0
                    } for r in doc_rows
                ]

                # 3. Per-Category Breakdown
                cur.execute("""
                    SELECT 
                        d.category,
                        COUNT(fl.id) AS category_feedback_count,
                        SUM(CASE WHEN fl.rating = 1 THEN 1 ELSE 0 END) AS upvotes,
                        SUM(CASE WHEN fl.rating = -1 THEN 1 ELSE 0 END) AS downvotes,
                        ROUND(SUM(CASE WHEN fl.rating = 1 THEN 1.0 ELSE 0.0 END) / COUNT(fl.id) * 100, 1) AS category_satisfaction_rate
                    FROM feedback_logs fl
                    CROSS JOIN LATERAL unnest(string_to_array(fl.retrieved_unit_ids, ',')::int[]) AS unit_id
                    JOIN knowledge_units ku ON ku.id = unit_id
                    JOIN documents d ON ku.document_id = d.id
                    GROUP BY d.category
                    ORDER BY category_satisfaction_rate ASC;
                """)
                cat_rows = cur.fetchall()
                categories = [
                    {
                        "category": r[0],
                        "total_events": r[1],
                        "upvotes": r[2],
                        "downvotes": r[3],
                        "satisfaction_rate": float(r[4]) if r[4] is not None else 0.0
                    } for r in cat_rows
                ]

            conn.close()
            self.send_json(200, {
                "overall": overall,
                "documents": documents,
                "categories": categories
            })
        except Exception as e:
            self.send_json(500, {"error": {"message": str(e)}})

    # ── Status & Models ──
    def handle_status(self):
        user = get_authenticated_user(self.headers)
        ollama_ok = check_ollama()
        db_ok     = check_db()
        redis_ok  = check_redis()
        docs      = list_documents(user=user)
        self.send_json(200, {
            "ollama": ollama_ok,
            "db": db_ok,
            "redis": redis_ok,
            "doc_count": len(docs),
            "chat_model": OLLAMA_CHAT_MODEL,
            "embed_model": OLLAMA_EMBED_MODEL,
            "okf_enabled": True,
            "ready": ollama_ok and db_ok,
            "user": user
        })

    def handle_models(self):
        providers = {}
        try:
            req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                ollama_models = [m.get("name", "") for m in data.get("models", [])]
                ollama_models = [m for m in ollama_models if OLLAMA_EMBED_MODEL.split(":")[0] not in m]
                if ollama_models:
                    providers["ollama"] = {"models": ollama_models, "label": "Ollama (Local)", "icon": "cpu"}
        except Exception:
            providers["ollama"] = {"models": [OLLAMA_CHAT_MODEL], "label": "Ollama (Local)", "icon": "cpu"}

        if GEMINI_API_KEY:
            providers["gemini"] = {"models": GEMINI_MODELS, "label": "Google Gemini", "icon": "sparkles"}

        if GROQ_API_KEY:
            providers["groq"] = {"models": GROQ_MODELS, "label": "Groq Cloud (Ultra Fast)", "icon": "bolt"}

        self.send_json(200, {
            "providers": providers,
            "default": f"ollama/{OLLAMA_CHAT_MODEL}"
        })

    def handle_list_documents(self):
        user = get_authenticated_user(self.headers)
        docs = list_documents(user=user)
        self.send_json(200, {"documents": docs})

    def handle_delete_document(self):
        user = get_authenticated_user(self.headers)
        if not user:
            self.send_json(401, {"error": {"message": "Authentication required."}})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            filename = payload.get("filename", "")
            if not filename:
                self.send_json(400, {"error": {"message": "Filename required."}})
                return

            res = delete_document(filename, user=user)
            if res == "forbidden":
                self.send_json(403, {"error": {"message": "You do not have permission to delete this document."}})
            elif res:
                self.send_json(200, {"success": True, "filename": filename})
            else:
                self.send_json(500, {"error": {"message": "Failed to delete document."}})
        except Exception as e:
            self.send_json(500, {"error": {"message": str(e)}})

    def handle_upload(self):
        user = get_authenticated_user(self.headers)
        if not user:
            self.send_json(401, {"error": {"message": "Authentication required to upload documents."}})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            filename = payload.get("filename", "")
            base64_data = payload.get("data", "")
            group_id = payload.get("group_id")

            if not filename or not base64_data:
                self.send_json(400, {"error": {"message": "Filename and file data are required."}})
                return

            if group_id:
                try:
                    group_id = int(group_id)
                except ValueError:
                    group_id = None

            if group_id:
                conn = get_db_conn()
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 1 FROM group_members WHERE group_id = %s AND user_id = %s;
                    """, (group_id, user["id"]))
                    if not cur.fetchone() and user["role"] != "admin":
                        conn.close()
                        self.send_json(403, {"error": {"message": "You are not a member of the selected group."}})
                        return
                conn.close()

            if "," in base64_data:
                base64_data = base64_data.split(",", 1)[1]

            file_bytes = base64.b64decode(base64_data)
            print(f"\n  OKF UPLOAD: Processing '{filename}' ({len(file_bytes)} bytes) by user {user['username']}...")

            chunks_stored = process_uploaded_file(filename, file_bytes, user_id=user["id"], group_id=group_id)
            print(f"  OKF UPLOAD: Successfully structured & stored {chunks_stored} knowledge unit(s) for '{filename}'.")

            self.send_json(200, {
                "success": True,
                "filename": filename,
                "chunks": chunks_stored,
                "message": f"Successfully extracted & indexed {chunks_stored} OKF Knowledge Units."
            })
        except Exception as e:
            print(f"  UPLOAD ERROR: {e}")
            self.send_json(500, {"error": {"message": f"Upload failed: {str(e)}"}})

    def handle_feedback(self):
        user = get_authenticated_user(self.headers)
        user_id = user["id"] if user else None

        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))

            query = payload.get("query", "")
            response_text = payload.get("response", "")
            rating = int(payload.get("rating", 0))
            notes = payload.get("notes", "")
            unit_ids_raw = payload.get("unit_ids", "")
            model_name = payload.get("model", "")

            if not HAS_PSYCOPG2:
                self.send_json(200, {"status": "skipped", "message": "Database not connected"})
                return

            delta = 1.0 if rating > 0 else -1.0
            parsed_unit_ids = []
            if unit_ids_raw:
                for uid in str(unit_ids_raw).split(","):
                    uid = uid.strip()
                    if uid.isdigit():
                        parsed_unit_ids.append(int(uid))

            conn = get_db_conn()
            with conn.cursor() as cur:
                # 1. Update feedback_score on verified permitted knowledge units
                if parsed_unit_ids and user_id:
                    cur.execute("""
                        UPDATE knowledge_units ku
                        SET feedback_score = GREATEST(-10.0, LEAST(10.0, ku.feedback_score + %s))
                        FROM documents d
                        WHERE ku.document_id = d.id
                          AND ku.id = ANY(%s)
                          AND (
                              d.user_id = %s
                              OR d.group_id IN (SELECT gm.group_id FROM group_members gm WHERE gm.user_id = %s)
                          );
                    """, (delta, parsed_unit_ids, user_id, user_id))
                elif parsed_unit_ids:
                    cur.execute("""
                        UPDATE knowledge_units ku
                        SET feedback_score = GREATEST(-10.0, LEAST(10.0, ku.feedback_score + %s))
                        FROM documents d
                        JOIN groups g ON d.group_id = g.id
                        WHERE ku.document_id = d.id
                          AND ku.id = ANY(%s)
                          AND g.name = 'Everyone';
                    """, (delta, parsed_unit_ids))

                # 2. Insert into feedback_logs
                cur.execute("""
                    INSERT INTO feedback_logs (user_id, query, response, rating, feedback_notes, retrieved_unit_ids, model)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                """, (user_id, query, response_text, rating, notes, str(unit_ids_raw), model_name))

            conn.commit()
            conn.close()

            print(f"  [FEEDBACK LOGGED] Rating: {rating} for query '{query[:40]}...'")
            self.send_json(200, {"status": "success", "message": "Feedback recorded & scores updated."})
        except Exception as e:
            print(f"  [FEEDBACK ERROR] {e}")
            self.send_json(500, {"error": {"message": str(e)}})

    # ── Token Streaming Chat Handler ──
    def handle_chat(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as e:
            self.send_json(400, {"error": {"message": f"Invalid JSON: {e}"}})
            return

        user = get_authenticated_user(self.headers)
        messages  = payload.get("messages", [])
        topic     = payload.get("topic", "general")
        selected_model = payload.get("model", f"ollama/{OLLAMA_CHAT_MODEL}")
        user_text = messages[-1].get("content", "") if messages else ""

        if "/" in selected_model:
            provider, model_name = selected_model.split("/", 1)
        else:
            provider, model_name = "ollama", selected_model

        if not user_text:
            self.send_json(400, {"error": {"message": "No message content."}})
            return

        client_ip = self.client_address[0] if hasattr(self, 'client_address') else "127.0.0.1"
        if is_rate_limited(client_ip):
            self.send_json(429, {"error": {"message": "Rate limit exceeded. Please wait a minute before sending more messages."}})
            return

        username = user["username"] if user else "Anonymous"
        print(f"\n  USER [{username} | {topic}]: {user_text[:80]}...")

        search_query = generate_standalone_query(messages, provider=provider, model_name=model_name)

        rag_start = time.time()
        okf_units = retrieve_context(search_query, user=user)
        rag_ms = int((time.time() - rag_start) * 1000)
        sources = list({u["doc_title"] or u["source"] for u in okf_units})

        system = build_augmented_system(topic, okf_units)

        rag_details = [
            {
                "id": u["id"],
                "source": u["source"],
                "doc_title": u["doc_title"],
                "section_title": u["section_title"],
                "entity_type": u["entity_type"],
                "authority": u["authority"],
                "version": u["version"],
                "content": u["content"],
                "summary": u["summary"],
                "rules": u["rules"],
                "table_data": u["table_data"],
                "score": u.get("score", 0.5),
                "rrf_score": u.get("rrf_score", 0.0),
                "final_score": u.get("final_score", 0.0),
                "feedback_score": u.get("feedback_score", 0.0)
            } for u in okf_units
        ]

        # Initiate Server-Sent Events stream
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.close_connection = True

        # Send initial metadata chunk
        meta_chunk = json.dumps({
            "sources": sources,
            "rag_details": rag_details,
            "model": f"{provider}/{model_name}",
            "_timings": {"rag_ms": rag_ms}
        })
        self.wfile.write(f"data: {meta_chunk}\n\n".encode("utf-8"))
        self.wfile.flush()

        # Stream generated tokens
        full_reply = []
        try:
            for token in dispatch_chat_stream(provider, model_name, system, messages):
                full_reply.append(token)
                token_chunk = json.dumps({"token": token})
                self.wfile.write(f"data: {token_chunk}\n\n".encode("utf-8"))
                self.wfile.flush()
        except Exception as e:
            err_chunk = json.dumps({"token": f"\n\n⚠️ AI Error: {str(e)}"})
            self.wfile.write(f"data: {err_chunk}\n\n".encode("utf-8"))
            self.wfile.flush()

        # Send completion marker
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


# ── MIME types fix for Windows ────────────────────────────────────────────────
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

socketserver.TCPServer.allow_reuse_address = True

if __name__ == "__main__":
    init_db_schema_if_needed()
    ollama_ok = check_ollama()
    db_ok     = check_db()
    redis_ok  = check_redis()

    handler = AcademiqHandler
    with socketserver.ThreadingTCPServer(("", PORT), handler) as httpd:
        warm_up_model()
        print("\n" + "="*55)
        print("  AcademiQ — Institutional AI Knowledge Platform")
        print(f"  Open: http://localhost:{PORT}")
        print("="*55)
        print(f"  OKF Hybrid Search Engine:    [OK] Parallel + Math Rerank")
        print(f"  Ollama ({OLLAMA_CHAT_MODEL}): {'[OK] Ready' if ollama_ok else '[FAIL] Not found — start Ollama'}")
        print(f"  pgvector DB:                 {'[OK] Ready' if db_ok else '[FAIL] Not found — run setup_db.py first'}")
        print(f"  Redis Cache:                 {'[OK] Ready' if redis_ok else '[OPTIONAL] Offline'}")
        print(f"  Gemini API:                  {'[OK] Key configured' if GEMINI_API_KEY else '[SKIP] No key in .env'}")
        print(f"  Groq API:                    {'[OK] Key configured' if GROQ_API_KEY else '[SKIP] No key in .env'}")
        print("="*55 + "\n")

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Shutting down AcademiQ server...")
