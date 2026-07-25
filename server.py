#!/usr/bin/env python3
"""
AcademiQ — Local AI Server
Uses Ollama (llama3.2:3b) for chat + PostgreSQL/pgvector for semantic RAG.
Supports direct file uploads via web UI.

Run:  python server.py
Open: http://localhost:3000
"""

import http.server
import socketserver
import urllib.request
import urllib.error
import json
import os
import mimetypes
import re
import base64
import io

PORT = 3000

# ── Configuration ─────────────────────────────────────────────────────────────
OLLAMA_BASE_URL  = "http://localhost:11434"
OLLAMA_CHAT_MODEL  = "llama3.2:3b"
OLLAMA_EMBED_MODEL = "nomic-embed-text"
EMBED_DIM        = 768

PG_HOST = "localhost"
PG_PORT = 5433          # Docker container mapped to host port 5433
PG_DB   = "academiq"
PG_USER = "postgres"
PG_PASS = "postgres"

TOP_K   = 3    # Number of RAG chunks to retrieve per query
KB_DIR  = "knowledge_base"
CHUNK_SIZE    = 500
CHUNK_OVERLAP = 80

# ── Optional imports ──────────────────────────────────────────────────────────
try:
    import psycopg2
    from pgvector.psycopg2 import register_vector
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

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
        "You are AcademiQ, a friendly and knowledgeable academic advisor. "
        "You help students with study strategies, exams, majors, careers, writing, and wellbeing. "
        "Keep responses helpful, encouraging, and concise (2-4 short paragraphs). "
        "Use plain language. Be warm and supportive."
    ),
    "study": (
        "You are AcademiQ, specializing in study strategies and time management for students. "
        "You help with study schedules, focus techniques, memory methods (spaced repetition, "
        "active recall, Pomodoro), and productivity habits. "
        "Give practical, actionable advice. Keep responses concise and encouraging."
    ),
    "exams": (
        "You are AcademiQ, an expert in exam preparation and test-taking strategies. "
        "You help students with revision planning, managing exam anxiety, understanding question types, "
        "time management during tests, and post-exam reflection. "
        "Be specific and practical. Keep responses concise."
    ),
    "career": (
        "You are AcademiQ, a career and major selection advisor for students. "
        "You help students explore majors, understand career pathways, evaluate job markets, "
        "prepare for internships, and think through graduate school. "
        "Ask clarifying questions when needed. Be balanced and encouraging."
    ),
    "writing": (
        "You are AcademiQ, specializing in academic writing and research. "
        "You help with essay structure, thesis statements, research methods, "
        "citations (APA, MLA, Chicago), editing techniques, and overcoming writer's block. "
        "Give concrete examples when helpful. Keep responses practical and clear."
    ),
    "stress": (
        "You are AcademiQ, focused on student wellbeing and managing academic stress. "
        "You help with burnout recovery, work-life balance, motivation, imposter syndrome, "
        "and building healthy habits. Be empathetic and supportive. "
        "Remind students that their wellbeing matters more than grades when appropriate."
    ),
}

# ── Health checks ─────────────────────────────────────────────────────────────
def check_ollama():
    """Return True if Ollama is reachable and both models are available."""
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

def check_db():
    """Return True if PostgreSQL + pgvector is reachable and has data."""
    if not HAS_PSYCOPG2:
        return False
    try:
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, dbname=PG_DB,
            user=PG_USER, password=PG_PASS,
            connect_timeout=3
        )
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM document_chunks;")
            count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False

# ── Document Parsing & Chunking ────────────────────────────────────────────────
def extract_text_from_bytes(file_bytes, filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in (".txt",):
        return file_bytes.decode("utf-8", errors="ignore")
    elif ext == ".md":
        text = file_bytes.decode("utf-8", errors="ignore")
        text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
        text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)
        return text
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
        # Default fallback text decode
        return file_bytes.decode("utf-8", errors="ignore")

def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        if end < len(text):
            for sep in ["\n\n", ". ", "\n", " "]:
                idx = text.rfind(sep, start, end)
                if idx != -1 and idx > start + overlap:
                    end = idx + len(sep)
                    break
        chunk = text[start:end].strip()
        if len(chunk) >= 40:
            chunks.append(chunk)
        start = end - overlap
    return chunks

# ── Embedding ─────────────────────────────────────────────────────────────────
def get_embedding(text):
    payload = json.dumps({
        "model": OLLAMA_EMBED_MODEL,
        "prompt": text
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("embedding", [])

# ── Ingest single uploaded file ───────────────────────────────────────────────
def process_uploaded_file(filename, file_bytes):
    if not HAS_PSYCOPG2:
        raise ValueError("PostgreSQL driver (psycopg2) is not available.")

    # 1. Save to knowledge_base directory
    os.makedirs(KB_DIR, exist_ok=True)
    save_path = os.path.join(KB_DIR, filename)
    with open(save_path, "wb") as f:
        f.write(file_bytes)

    # 2. Extract text & chunk
    ext  = os.path.splitext(filename)[1].lower()
    text = extract_text_from_bytes(file_bytes, filename)
    if not text or not text.strip():
        raise ValueError("No readable text could be extracted from file.")

    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("File text is too short or empty after processing.")

    # 3. Connect DB & setup schema if needed
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB,
        user=PG_USER, password=PG_PASS
    )
    register_vector(conn)

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
        # Remove any prior chunks for this filename
        cur.execute("DELETE FROM document_chunks WHERE source = %s;", (filename,))
    conn.commit()

    # 4. Generate embeddings and insert
    stored_chunks = 0
    for chunk in chunks:
        embedding = get_embedding(chunk)
        if embedding and len(embedding) == EMBED_DIM:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO document_chunks (source, file_type, content, embedding) VALUES (%s, %s, %s, %s);",
                    (filename, ext.lstrip("."), chunk, embedding)
                )
            conn.commit()
            stored_chunks += 1

    conn.close()
    return stored_chunks

def list_documents():
    if not HAS_PSYCOPG2:
        return []
    try:
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, dbname=PG_DB,
            user=PG_USER, password=PG_PASS
        )
        with conn.cursor() as cur:
            cur.execute("""
                SELECT source, file_type, COUNT(*) as chunks
                FROM document_chunks
                GROUP BY source, file_type
                ORDER BY source ASC;
            """)
            rows = cur.fetchall()
        conn.close()
        return [{"source": r[0], "file_type": r[1], "chunks": r[2]} for r in rows]
    except Exception as e:
        print(f"Error listing documents: {e}")
        return []

def delete_document(filename):
    if not HAS_PSYCOPG2:
        return False
    try:
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, dbname=PG_DB,
            user=PG_USER, password=PG_PASS
        )
        with conn.cursor() as cur:
            cur.execute("DELETE FROM document_chunks WHERE source = %s;", (filename,))
        conn.commit()
        conn.close()

        # Delete from disk if present
        filePath = os.path.join(KB_DIR, filename)
        if os.path.exists(filePath):
            os.remove(filePath)
        return True
    except Exception as e:
        print(f"Error deleting document {filename}: {e}")
        return False

# ── Semantic RAG retrieval ────────────────────────────────────────────────────
def retrieve_context(query, top_k=TOP_K):
    if not HAS_PSYCOPG2:
        return []
    try:
        embedding = get_embedding(query)
        if not embedding:
            return []

        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, dbname=PG_DB,
            user=PG_USER, password=PG_PASS
        )
        register_vector(conn)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT source, file_type, content,
                       1 - (embedding <=> %s::vector) AS score
                FROM document_chunks
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
            """, (embedding, embedding, top_k))
            rows = cur.fetchall()
        conn.close()

        results = []
        for source, file_type, content, score in rows:
            if score >= 0.3:  # only use sufficiently relevant chunks
                results.append({
                    "source": source,
                    "file_type": file_type,
                    "content": content,
                    "score": score
                })
        return results
    except Exception as e:
        print(f"RAG retrieval error: {e}")
        return []

# ── Build augmented system prompt ─────────────────────────────────────────────
def build_augmented_system(topic, rag_chunks):
    base = SYSTEM_PROMPTS.get(topic, SYSTEM_PROMPTS["general"])
    if not rag_chunks:
        return base

    context_parts = []
    for chunk in rag_chunks:
        src = chunk["source"]
        context_parts.append(f"[From: {src}]\n{chunk['content']}")

    context_block = "\n\n---\n\n".join(context_parts)
    return (
        f"{base}\n\n"
        f"[RELEVANT KNOWLEDGE BASE CONTEXT]\n"
        f"Use the following official information to answer the student's question accurately. "
        f"Cite the source document name naturally if relevant. "
        f"Do not mention that you were given context.\n\n"
        f"{context_block}"
    )

# ── Ollama chat ───────────────────────────────────────────────────────────────
def ollama_chat(system_prompt, messages):
    ollama_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        ollama_messages.append({
            "role": msg.get("role", "user"),
            "content": msg.get("content", "")
        })

    payload = json.dumps({
        "model": OLLAMA_CHAT_MODEL,
        "messages": ollama_messages,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_predict": 1000
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["message"]["content"]

# ── HTTP Handler ──────────────────────────────────────────────────────────────
class AcademiqHandler(http.server.SimpleHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"  [{self.address_string()}] {format % args}")

    def send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/status":
            self.handle_status()
            return
        elif self.path == "/api/documents":
            self.handle_list_documents()
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/chat":
            self.handle_chat()
        elif self.path == "/api/upload":
            self.handle_upload()
        elif self.path == "/api/delete_document":
            self.handle_delete_document()
        else:
            self.send_response(404)
            self.end_headers()

    def handle_status(self):
        ollama_ok = check_ollama()
        db_ok     = check_db()
        docs      = list_documents()
        self.send_json(200, {
            "ollama": ollama_ok,
            "db": db_ok,
            "doc_count": len(docs),
            "chat_model": OLLAMA_CHAT_MODEL,
            "embed_model": OLLAMA_EMBED_MODEL,
            "ready": ollama_ok and db_ok
        })

    def handle_list_documents(self):
        docs = list_documents()
        self.send_json(200, {"documents": docs})

    def handle_delete_document(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
            filename = payload.get("filename", "")
            if not filename:
                self.send_json(400, {"error": {"message": "Filename required."}})
                return
            success = delete_document(filename)
            self.send_json(200, {"success": success, "filename": filename})
        except Exception as e:
            self.send_json(500, {"error": {"message": str(e)}})

    def handle_upload(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
            filename   = payload.get("filename", "")
            base64_data = payload.get("data", "")

            if not filename or not base64_data:
                self.send_json(400, {"error": {"message": "Filename and file data are required."}})
                return

            # Strip base64 prefix if present (e.g. data:application/pdf;base64,...)
            if "," in base64_data:
                base64_data = base64_data.split(",", 1)[1]

            file_bytes = base64.b64decode(base64_data)
            print(f"\n  UPLOAD: Processing '{filename}' ({len(file_bytes)} bytes)...")

            chunks_stored = process_uploaded_file(filename, file_bytes)
            print(f"  UPLOAD: Successfully stored {chunks_stored} chunk(s) for '{filename}'.")

            self.send_json(200, {
                "success": True,
                "filename": filename,
                "chunks": chunks_stored,
                "message": f"Successfully indexed {chunks_stored} chunks into database."
            })
        except Exception as e:
            print(f"  UPLOAD ERROR: {e}")
            self.send_json(500, {"error": {"message": f"Upload failed: {str(e)}"}})

    def handle_chat(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
        except Exception as e:
            self.send_json(400, {"error": {"message": f"Invalid JSON: {e}"}})
            return

        messages  = payload.get("messages", [])
        topic     = payload.get("topic", "general")
        user_text = messages[-1].get("content", "") if messages else ""

        if not user_text:
            self.send_json(400, {"error": {"message": "No message content."}})
            return

        print(f"\n  USER [{topic}]: {user_text[:80]}...")

        # ── Semantic RAG retrieval ──
        rag_chunks = retrieve_context(user_text)
        sources    = list({c["source"] for c in rag_chunks})

        if rag_chunks:
            print(f"  RAG: {len(rag_chunks)} chunk(s) matched -> {sources}")
        else:
            print("  RAG: No relevant chunks found.")

        # ── Build system prompt ──
        system = build_augmented_system(topic, rag_chunks)

        # ── Call Ollama ──
        try:
            reply = ollama_chat(system, messages)
            print(f"  REPLY: {reply[:80]}...")
            
            # Format chunk details for context inspection
            rag_details = [
                {
                    "source": c["source"],
                    "file_type": c["file_type"],
                    "content": c["content"],
                    "score": round(float(c["score"]), 3)
                } for c in rag_chunks
            ]

            self.send_json(200, {
                "content": [{"type": "text", "text": reply}],
                "sources": sources,
                "rag_details": rag_details,
                "model": OLLAMA_CHAT_MODEL
            })
        except urllib.error.URLError:
            self.send_json(503, {
                "error": {
                    "message": (
                        "Ollama is not running. Please start Ollama and ensure "
                        f"'{OLLAMA_CHAT_MODEL}' is pulled."
                    )
                }
            })
        except Exception as e:
            self.send_json(500, {"error": {"message": f"Ollama error: {str(e)}"}})

# ── MIME types fix for Windows ────────────────────────────────────────────────
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

# ── Start server ──────────────────────────────────────────────────────────────
socketserver.TCPServer.allow_reuse_address = True

if __name__ == "__main__":
    ollama_ok = check_ollama()
    db_ok     = check_db()

    handler = AcademiqHandler
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print("\n" + "="*50)
        print("  AcademiQ — Local AI Server")
        print(f"  Open: http://localhost:{PORT}")
        print("="*50)
        print(f"  Ollama ({OLLAMA_CHAT_MODEL}): {'[OK] Ready' if ollama_ok else '[FAIL] Not found — start Ollama & pull model'}")
        print(f"  pgvector DB:                 {'[OK] Ready' if db_ok else '[FAIL] Not found — run setup_db.py first'}")
        print("="*50 + "\n")

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Shutting down AcademiQ server...")
