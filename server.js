// ── AcademiQ Backend Server ──
// Run this with: node server.js
// Then open: http://localhost:3000

const http = require("http");
const fs   = require("fs");
const path = require("path");

// ✅ PASTE YOUR ANTHROPIC API KEY HERE
const ANTHROPIC_API_KEY = "YOUR_API_KEY_HERE";

const MIME = {
  ".html": "text/html",
  ".css":  "text/css",
  ".js":   "application/javascript",
  ".png":  "image/png",
  ".ico":  "image/x-icon",
};

const server = http.createServer((req, res) => {

  // ── Proxy: POST /api/chat → Anthropic ──
  if (req.method === "POST" && req.url === "/api/chat") {
    let body = "";
    req.on("data", chunk => (body += chunk));
    req.on("end", async () => {
      try {
        const apiRes = await fetch("https://api.anthropic.com/v1/messages", {
          method: "POST",
          headers: {
            "Content-Type":      "application/json",
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
          },
          body,
        });
        const data = await apiRes.json();
        res.writeHead(apiRes.status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
      } catch (err) {
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: { message: err.message } }));
      }
    });
    return;
  }

  // ── Serve static files ──
  let filePath = "." + (req.url === "/" ? "/index.html" : req.url);
  filePath = path.normalize(filePath);

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404);
      res.end("Not found");
      return;
    }
    const ext  = path.extname(filePath);
    const mime = MIME[ext] || "text/plain";
    res.writeHead(200, { "Content-Type": mime });
    res.end(data);
  });
});

const PORT = 3000;
server.listen(PORT, () => {
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("  AcademiQ is running!");
  console.log(`  Open: http://localhost:${PORT}`);
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
});
