# AcademiQ — Institutional AI Knowledge Platform

AcademiQ is an institutional-grade Retrieval-Augmented Generation (RAG) platform powered by the **Open Knowledge Format (OKF)**, **Parallel Hybrid Search** (Vector Cosine Distance + Full-Text BM25/GIN), a **Deterministic Pure Math Reranker**, and **Three-Tier Access Scoping**.

Designed for universities, academic institutions, and enterprise knowledge bases, AcademiQ structures raw unstructured documents (PDFs, Markdown, TXT, HTML) into discrete Knowledge Units (KUs), policy rules, and tables to deliver verifiable, context-grounded AI responses with source citations.

---

## 🚀 Key Features

### 1. Open Knowledge Format (OKF) Engine
- **Parent-Child Chunking**: Splits documents into broad Parent Sections and granular Child Knowledge Units to balance context completeness and vector search precision.
- **Rule & Policy Clause Extraction**: Automatically extracts policy conditions, thresholds (e.g. GPA limits, course drop dates), actions, and exceptions.
- **Structured Table Extraction**: Parses markdown and tabular data into queryable JSON headers and rows.
- **Deterministic Contextual Prefixing**: Situates child chunks with document title, section heading, category, and authority for improved semantic embedding retrieval.

### 2. Parallel Hybrid Retrieval & Pure Math Reranker
- **Concurrent Dual Retrieval**: Executes dense vector search (
omic-embed-text via pgvector) and sparse full-text search (	svector with 	s_rank_cd and GIN index) in parallel threads via ThreadPoolExecutor.
- **Reciprocal Rank Fusion (RRF)**: Combines dense and sparse rank positions using constant \(k=60\):
  \text{RRF} = \left(\frac{1}{60 + r_{\text{dense}}} + \frac{1}{60 + r_{\text{sparse}}}\right) \times 30.0
- **Reinforcement Feedback Dampening**: Applies bounded hyperbolic tangent modulation based on user upvotes/downvotes:
  \text{Feedback Boost} = \tanh\left(\frac{\text{feedback\_score}}{3.0}\right)
- **Deterministic Composite Score**:
  \text{final\_score} = 1.0 \times \text{RRF} + 0.25 \times \text{Feedback Boost} + \text{Exact Match Boost}

### 3. Multi-Format Ingestion Pipeline
- Native extraction for **PDF** (PyPDF2), **Markdown** (.md), **Plain Text** (.txt), and **HTML** (BeautifulSoup4).
- Fault-tolerant ingestion: child chunks are preserved in full-text search indexes even if embedding models encounter timeouts.

### 4. Three-Tier Access Scoping & RBAC
- **Public / Institutional**: Documents accessible to all users across the institution.
- **Group-Scoped**: Knowledge units restricted to specific departments, cohorts, or project groups.
- **Personal / Private**: Private user documents with strict access isolation.
- **Role-Based Admin Dashboard**: Analytics, document oversight, user/group management, and query latency metrics.

### 5. Low-Latency Token Streaming & Multi-Model Dispatch
- Real-time Server-Sent Events (SSE) streaming with clean socket termination (Connection: close).
- Local offline inference via **Ollama** (llama3.2:3b, 
omic-embed-text).
- Cloud LLM fallback support for **Google Gemini** (gemini-2.0-flash, gemini-1.5-pro) and **Groq** (groq/compound-mini, openai/gpt-oss-20b).

---

## 🏗️ Architecture

`
                                  ┌─────────────────────────────┐
                                  │   Raw Documents (PDF/TXT)   │
                                  └──────────────┬──────────────┘
                                                 │
                                     [ OKF Extractor Engine ]
                                                 │
                       ┌─────────────────────────┴─────────────────────────┐
                       ▼                                                   ▼
            [ Parent Knowledge Units ]                          [ Child Knowledge Units ]
            (Broad Section Context)                             (Granular Chunks + Meta)
                       │                                                   │
                       └─────────────────────────┬─────────────────────────┘
                                                 │
                                   ┌─────────────┴─────────────┐
                                   ▼                           ▼
                        [ PostgreSQL pgvector ]     [ PostgreSQL TSVECTOR GIN ]
                        (Dense Cosine Vectors)      (Sparse English Lexemes)
                                   ▲                           ▲
═══════════════════════════════════╪═══════════════════════════╪═════════════════════════════
QUERY PIPELINE                     │                           │
                                   └─────────────┬─────────────┘
                                                 │
               User Query ──► [ Parallel ThreadPool Search (Dense + Sparse) ]
                                                 │
                                                 ▼
                                     [ Reciprocal Rank Fusion ]
                                                 │
                                                 ▼
                                  [ Deterministic Math Reranker ]
                                  (RRF + Feedback + Exact Match)
                                                 │
                                                 ▼
                                   [ Augmented Grounded Prompt ]
                                                 │
                                                 ▼
                                     [ LLM Token Streaming ] ──► UI Client
`

---

## 🛠️ Tech Stack

- **Backend**: Python 3.13 (http.server, socketserver, psycopg2, crypt)
- **Vector & Relational Database**: PostgreSQL 16+ with pgvector extension
- **Caching & Rate Limiting**: Redis (in-memory fallback included)
- **Local AI & Embeddings**: Ollama (
omic-embed-text, llama3.2:3b)
- **Cloud Providers (Optional)**: Google Gemini API, Groq API
- **Frontend**: Vanilla JavaScript (ES6+), HTML5, CSS3 Custom Properties (Dark/Light themes), Tabler Icons

---

## 📦 Installation & Setup

### 1. Prerequisites
- **Python 3.10+** installed
- **PostgreSQL** with pgvector extension (e.g. running via Docker):
  `ash
  docker run -d --name academiq-pgvector -p 5433:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=academiq pgvector/pgvector:pg16
  `
- **Ollama** running locally with required models:
  `ash
  ollama pull nomic-embed-text
  ollama pull llama3.2:3b
  `

### 2. Clone Repository & Install Dependencies
`ash
git clone https://github.com/mohitlalwani1409-cpu/academiq.git
cd academiq
pip install -r requirements.txt
`

### 3. Configure Environment Variables
Create a .env file in the root directory:
`ini
PG_HOST=127.0.0.1
PG_PORT=5433
PG_DB=academiq
PG_USER=postgres
PG_PASS=postgres

OLLAMA_BASE_URL=http://localhost:11434

# Optional Cloud API Keys
GEMINI_API_KEY=
GROQ_API_KEY=
`

### 4. Initialize Database & Seed Knowledge Base
Run the OKF database setup and knowledge ingestion script:
`ash
python setup_db.py
`

### 5. Create Admin Account (Optional)
`ash
python create_admin.py
`

### 6. Start the Server
`ash
python server.py
`
Open your browser at **http://localhost:3001**.

---

## 🧪 Testing & Verification

Run the comprehensive unit and integration test suite:
`ash
python tests/test_all_features.py
`
This tests:
- Bcrypt password hashing & authentication
- Pure math reranking formulas & feedback dampening
- Multi-user access scoping
- Server-Sent Events (SSE) chunk stream parsing

---

## 📡 API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| /api/chat | POST | Streams RAG-grounded token response via Server-Sent Events (SSE) |
| /api/upload | POST | Ingests and indexes PDF/TXT/MD files into OKF Knowledge Units |
| /api/documents | GET | Lists all accessible documents scoped to current user |
| /api/delete_document | POST | Deletes a document and its knowledge units |
| /api/feedback | POST | Logs user rating (+1 / -1) and updates KU reinforcement score |
| /api/auth/signup | POST | Registers a new user and auto-enrolls in Everyone group |
| /api/auth/login | POST | Authenticates user and creates session cookie |
| /api/auth/me | GET | Returns authenticated user profile |
| /api/groups | GET | Lists user's groups |
| /api/admin/stats | GET | Admin analytics on feedback, document counts, and system metrics |


