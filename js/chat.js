// ── AcademiQ Main JS Application ──

const API_CHAT = "/api/chat";
const API_STATUS = "/api/status";
const API_DOCS = "/api/documents";
const API_UPLOAD = "/api/upload";
const API_DELETE_DOC = "/api/delete_document";

let currentTopic = "general";
let conversationHistory = [];
let allDocuments = [];
let lastRagDetails = [];

// DOM References
const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");
const statusBadge = document.getElementById("ai-status-badge");
const topicLabel = document.getElementById("topic-label");
const sidebarDocBadge = document.getElementById("kb-doc-badge");

// ── Theme Management ──
function initTheme() {
  const savedTheme = localStorage.getItem("academiq_theme") || "dark";
  document.documentElement.setAttribute("data-theme", savedTheme);
  updateThemeIcon(savedTheme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme");
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("academiq_theme", next);
  updateThemeIcon(next);
}

function updateThemeIcon(theme) {
  const icon = document.getElementById("theme-icon");
  if (icon) {
    icon.className = theme === "dark" ? "ti ti-sun" : "ti ti-moon";
  }
}

// ── Mobile Sidebar Drawer ──
function toggleSidebar() {
  const sidebar = document.getElementById("sidebar");
  const overlay = document.getElementById("sidebar-overlay");
  if (sidebar && overlay) {
    sidebar.classList.toggle("open");
    overlay.classList.toggle("active");
  }
}

// ── Topic Switcher ──
function setTopic(topic) {
  currentTopic = topic;
  const topicNames = {
    general: "General Academic Advisor",
    study: "Study Strategies & Productivity",
    exams: "Exam Preparation & Revision",
    career: "Career & Major Guidance",
    writing: "Academic Writing & Research",
    stress: "Stress Management & Wellbeing"
  };

  if (topicLabel) {
    topicLabel.textContent = topicNames[topic] || "Academic Advisor";
  }

  // Update active sidebar item
  document.querySelectorAll(".sidebar-nav .nav-item").forEach(btn => {
    btn.classList.remove("active");
  });
  event?.currentTarget?.classList.add("active");

  // Close mobile sidebar if open
  document.getElementById("sidebar")?.classList.remove("open");
  document.getElementById("sidebar-overlay")?.classList.remove("active");
}

// ── New Session ──
function newChat() {
  conversationHistory = [];
  messagesEl.innerHTML = `
    <div class="welcome-hero">
      <div class="hero-icon-container">
        <i class="ti ti-school"></i>
        <div class="hero-glow"></div>
      </div>
      <h1 class="hero-title">How can I guide your studies today?</h1>
      <p class="hero-subtitle">AcademiQ is your local vector-search empowered academic advisor. Upload your notes, syllabi, or PDFs to receive precise, context-aware answers.</p>

      <div class="suggestion-grid" id="suggestions">
        <button class="suggestion-card" onclick="sendSuggestion('How do I build an effective study schedule for finals?')">
          <div class="card-icon"><i class="ti ti-calendar-event"></i></div>
          <div class="card-text">
            <span class="card-title">Study Schedule</span>
            <span class="card-desc">Build a 7-day revision plan</span>
          </div>
        </button>
        <button class="suggestion-card" onclick="sendSuggestion('What are the best active recall techniques for exams?')">
          <div class="card-icon"><i class="ti ti-notes"></i></div>
          <div class="card-text">
            <span class="card-title">Exam Strategies</span>
            <span class="card-desc">Active recall & spaced repetition</span>
          </div>
        </button>
        <button class="suggestion-card" onclick="sendSuggestion('How do I choose between different college majors?')">
          <div class="card-icon"><i class="ti ti-compass"></i></div>
          <div class="card-text">
            <span class="card-title">Career Pathway</span>
            <span class="card-desc">Evaluate majors & skills</span>
          </div>
        </button>
        <button class="suggestion-card" onclick="sendSuggestion('How do I structure a literature review paper?')">
          <div class="card-icon"><i class="ti ti-file-text"></i></div>
          <div class="card-text">
            <span class="card-title">Academic Writing</span>
            <span class="card-desc">Outline thesis & citations</span>
          </div>
        </button>
      </div>
    </div>
  `;
}

// ── Sending Messages ──
function sendSuggestion(text) {
  if (inputEl) {
    inputEl.value = text;
    handleSend();
  }
}

function handleKey(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
}

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 160) + "px";
}

async function handleSend() {
  const text = inputEl.value.trim();
  if (!text) return;

  // Clear welcome screen if present
  const welcomeHero = messagesEl.querySelector(".welcome-hero");
  if (welcomeHero) welcomeHero.remove();

  // Render User Message
  appendMessage("user", text);
  conversationHistory.push({ role: "user", content: text });

  // Reset Input
  inputEl.value = "";
  inputEl.style.height = "auto";
  sendBtn.disabled = true;

  // Show Typing Indicator
  const typingEl = showTypingIndicator();

  try {
    const res = await fetch(API_CHAT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic: currentTopic,
        messages: conversationHistory
      })
    });

    typingEl.remove();

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error?.message || `Server error (${res.status})`);
    }

    const data = await res.json();
    const replyText = data.content?.[0]?.text || "No response generated.";
    const sources = data.sources || [];
    lastRagDetails = data.rag_details || [];

    // Append Assistant Message
    appendMessage("assistant", replyText, sources, lastRagDetails);
    conversationHistory.push({ role: "assistant", content: replyText });

  } catch (err) {
    typingEl.remove();
    appendMessage("assistant", `⚠️ Error: ${err.message}`);
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

// ── Render Message Bubbles ──
function appendMessage(role, text, sources = [], ragDetails = []) {
  const wrapper = document.createElement("div");
  wrapper.className = `msg-wrapper ${role}-wrapper`;

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.innerHTML = role === "user" ? '<i class="ti ti-user"></i>' : '<i class="ti ti-school"></i>';

  const body = document.createElement("div");
  body.className = "msg-body";

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";

  if (role === "user") {
    bubble.textContent = text;
  } else {
    bubble.innerHTML = formatMarkdown(text);
  }

  body.appendChild(bubble);

  // Render Citations if available
  if (role === "assistant" && sources && sources.length > 0) {
    const sourcesDiv = document.createElement("div");
    sourcesDiv.className = "sources-container";
    sourcesDiv.innerHTML = `<span class="sources-label"><i class="ti ti-file-search"></i> Grounded in:</span>`;

    sources.forEach(src => {
      const pill = document.createElement("span");
      pill.className = "citation-pill";
      pill.innerHTML = `<i class="ti ti-file-text"></i> ${src}`;
      pill.title = "Click to inspect retrieved pgvector chunks";
      pill.onclick = () => openRagInspector(src, ragDetails);
      sourcesDiv.appendChild(pill);
    });

    body.appendChild(sourcesDiv);
  }

  wrapper.appendChild(avatar);
  wrapper.appendChild(body);
  messagesEl.appendChild(wrapper);

  // Scroll to bottom
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function showTypingIndicator() {
  const wrapper = document.createElement("div");
  wrapper.className = "msg-wrapper assistant-wrapper";
  wrapper.innerHTML = `
    <div class="msg-avatar"><i class="ti ti-school"></i></div>
    <div class="typing-indicator">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
    </div>
  `;
  messagesEl.appendChild(wrapper);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return wrapper;
}

// ── Markdown Formatter Helper ──
function formatMarkdown(text) {
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Bold
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Italic
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
  // Inline Code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Paragraphs
  html = html.split(/\n\n+/).map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');

  return html;
}

// ── RAG Context Inspector Modal ──
function openRagInspector(sourceName, ragDetails) {
  const modal = document.getElementById("rag-inspector-modal");
  const body = document.getElementById("inspector-body");
  const sub = document.getElementById("inspector-subtitle");

  if (!modal || !body) return;

  sub.textContent = `Showing vector search matches for '${sourceName}'`;
  body.innerHTML = "";

  const matches = ragDetails.filter(d => d.source === sourceName);
  if (matches.length === 0) {
    body.innerHTML = `<div class="doc-empty-state"><p>No detailed chunk matches recorded for this source.</p></div>`;
  } else {
    matches.forEach((chunk, i) => {
      const card = document.createElement("div");
      card.className = "inspector-chunk-card";
      const simPercent = (chunk.score * 100).toFixed(1);
      card.innerHTML = `
        <div class="chunk-header">
          <span class="chunk-source-name"><i class="ti ti-file-text"></i> ${chunk.source} (Chunk #${i+1})</span>
          <span class="chunk-score-pill">Cosine Similarity: ${simPercent}%</span>
        </div>
        <div class="chunk-content-box">${chunk.content}</div>
      `;
      body.appendChild(card);
    });
  }

  modal.style.display = "flex";
}

function closeRagInspector() {
  const modal = document.getElementById("rag-inspector-modal");
  if (modal) modal.style.display = "none";
}

function closeRagInspectorOnOverlay(e) {
  if (e.target.id === "rag-inspector-modal") {
    closeRagInspector();
  }
}

// ── Unified Knowledge Base Modal & File Upload ──
function openKbModal() {
  const modal = document.getElementById("kb-modal");
  if (modal) modal.style.display = "flex";
  fetchDocuments();
  setupDropzone();
}

function closeKbModal() {
  const modal = document.getElementById("kb-modal");
  if (modal) modal.style.display = "none";
}

function closeKbModalOnOverlay(e) {
  if (e.target.id === "kb-modal") {
    closeKbModal();
  }
}

async function fetchDocuments() {
  const grid = document.getElementById("doc-list");
  const docCountEl = document.getElementById("stat-doc-count");
  const chunkCountEl = document.getElementById("stat-chunk-count");

  try {
    const res = await fetch(API_DOCS);
    const data = await res.json();
    allDocuments = data.documents || [];

    let totalChunks = 0;
    allDocuments.forEach(d => totalChunks += (d.chunks || 0));

    if (docCountEl) docCountEl.textContent = allDocuments.length;
    if (chunkCountEl) chunkCountEl.textContent = totalChunks;
    if (sidebarDocBadge) sidebarDocBadge.textContent = allDocuments.length;

    renderDocList(allDocuments);
  } catch (err) {
    if (grid) grid.innerHTML = `<div class="doc-empty-state"><p>Error connecting to database to list documents.</p></div>`;
  }
}

function renderDocList(docs) {
  const grid = document.getElementById("doc-list");
  if (!grid) return;

  if (docs.length === 0) {
    grid.innerHTML = `
      <div class="doc-empty-state">
        <i class="ti ti-file-off"></i>
        <p>No matching documents found. Upload a file above!</p>
      </div>
    `;
    return;
  }

  grid.innerHTML = "";
  docs.forEach(doc => {
    const card = document.createElement("div");
    card.className = "doc-card";

    const iconClass = doc.file_type === "pdf" ? "ti-file-type-pdf" :
                      doc.file_type === "html" ? "ti-file-code" : "ti-file-text";

    card.innerHTML = `
      <div class="doc-card-left">
        <i class="ti ${iconClass} doc-type-icon"></i>
        <div>
          <div class="doc-card-title">${doc.source}</div>
          <div class="doc-card-sub">${doc.chunks} vector chunks • .${doc.file_type}</div>
        </div>
      </div>
      <button class="btn-delete-doc" onclick="deleteDoc('${doc.source}')" title="Delete document">
        <i class="ti ti-trash"></i>
      </button>
    `;
    grid.appendChild(card);
  });
}

function filterDocList() {
  const query = document.getElementById("doc-search-input")?.value?.toLowerCase() || "";
  const filtered = allDocuments.filter(d => d.source.toLowerCase().includes(query));
  renderDocList(filtered);
}

async function deleteDoc(filename) {
  if (!confirm(`Are you sure you want to remove '${filename}' from the database?`)) return;

  try {
    const res = await fetch(API_DELETE_DOC, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename })
    });
    const data = await res.json();
    if (data.success) {
      fetchDocuments();
      updateStatusBadge();
    } else {
      alert(`Could not delete document: ${data.error?.message || 'Unknown error'}`);
    }
  } catch (err) {
    alert(`Delete error: ${err.message}`);
  }
}

async function handleFileUpload(input) {
  const file = input.files[0];
  if (!file) return;

  const banner = document.getElementById("upload-status");
  if (banner) {
    banner.style.display = "flex";
    banner.className = "upload-status-banner banner-loading";
    banner.innerHTML = `<i class="ti ti-loader-2 spin"></i> Extracting text & embedding <b>${file.name}</b> into pgvector...`;
  }

  const reader = new FileReader();
  reader.onload = async function (e) {
    const base64Data = e.target.result;
    try {
      const res = await fetch(API_UPLOAD, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: file.name,
          data: base64Data
        })
      });

      const data = await res.json();
      if (res.ok && data.success) {
        if (banner) {
          banner.className = "upload-status-banner banner-success";
          banner.innerHTML = `<i class="ti ti-circle-check"></i> Successfully indexed <b>${file.name}</b> (${data.chunks} chunks)!`;
        }
        input.value = "";
        fetchDocuments();
        updateStatusBadge();
      } else {
        throw new Error(data.error?.message || "Upload failed");
      }
    } catch (err) {
      if (banner) {
        banner.className = "upload-status-banner banner-error";
        banner.innerHTML = `<i class="ti ti-alert-circle"></i> Indexing error: ${err.message}`;
      }
      input.value = "";
    }
  };

  reader.readAsDataURL(file);
}

function setupDropzone() {
  const dropzone = document.getElementById("dropzone");
  if (!dropzone) return;

  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropzone.addEventListener(eventName, e => {
      e.preventDefault();
      e.stopPropagation();
    }, false);
  });

  ['dragenter', 'dragover'].forEach(eventName => {
    dropzone.addEventListener(eventName, () => dropzone.classList.add('drag-over'), false);
  });

  ['dragleave', 'drop'].forEach(eventName => {
    dropzone.addEventListener(eventName, () => dropzone.classList.remove('drag-over'), false);
  });

  dropzone.addEventListener('drop', e => {
    const files = e.dataTransfer?.files;
    if (files && files.length > 0) {
      const input = document.getElementById("file-upload-input");
      if (input) {
        input.files = files;
        handleFileUpload(input);
      }
    }
  }, false);
}

// ── AI Status Poller ──
async function updateStatusBadge() {
  if (!statusBadge) return;
  try {
    const res = await fetch(API_STATUS);
    const data = await res.json();
    const docCount = data.doc_count || 0;

    if (sidebarDocBadge) sidebarDocBadge.textContent = docCount;

    if (data.ready) {
      statusBadge.className = "status-badge badge-ready";
      statusBadge.innerHTML = `<span class="pulse-dot"></span><span>Local AI Ready (${docCount} docs)</span>`;
    } else if (data.ollama && !data.db) {
      statusBadge.className = "status-badge badge-warn";
      statusBadge.innerHTML = `<span class="pulse-dot"></span><span>DB Empty</span>`;
    } else {
      statusBadge.className = "status-badge badge-error";
      statusBadge.innerHTML = `<span class="pulse-dot"></span><span>Ollama Offline</span>`;
    }
  } catch {
    statusBadge.className = "status-badge badge-error";
    statusBadge.innerHTML = `<span class="pulse-dot"></span><span>Server Offline</span>`;
  }
}

// ── Init ──
initTheme();
inputEl?.focus();
updateStatusBadge();
setInterval(updateStatusBadge, 20000);
