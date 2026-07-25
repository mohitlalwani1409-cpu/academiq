#!/usr/bin/env python3
"""
AcademiQ — Database Setup & Document Ingestion
Run this ONCE (or re-run to re-ingest) after starting the pgvector Docker container.

Usage:
    python setup_db.py

Supports: .txt  .md  .html  .htm  .pdf
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

# ── Configuration ─────────────────────────────────────────────────────────────
PG_HOST          = "localhost"
PG_PORT          = 5433          # Docker maps container 5432 → host 5433
PG_DB            = "academiq"
PG_USER          = "postgres"
PG_PASS          = "postgres"

OLLAMA_BASE_URL  = "http://localhost:11434"
EMBED_MODEL      = "nomic-embed-text"
EMBED_DIM        = 768

KB_DIR           = "knowledge_base"
CHUNK_SIZE       = 500   # characters per chunk (approx)
CHUNK_OVERLAP    = 80    # characters of overlap between chunks

SUPPORTED_EXTS   = {".txt", ".md", ".html", ".htm", ".pdf"}

# ── Text extraction ───────────────────────────────────────────────────────────
def extract_text_txt(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def extract_text_md(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    # Strip markdown headers/decorators but keep content
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)
    return text

def extract_text_html(path):
    if not HAS_BS4:
        return None
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f.read(), "lxml")
    # Remove scripts and styles
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

# ── Chunking ──────────────────────────────────────────────────────────────────
def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Split text into overlapping character-based chunks."""
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        # Try to break at a sentence boundary
        if end < len(text):
            for sep in ["\n\n", ". ", "\n", " "]:
                idx = text.rfind(sep, start, end)
                if idx != -1 and idx > start + overlap:
                    end = idx + len(sep)
                    break
        chunk = text[start:end].strip()
        if len(chunk) >= 40:   # skip tiny fragments
            chunks.append(chunk)
        start = end - overlap
    return chunks

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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id        SERIAL PRIMARY KEY,
                source    TEXT NOT NULL,
                file_type TEXT NOT NULL,
                content   TEXT NOT NULL,
                embedding VECTOR(%s)
            );
        """, (EMBED_DIM,))
        # IVFFlat index for fast cosine search
        cur.execute("""
            CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx
            ON document_chunks
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 10);
        """)
    conn.commit()
    print("[OK] Database schema ready.")

def clear_table(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM document_chunks;")
    conn.commit()
    print("[OK] Cleared existing chunks.")

def insert_chunk(conn, source, file_type, content, embedding):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO document_chunks (source, file_type, content, embedding) VALUES (%s, %s, %s, %s);",
            (source, file_type, content, embedding)
        )
    conn.commit()

# ── Main ingestion ────────────────────────────────────────────────────────────
def ingest():
    print("\n" + "="*50)
    print("  AcademiQ - Knowledge Base Ingestion")
    print("="*50)

    # 1. Check Ollama
    print("\n[1/4] Checking Ollama...")
    if not check_ollama():
        print("ERROR: Ollama is not running or model not pulled.")
        print("Start Ollama, then run:  ollama pull nomic-embed-text")
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
    print("\n[3/4] Setting up schema...")
    setup_schema(conn)
    clear_table(conn)

    # 4. Ingest files
    print(f"\n[4/4] Ingesting files from '{KB_DIR}/'...")
    if not os.path.exists(KB_DIR):
        print(f"  ERROR: '{KB_DIR}/' directory not found.")
        sys.exit(1)

    total_chunks = 0
    total_files  = 0

    for filename in sorted(os.listdir(KB_DIR)):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTS:
            continue

        path = os.path.join(KB_DIR, filename)
        print(f"\n  -> {filename} ({ext})")

        text = extract_text(path, ext)
        if not text or not text.strip():
            print("    SKIP: No text extracted.")
            continue

        chunks = chunk_text(text)
        print(f"    {len(chunks)} chunk(s) to embed...")

        file_chunks = 0
        for i, chunk in enumerate(chunks):
            embedding = get_embedding(chunk)
            if not embedding or len(embedding) != EMBED_DIM:
                print(f"    WARNING: Bad embedding for chunk {i+1}, skipping.")
                continue
            insert_chunk(conn, filename, ext.lstrip("."), chunk, embedding)
            file_chunks += 1
            print(f"    [OK] chunk {i+1}/{len(chunks)} embedded & stored", end="\r")

        print(f"    [OK] {file_chunks} chunks stored from {filename}    ")
        total_chunks += file_chunks
        total_files  += 1

    conn.close()

    print("\n" + "="*50)
    print(f"  DONE: {total_chunks} chunks from {total_files} file(s)")
    print("  You can now start the server: python server.py")
    print("="*50 + "\n")

if __name__ == "__main__":
    ingest()
