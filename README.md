# AcademiQ — Academic Advisor Chatbot

A clean, fully client-side academic advisor.

## Features

- Real-time chat
- 6 specialized topic modes (Study, Exams, Career, Writing, Stress, General)
- Quick suggestion cards and chips for common questions
- Responsive design (mobile-friendly)
- Clean purple-accented UI with sidebar navigation

## Project Structure


academiq/
├── index.html        ← Main app page
├── css/
│   └── style.css     ← All styles
├── js/
│   └── chat.js       ← Chat logic & API calls
└── README.md


## Setup

### 1. Get your Anthropic API key
- Go to https://console.anthropic.com
- Create an account and generate an API key

### 2. Add your API key

Open `js/chat.js` and find the top of the file. The app calls the Anthropic API directly from the browser.

>  **Important:** For production use, never expose your API key in client-side code. Instead, proxy requests through your own backend server. For local/demo use, you can set the key in a backend proxy.

### 3. Set up a simple backend proxy (recommended)

Create a small server (Node.js example):

```js
// server.js
const express = require('express');
const fetch = require('node-fetch');
const app = express();
app.use(express.json());
app.use(express.static('.'));

app.post('/api/chat', async (req, res) => {
  const response = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': process.env.ANTHROPIC_API_KEY,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify(req.body),
  });
  const data = await response.json();
  res.json(data);
});

app.listen(3000, () => console.log('Running on http://localhost:3000'));
```

Then update `API_URL` in `js/chat.js` to `/api/chat`.

### 4. Open in browser

For local testing, open `index.html` directly in your browser, or serve it:

```bash
# Python
python3 -m http.server 8080

# Node.js
npx serve .
```

Then visit `http://localhost:8080`

## Topic Modes

| Mode | Focus |
|------|-------|
| General | Broad academic advice |
| Study Strategies | Schedules, focus, memory techniques |
| Exam Prep | Revision planning, test anxiety, technique |
| Career & Major | Major selection, career paths, grad school |
| Writing & Research | Essays, citations, research methods |
| Stress & Wellbeing | Burnout, balance, motivation |

## Customization

- **Change bot name/persona**: Edit the system prompts in `js/chat.js` → `SYSTEM_PROMPTS`
- **Add more topics**: Add entries to `SYSTEM_PROMPTS` and `TOPIC_LABELS`, then add a `<button>` in the sidebar
- **Change colors**: Edit CSS variables in `css/style.css` under `:root`
- **Add more suggestions**: Edit the `.suggestion-card` buttons in `index.html`

## Tech Stack

- Plain HTML, CSS, JavaScript (no frameworks)
- Anthropic Claude API (`claude-sonnet-4-6`)
- Tabler Icons (CDN)

---
