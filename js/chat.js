// ── AcademiQ Chat Logic ──

const API_URL = "https://api.anthropic.com/v1/messages";
const MODEL   = "claude-sonnet-4-6";

// ── System prompts per topic ──
const SYSTEM_PROMPTS = {
  general: `You are AcademiQ, a friendly and knowledgeable academic advisor. You help students with study strategies, exams, majors, careers, writing, and wellbeing. Keep responses helpful, encouraging, and concise (2–4 short paragraphs). Use plain language. Be warm and supportive.`,

  study: `You are AcademiQ, specializing in study strategies and time management for students. You help with study schedules, focus techniques, memory methods (spaced repetition, active recall, Pomodoro), and productivity habits. Give practical, actionable advice. Keep responses concise and encouraging.`,

  exams: `You are AcademiQ, an expert in exam preparation and test-taking strategies. You help students with revision planning, managing exam anxiety, understanding question types, time management during tests, and post-exam reflection. Be specific and practical. Keep responses concise.`,

  career: `You are AcademiQ, a career and major selection advisor for students. You help students explore majors, understand career pathways, evaluate job markets, prepare for internships, and think through graduate school. Ask clarifying questions when needed. Be balanced and encouraging.`,

  writing: `You are AcademiQ, specializing in academic writing and research. You help with essay structure, thesis statements, research methods, citations (APA, MLA, Chicago), editing techniques, and overcoming writer's block. Give concrete examples when helpful. Keep responses practical and clear.`,

  stress: `You are AcademiQ, focused on student wellbeing and managing academic stress. You help with burnout recovery, work-life balance, motivation, imposter syndrome, and building healthy habits. Be empathetic and supportive. Remind students that their wellbeing matters more than grades when appropriate.`,
};

const TOPIC_LABELS = {
  general: "General Academic Advisor",
  study:   "Study Strategies Specialist",
  exams:   "Exam Prep Coach",
  career:  "Career & Major Advisor",
  writing: "Writing & Research Guide",
  stress:  "Wellbeing & Stress Support",
};

// ── State ──
let currentTopic   = "general";
let conversationHistory = [];
let isLoading      = false;

// ── DOM refs ──
const messagesEl   = document.getElementById("messages");
const inputEl      = document.getElementById("user-input");
const sendBtnEl    = document.getElementById("send-btn");
const topicLabelEl = document.getElementById("topic-label");
const chipsBars    = document.getElementById("chips-bar");

// ── Topic switching ──
function setTopic(topic) {
  currentTopic = topic;
  topicLabelEl.textContent = TOPIC_LABELS[topic];

  document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
  const btn = document.querySelector(`.nav-item[onclick="setTopic('${topic}')"]`);
  if (btn) btn.classList.add("active");

  newChat();
}

// ── New chat ──
function newChat() {
  conversationHistory = [];
  messagesEl.innerHTML = "";

  const welcome = document.createElement("div");
  welcome.className = "welcome-block";
  welcome.innerHTML = `
    <div class="welcome-icon"><i class="ti ti-school"></i></div>
    <h1 class="welcome-title">Hello, I'm AcademiQ</h1>
    <p class="welcome-sub">Your personal academic advisor. Ask me anything about studying, exams, choosing a major, writing papers, or managing academic stress.</p>
    <div class="suggestion-grid">
      <button class="suggestion-card" onclick="sendSuggestion('How do I build an effective study schedule?')">
        <i class="ti ti-calendar"></i><span>Build a study schedule</span>
      </button>
      <button class="suggestion-card" onclick="sendSuggestion('What are the best techniques to prepare for exams?')">
        <i class="ti ti-notes"></i><span>Exam preparation tips</span>
      </button>
      <button class="suggestion-card" onclick="sendSuggestion('How do I choose the right college major?')">
        <i class="ti ti-compass"></i><span>Choosing a major</span>
      </button>
      <button class="suggestion-card" onclick="sendSuggestion('How do I write a strong research paper?')">
        <i class="ti ti-file-text"></i><span>Research paper guide</span>
      </button>
      <button class="suggestion-card" onclick="sendSuggestion('What are the best note-taking methods for college?')">
        <i class="ti ti-pencil"></i><span>Note-taking methods</span>
      </button>
      <button class="suggestion-card" onclick="sendSuggestion('How do I manage academic stress and burnout?')">
        <i class="ti ti-heart"></i><span>Manage academic stress</span>
      </button>
    </div>
  `;
  messagesEl.appendChild(welcome);
  chipsBars.style.display = "flex";
}

// ── Add message bubble ──
function addMessage(role, text) {
  // Hide welcome block on first real message
  const welcome = messagesEl.querySelector(".welcome-block");
  if (welcome) welcome.remove();
  chipsBars.style.display = "none";

  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;

  if (role === "bot") {
    const avatar = document.createElement("div");
    avatar.className = "msg-avatar";
    avatar.innerHTML = `<i class="ti ti-school"></i>`;
    wrap.appendChild(avatar);
  }

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrap.appendChild(bubble);

  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

// ── Typing indicator ──
function showTyping() {
  const wrap = document.createElement("div");
  wrap.className = "msg bot";
  wrap.id = "typing-wrap";

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.innerHTML = `<i class="ti ti-school"></i>`;

  const bubble = document.createElement("div");
  bubble.className = "bubble typing-indicator";
  bubble.innerHTML = `<span></span><span></span><span></span>`;

  wrap.appendChild(avatar);
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function removeTyping() {
  const t = document.getElementById("typing-wrap");
  if (t) t.remove();
}

// ── Send message ──
async function handleSend() {
  const text = inputEl.value.trim();
  if (!text || isLoading) return;

  inputEl.value = "";
  inputEl.style.height = "auto";
  isLoading = true;
  sendBtnEl.disabled = true;

  addMessage("user", text);
  conversationHistory.push({ role: "user", content: text });
  showTyping();

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 1000,
        system: SYSTEM_PROMPTS[currentTopic],
        messages: conversationHistory,
      }),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data?.error?.message || "API error");
    }

    const reply = data.content?.find(b => b.type === "text")?.text
      || "I'm sorry, I couldn't generate a response. Please try again.";

    removeTyping();
    addMessage("bot", reply);
    conversationHistory.push({ role: "assistant", content: reply });

  } catch (err) {
    removeTyping();
    addMessage("bot", `Something went wrong: ${err.message}. Please check your API key in js/config.js and try again.`);
    console.error("AcademiQ error:", err);
  }

  isLoading = false;
  sendBtnEl.disabled = false;
  inputEl.focus();
}

// ── Suggestion / chip helpers ──
function sendSuggestion(text) {
  inputEl.value = text;
  handleSend();
}

// ── Keyboard ──
function handleKey(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
}

// ── Auto-resize textarea ──
function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 140) + "px";
}

// ── Init ──
inputEl.focus();
