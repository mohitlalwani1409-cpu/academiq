// ── AcademiQ Main JS Application (With Auth, Groups, Streaming, & Admin Analytics) ──

const API_CHAT = "/api/chat";
const API_STATUS = "/api/status";
const API_DOCS = "/api/documents";
const API_UPLOAD = "/api/upload";
const API_DELETE_DOC = "/api/delete_document";
const API_MODELS = "/api/models";
const API_AUTH_ME = "/api/auth/me";
const API_AUTH_LOGIN = "/api/auth/login";
const API_AUTH_SIGNUP = "/api/auth/signup";
const API_AUTH_LOGOUT = "/api/auth/logout";
const API_GROUPS = "/api/groups";
const API_ADMIN_STATS = "/api/admin/stats";

let currentTopic = "general";
let conversationHistory = [];
let allDocuments = [];
let userGroups = [];
let lastRagDetails = [];
let currentModel = "ollama/llama3.2:3b";
let currentUser = null;
let currentAuthTab = "login";

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

// ── Authentication & User Session Flow ──
async function checkAuth() {
  try {
    const res = await fetch(API_AUTH_ME);
    if (res.ok) {
      const data = await res.json();
      if (data.authenticated && data.user) {
        currentUser = data.user;
        updateUserHeaderUI(currentUser);
        closeAuthModal();
        fetchDocuments();
        fetchGroups();
        return;
      }
    }
  } catch (err) {
    console.warn("Auth check error:", err);
  }
  openAuthModal();
}

function openAuthModal() {
  const modal = document.getElementById("auth-modal");
  if (modal) modal.style.display = "flex";
}

function closeAuthModal() {
  const modal = document.getElementById("auth-modal");
  if (modal) modal.style.display = "none";
}

function switchAuthTab(tab) {
  currentAuthTab = tab;
  const loginTab = document.getElementById("tab-btn-login");
  const signupTab = document.getElementById("tab-btn-signup");
  const submitBtn = document.getElementById("auth-submit-btn");
  const errBox = document.getElementById("auth-error");

  if (errBox) errBox.style.display = "none";

  if (tab === "login") {
    loginTab?.classList.add("active");
    signupTab?.classList.remove("active");
    if (submitBtn) submitBtn.textContent = "Log In";
  } else {
    signupTab?.classList.add("active");
    loginTab?.classList.remove("active");
    if (submitBtn) submitBtn.textContent = "Create Account";
  }
}

async function handleAuthSubmit(e) {
  e.preventDefault();
  const usernameInput = document.getElementById("auth-username");
  const passwordInput = document.getElementById("auth-password");
  const errBox = document.getElementById("auth-error");

  const username = usernameInput?.value.trim();
  const password = passwordInput?.value.trim();
  if (!username || !password) return;

  const endpoint = currentAuthTab === "login" ? API_AUTH_LOGIN : API_AUTH_SIGNUP;

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });

    const data = await res.json();
    if (res.ok && data.success) {
      currentUser = data.user;
      updateUserHeaderUI(currentUser);
      closeAuthModal();
      usernameInput.value = "";
      passwordInput.value = "";
      fetchDocuments();
      fetchGroups();
      updateStatusBadge();
    } else {
      if (errBox) {
        errBox.textContent = data.error?.message || "Authentication failed.";
        errBox.style.display = "block";
      }
    }
  } catch (err) {
    if (errBox) {
      errBox.textContent = `Error: ${err.message}`;
      errBox.style.display = "block";
    }
  }
}

async function handleLogout() {
  try {
    await fetch(API_AUTH_LOGOUT, { method: "POST" });
  } catch (err) {}
  currentUser = null;
  updateUserHeaderUI(null);
  openAuthModal();
}

function updateUserHeaderUI(user) {
  const profileWrap = document.getElementById("user-profile-wrapper");
  const usernameEl = document.getElementById("header-username");
  const roleTag = document.getElementById("header-role-tag");
  const adminBtn = document.getElementById("btn-admin-dash");

  if (user && profileWrap) {
    profileWrap.style.display = "flex";
    if (usernameEl) usernameEl.textContent = user.username;
    if (roleTag) {
      roleTag.textContent = user.role.toUpperCase();
      roleTag.className = user.role === "admin" ? "role-tag-admin" : "role-tag-user";
    }
    if (adminBtn) {
      adminBtn.style.display = user.role === "admin" ? "inline-flex" : "none";
    }
  } else if (profileWrap) {
    profileWrap.style.display = "none";
    if (adminBtn) adminBtn.style.display = "none";
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

  document.querySelectorAll(".sidebar-nav .nav-item").forEach(btn => {
    btn.classList.remove("active");
  });
  event?.currentTarget?.classList.add("active");

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

// ── Sending Messages with Real-Time Token Streaming (Fix 2) ──
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

function createAssistantStreamBubble() {
  const wrapper = document.createElement("div");
  wrapper.className = "msg-wrapper assistant-wrapper";

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.innerHTML = '<i class="ti ti-brain"></i>';

  const body = document.createElement("div");
  body.className = "msg-body";

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';

  body.appendChild(bubble);
  wrapper.appendChild(avatar);
  wrapper.appendChild(body);
  messagesEl.appendChild(wrapper);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  return { wrapperEl: wrapper, bodyEl: body, bubbleEl: bubble };
}

async function handleSend() {
  const text = inputEl.value.trim();
  if (!text) return;

  const welcomeHero = messagesEl.querySelector(".welcome-hero");
  if (welcomeHero) welcomeHero.remove();

  appendMessage("user", text);
  conversationHistory.push({ role: "user", content: text });

  inputEl.value = "";
  inputEl.style.height = "auto";
  sendBtn.disabled = true;

  const { wrapperEl, bodyEl, bubbleEl } = createAssistantStreamBubble();

  try {
    const res = await fetch(API_CHAT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic: currentTopic,
        model: currentModel,
        messages: conversationHistory
      })
    });

    if (res.status === 401) {
      openAuthModal();
      throw new Error("Please log in to continue chatting.");
    }

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error?.message || `Server error (${res.status})`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let assistantReply = "";
    let buffer = "";
    let ragSources = [];
    let ragUnits = [];

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      // Keep trailing incomplete line in buffer for the next read (Fix 2)
      buffer = lines.pop();

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith("data: ")) continue;

        const payload = trimmed.substring(6);
        if (payload === "[DONE]") continue;

        try {
          const data = jsonParseSafe(payload);
          if (data.token) {
            assistantReply += data.token;
            bubbleEl.innerHTML = formatMarkdown(assistantReply);
            messagesEl.scrollTop = messagesEl.scrollHeight;
          } else if (data.sources && data.rag_details) {
            ragSources = data.sources;
            ragUnits = data.rag_details;
            lastRagDetails = ragUnits;
          }
        } catch (e) {
          console.warn("Error parsing stream chunk:", e, line);
        }
      }
    }

    // Process any remaining complete line left in buffer (Fix 2)
    if (buffer.trim().startsWith("data: ")) {
      const payload = buffer.trim().substring(6);
      if (payload !== "[DONE]") {
        try {
          const data = jsonParseSafe(payload);
          if (data.token) {
            assistantReply += data.token;
            bubbleEl.innerHTML = formatMarkdown(assistantReply);
          }
        } catch (e) {}
      }
    }

    // Attach citations and feedback thumbs after response generation
    if (ragSources && ragSources.length > 0) {
      attachCitationsAndFeedback(bodyEl, ragSources, ragUnits, text, assistantReply);
    }

    conversationHistory.push({ role: "assistant", content: assistantReply });

  } catch (err) {
    bubbleEl.innerHTML = `<span style="color:var(--danger-text)">⚠️ ${err.message}</span>`;
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

function jsonParseSafe(str) {
  try {
    return JSON.parse(str);
  } catch (e) {
    return {};
  }
}

// ── Render Message Bubbles & Actions ──
function appendMessage(role, text) {
  const wrapper = document.createElement("div");
  wrapper.className = `msg-wrapper ${role}-wrapper`;

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.innerHTML = role === "user" ? '<i class="ti ti-user"></i>' : '<i class="ti ti-brain"></i>';

  const body = document.createElement("div");
  body.className = "msg-body";

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.textContent = text;

  body.appendChild(bubble);
  wrapper.appendChild(avatar);
  wrapper.appendChild(body);
  messagesEl.appendChild(wrapper);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function attachCitationsAndFeedback(bodyEl, sources, ragDetails, userPrompt, replyText) {
  const sourcesDiv = document.createElement("div");
  sourcesDiv.className = "sources-container";
  sourcesDiv.innerHTML = `<span class="sources-label"><i class="ti ti-certificate"></i> Grounded in (OKF):</span>`;

  sources.forEach(src => {
    const pill = document.createElement("span");
    pill.className = "citation-pill";
    pill.innerHTML = `<i class="ti ti-file-text"></i> ${src}`;
    pill.title = "Click to inspect structured OKF knowledge unit";
    pill.onclick = () => openRagInspector(src, ragDetails);
    sourcesDiv.appendChild(pill);
  });

  bodyEl.appendChild(sourcesDiv);

  const actionsDiv = document.createElement("div");
  actionsDiv.className = "msg-actions";
  const unitIds = (ragDetails || []).map(d => d.id).join(",");

  actionsDiv.innerHTML = `
    <button class="btn-feedback-thumb" onclick="sendFeedback(this, 1, '${encodeURIComponent(userPrompt)}', '${encodeURIComponent(replyText)}', '${unitIds}')" title="Helpful & Accurately Grounded">
      <i class="ti ti-thumb-up"></i> Helpful
    </button>
    <button class="btn-feedback-thumb" onclick="sendFeedback(this, -1, '${encodeURIComponent(userPrompt)}', '${encodeURIComponent(replyText)}', '${unitIds}')" title="Report Inaccuracy / Missing Detail">
      <i class="ti ti-thumb-down"></i>
    </button>
  `;
  bodyEl.appendChild(actionsDiv);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ── Send Feedback (Reinforcement Learning / Feedback Loop) ──
async function sendFeedback(btn, rating, encodedQuery, encodedResponse, unitIds) {
  const query = decodeURIComponent(encodedQuery);
  const response = decodeURIComponent(encodedResponse);
  const parent = btn.parentElement;

  parent.querySelectorAll(".btn-feedback-thumb").forEach(b => {
    b.classList.remove("active-up", "active-down");
  });

  if (rating === 1) {
    btn.classList.add("active-up");
  } else {
    btn.classList.add("active-down");
  }

  try {
    await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: query,
        response: response,
        rating: rating,
        unit_ids: unitIds,
        model: currentModel
      })
    });
  } catch (err) {
    console.error("Feedback error:", err);
  }
}

function formatMarkdown(text) {
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.split(/\n\n+/).map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');

  return html;
}

// ── OKF Knowledge Unit Inspector Modal ──
function openRagInspector(sourceName, ragDetails) {
  const modal = document.getElementById("rag-inspector-modal");
  const body = document.getElementById("inspector-body");
  const sub = document.getElementById("inspector-subtitle");

  if (!modal || !body) return;

  sub.textContent = `Showing verified Open Knowledge Format (OKF) units for '${sourceName}'`;
  body.innerHTML = "";

  const matches = (ragDetails || []).filter(d => (d.doc_title === sourceName || d.source === sourceName));
  const unitsToRender = matches.length > 0 ? matches : (ragDetails || []);

  if (unitsToRender.length === 0) {
    body.innerHTML = `<div class="doc-empty-state"><p>No detailed OKF knowledge units recorded for this query.</p></div>`;
  } else {
    unitsToRender.forEach((unit) => {
      const card = document.createElement("div");
      card.className = "inspector-chunk-card";
      
      const entityType = (unit.entity_type || "general").toUpperCase();
      const secTitle = unit.section_title || "Section Overview";
      const docTitle = unit.doc_title || unit.source || "Document";
      const auth = unit.authority || "Institutional Authority";
      const ver = unit.version ? `v${unit.version}` : "v1.0";
      const rrfScore = unit.rrf_score !== undefined ? unit.rrf_score : "N/A";
      const finalScore = unit.final_score !== undefined ? unit.final_score : (unit.score || "N/A");
      const fbScore = unit.feedback_score !== undefined ? unit.feedback_score : 0.0;

      let rulesHtml = "";
      if (unit.rules && unit.rules.length > 0) {
        rulesHtml = `
          <div class="okf-rules-box">
            <div class="okf-rules-title"><i class="ti ti-checkup-list"></i> Extracted Policy Rules & Conditions:</div>
            ${unit.rules.map(r => `
              <div class="okf-rule-item">
                • <strong>If/When:</strong> ${r.condition} ➔ <strong>Action:</strong> ${r.action}
                ${r.threshold ? `<span class="okf-rule-threshold">[Limit: ${r.threshold}]</span>` : ''}
              </div>
            `).join('')}
          </div>
        `;
      }

      let tableHtml = "";
      if (unit.table_data && unit.table_data.headers && unit.table_data.rows) {
        tableHtml = `
          <div class="okf-table-container">
            <table class="okf-table-render">
              <thead>
                <tr>${unit.table_data.headers.map(h => `<th>${h}</th>`).join('')}</tr>
              </thead>
              <tbody>
                ${unit.table_data.rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>`).join('')}
              </tbody>
            </table>
          </div>
        `;
      }

      card.innerHTML = `
        <div class="chunk-header">
          <div style="display:flex; align-items:center; gap:8px;">
            <span class="okf-entity-badge">${entityType}</span>
            <span class="chunk-source-name"><i class="ti ti-file-certificate"></i> ${docTitle} &gt; ${secTitle}</span>
          </div>
          <div class="okf-score-group">
            <span class="chunk-score-pill" title="Final Deterministic Composite Score">Final: ${finalScore}</span>
            <span class="okf-rrf-pill" title="Reciprocal Rank Fusion Score">RRF: ${rrfScore}</span>
            <span class="okf-entity-badge" title="Reinforcement Feedback Score">Score: ${fbScore > 0 ? '+' : ''}${fbScore}</span>
          </div>
        </div>
        ${rulesHtml}
        ${tableHtml}
        <div class="chunk-content-box">${unit.content}</div>
        <div class="okf-meta-bar">
          <span><i class="ti ti-shield-check"></i> Authority: <strong>${auth}</strong></span>
          <span><i class="ti ti-git-branch"></i> Version: <strong>${ver}</strong></span>
          <span><i class="ti ti-file-code"></i> Source: <strong>${unit.source}</strong></span>
        </div>
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
  fetchGroups();
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

async function fetchGroups() {
  const select = document.getElementById("upload-group-select");
  if (!select) return;

  try {
    const res = await fetch(API_GROUPS);
    if (res.ok) {
      const data = await res.json();
      userGroups = data.groups || [];

      select.innerHTML = `<option value="">Private (Visible only to me)</option>`;
      userGroups.forEach(g => {
        const opt = document.createElement("option");
        opt.value = g.id;
        opt.textContent = g.is_system ? `${g.name} (Global Institutional Group)` : `${g.name} (${g.member_count} members)`;
        select.appendChild(opt);
      });
    }
  } catch (err) {
    console.warn("Could not fetch user groups:", err);
  }
}

async function promptCreateGroup() {
  const name = prompt("Enter new Group Name (e.g. CS101-Study-Group):");
  if (!name || !name.trim()) return;

  try {
    const res = await fetch(API_GROUPS, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() })
    });

    const data = await res.json();
    if (res.ok && data.success) {
      alert(`Group '${name}' created!`);
      fetchGroups();
    } else {
      alert(`Could not create group: ${data.error?.message || "Unknown error"}`);
    }
  } catch (err) {
    alert(`Error creating group: ${err.message}`);
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
        <p>No matching documents found. Upload a file above to extract OKF knowledge units!</p>
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

    const title = doc.title || doc.source;
    const category = (doc.category || "General").replace(/_/g, ' ');
    const ver = doc.version ? `v${doc.version}` : "v1.0";
    const groupName = doc.group_name || "Private";
    const canDelete = doc.is_mine || (currentUser && currentUser.role === "admin");

    card.innerHTML = `
      <div class="doc-card-left">
        <i class="ti ${iconClass} doc-type-icon"></i>
        <div>
          <div class="doc-card-title">
            ${title} 
            <span class="okf-entity-badge" style="margin-left:6px;">${category}</span>
            <span class="role-tag-user" style="margin-left:4px;">${groupName}</span>
          </div>
          <div class="doc-card-sub">${doc.chunks} OKF units • ${ver} • ${doc.source}</div>
        </div>
      </div>
      ${canDelete ? `
        <button class="btn-delete-doc" onclick="deleteDoc('${doc.source}')" title="Delete document">
          <i class="ti ti-trash"></i>
        </button>
      ` : ''}
    `;
    grid.appendChild(card);
  });
}

function filterDocList() {
  const query = document.getElementById("doc-search-input")?.value?.toLowerCase() || "";
  const filtered = allDocuments.filter(d => d.source.toLowerCase().includes(query) || (d.title && d.title.toLowerCase().includes(query)));
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
    if (res.ok && data.success) {
      fetchDocuments();
      updateStatusBadge();
    } else {
      alert(`Could not delete document: ${data.error?.message || 'Permission denied'}`);
    }
  } catch (err) {
    alert(`Delete error: ${err.message}`);
  }
}

async function handleFileUpload(input) {
  const file = input.files[0];
  if (!file) return;

  const groupSelect = document.getElementById("upload-group-select");
  const selectedGroupId = groupSelect?.value || null;

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
          data: base64Data,
          group_id: selectedGroupId
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

// ── Admin Analytics Dashboard Modal ──
function openAdminModal() {
  const modal = document.getElementById("admin-stats-modal");
  if (modal) modal.style.display = "flex";
  fetchAdminStats();
}

function closeAdminModal() {
  const modal = document.getElementById("admin-stats-modal");
  if (modal) modal.style.display = "none";
}

function closeAdminModalOnOverlay(e) {
  if (e.target.id === "admin-stats-modal") {
    closeAdminModal();
  }
}

async function fetchAdminStats() {
  const body = document.getElementById("admin-stats-body");
  if (!body) return;

  body.innerHTML = `<div style="text-align:center; padding:40px;"><i class="ti ti-loader-2 spin" style="font-size:24px;"></i><p>Loading analytics...</p></div>`;

  try {
    const res = await fetch(API_ADMIN_STATS);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error?.message || "Failed to load admin stats");
    }

    const data = await res.json();
    const ov = data.overall || {};
    const docs = data.documents || [];
    const cats = data.categories || [];

    let docRowsHtml = "";
    if (docs.length === 0) {
      docRowsHtml = `<tr><td colspan="6" style="text-align:center; color:var(--text-muted);">No feedback recorded on indexed documents yet.</td></tr>`;
    } else {
      docs.forEach(d => {
        docRowsHtml += `
          <tr>
            <td><strong>${d.title}</strong><br><small style="color:var(--text-muted);">${d.filename}</small></td>
            <td><span class="okf-entity-badge">${d.category.replace(/_/g, ' ')}</span></td>
            <td>${d.total_events}</td>
            <td><span style="color:var(--success-text);">+${d.upvotes}</span> / <span style="color:var(--danger-text);">-${d.downvotes}</span></td>
            <td><strong>${d.satisfaction_rate}%</strong></td>
            <td>${d.avg_chunk_score > 0 ? '+' : ''}${d.avg_chunk_score}</td>
          </tr>
        `;
      });
    }

    let catPillsHtml = cats.map(c => `
      <div class="kpi-card" style="padding:12px;">
        <span class="kpi-label">${c.category.replace(/_/g, ' ')}</span>
        <span class="kpi-value" style="font-size:18px;">${c.satisfaction_rate}%</span>
        <span style="font-size:11px; color:var(--text-muted);">${c.total_events} rating(s)</span>
      </div>
    `).join('');

    body.innerHTML = `
      <div class="admin-stats-grid">
        <div class="kpi-card">
          <span class="kpi-label">Satisfaction Rate</span>
          <span class="kpi-value" style="color:var(--accent-secondary);">${ov.satisfaction_rate}%</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">Total Feedback</span>
          <span class="kpi-value">${ov.total}</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">Upvotes</span>
          <span class="kpi-value" style="color:var(--success-text);">${ov.upvotes}</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">Downvotes</span>
          <span class="kpi-value" style="color:var(--danger-text);">${ov.downvotes}</span>
        </div>
      </div>

      <div style="margin-bottom:20px;">
        <h3 class="section-heading" style="margin-bottom:12px;">Category Satisfaction</h3>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:12px;">
          ${catPillsHtml || '<span style="color:var(--text-muted); font-size:12px;">No category data yet.</span>'}
        </div>
      </div>

      <h3 class="section-heading" style="margin-bottom:12px;">Per-Document Feedback Breakdown</h3>
      <div class="admin-table-container">
        <table class="admin-stats-table">
          <thead>
            <tr>
              <th>Document</th>
              <th>Category</th>
              <th>Feedback Events</th>
              <th>Votes (+ / -)</th>
              <th>Satisfaction</th>
              <th>Avg Chunk Score</th>
            </tr>
          </thead>
          <tbody>
            ${docRowsHtml}
          </tbody>
        </table>
      </div>
    `;

  } catch (err) {
    body.innerHTML = `<div style="color:var(--danger-text); padding:20px;">⚠️ ${err.message}</div>`;
  }
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

// ── Model Selector ──
let lastModelsJson = "";

async function fetchModels() {
  const select = document.getElementById("model-select");
  if (!select) return;

  try {
    const res = await fetch(API_MODELS);
    const data = await res.json();
    const jsonStr = JSON.stringify(data);
    
    if (jsonStr === lastModelsJson) {
      return;
    }
    lastModelsJson = jsonStr;

    const providers = data.providers || {};
    const defaultModel = data.default || "ollama/llama3.2:3b";
    const activeModel = currentModel || localStorage.getItem("academiq_model") || defaultModel;

    select.innerHTML = "";

    const providerIcons = {
      ollama: "⚙️",
      gemini: "✨",
      groq: "⚡"
    };

    let modelFound = false;

    for (const [providerKey, providerData] of Object.entries(providers)) {
      const group = document.createElement("optgroup");
      const icon = providerIcons[providerKey] || "";
      group.label = `${icon} ${providerData.label || providerKey}`;

      for (const model of providerData.models) {
        const option = document.createElement("option");
        const val = `${providerKey}/${model}`;
        option.value = val;
        option.textContent = model;
        if (val === activeModel) {
          option.selected = true;
          modelFound = true;
        }
        group.appendChild(option);
      }

      select.appendChild(group);
    }

    if (modelFound) {
      select.value = activeModel;
      currentModel = activeModel;
    } else if (select.options.length > 0) {
      currentModel = select.options[0].value;
      select.value = currentModel;
    }

    localStorage.setItem("academiq_model", currentModel);
    updateModelIcon();
  } catch (err) {
    console.warn("Could not fetch models:", err);
  }
}

function onModelChange() {
  const select = document.getElementById("model-select");
  if (!select) return;
  currentModel = select.value;
  localStorage.setItem("academiq_model", currentModel);
  updateModelIcon();
  console.log(`[AcademiQ] Switched model to: ${currentModel}`);
}

function updateModelIcon() {
  const icon = document.querySelector(".model-selector-icon");
  if (!icon) return;

  const provider = (currentModel || "").split("/")[0];
  const iconMap = {
    ollama: "ti-cpu",
    gemini: "ti-sparkles",
    groq: "ti-bolt"
  };
  icon.className = `ti ${iconMap[provider] || "ti-cpu"} model-selector-icon`;
}

// ── Init ──
initTheme();
inputEl?.focus();
checkAuth();
updateStatusBadge();
fetchModels();
setInterval(updateStatusBadge, 20000);
setInterval(fetchModels, 30000);
