"use strict";

const messagesEl = document.getElementById("messages");
const inputEl    = document.getElementById("input");
const sendBtn    = document.getElementById("send");

let ws            = null;
let currentBubble = null;
let buffer        = "";
let sessionClosed = false;

const TYPING_HTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';

const BOT_AVATAR_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" width="18" height="18">
  <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h3a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3v-7a3 3 0 0 1 3-3h3V5.73A2 2 0 0 1 12 2zM9.5 11a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zm5 0a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zm-4.5 5h4v.5h-4V16z"/>
</svg>`;

// ---- Auto-grow textarea ----
inputEl.addEventListener("input", () => {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 130) + "px";
});

// ---- WebSocket ----
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);

  ws.onopen = () => {
    sendBtn.disabled = false;
    inputEl.disabled = false;
    inputEl.focus();
  };

  ws.onmessage = (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch { return; }

    if (m.type === "assistant_start") {
      currentBubble = appendBubble("assistant");
      currentBubble.innerHTML = TYPING_HTML;
      buffer = "";

    } else if (m.type === "assistant_token") {
      buffer += m.text;
      if (!currentBubble) currentBubble = appendBubble("assistant");
      currentBubble.innerHTML = renderMinimalMarkdown(buffer);
      scrollToBottom();

    } else if (m.type === "assistant_end") {
      if (currentBubble) {
        if (buffer === "") {
          currentBubble.closest(".bubble-wrap")?.remove();
        }
        currentBubble = null;
      }
      buffer = "";

    } else if (m.type === "session_closing") {
      sessionClosed = true;
      appendBubble("system").innerHTML =
        "Sesja została zakończona. Odśwież stronę, aby rozpocząć nową rozmowę.";
      sendBtn.disabled = true;
      inputEl.disabled = true;
      ws.close();
    }
  };

  ws.onclose = () => {
    if (!sessionClosed) {
      if (currentBubble && currentBubble.isConnected && buffer === "") {
        currentBubble.closest(".bubble-wrap")?.remove();
        currentBubble = null;
      }
      appendBubble("system").innerHTML =
        "Połączenie zamknięte — odśwież stronę, aby ponowić rozmowę.";
    }
    sendBtn.disabled = true;
    inputEl.disabled = true;
  };

  ws.onerror = () => {
    appendBubble("system").innerHTML = "Błąd połączenia z serwerem.";
  };
}

// ---- Sending ----
function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
  appendBubble("user").innerHTML = escapeHtml(text);
  ws.send(JSON.stringify({ type: "user_message", text }));
  inputEl.value = "";
  inputEl.style.height = "auto";
  scrollToBottom();
}

sendBtn.addEventListener("click", sendMessage);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

// ---- DOM helpers ----
function now() {
  return new Date().toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
}

function appendBubble(role) {
  const wrap = document.createElement("div");
  wrap.className = `bubble-wrap ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (role === "system") {
    wrap.appendChild(bubble);
  } else {
    if (role === "assistant") {
      const avatar = document.createElement("div");
      avatar.className = "avatar";
      avatar.innerHTML = BOT_AVATAR_SVG;
      wrap.appendChild(avatar);
    }
    const inner = document.createElement("div");
    inner.className = "bubble-inner";
    const time = document.createElement("div");
    time.className = "bubble-time";
    time.textContent = now();
    inner.appendChild(bubble);
    inner.appendChild(time);
    wrap.appendChild(inner);
  }

  messagesEl.appendChild(wrap);
  scrollToBottom();
  return bubble;
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ---- Minimal markdown renderer ----
// Supports: **bold**, - list items, blank-line paragraphs. HTML-escaped first.

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderMinimalMarkdown(raw) {
  const escaped = escapeHtml(raw);
  const blocks = escaped.split(/\n{2,}/);
  const parts = [];

  for (const block of blocks) {
    const lines = block.split("\n");
    const isListLine  = (l) => l.trimStart().startsWith("- ");
    const listLines   = lines.filter(isListLine);
    const nonList     = lines.filter((l) => !isListLine(l));

    if (listLines.length > 0 && nonList.every((l) => l.trim() === "")) {
      const items = listLines
        .map((l) => `<li>${applyInline(l.replace(/^[\s-]+/, ""))}</li>`)
        .join("");
      parts.push(`<ul>${items}</ul>`);
    } else {
      const html = lines.map((l) => {
        if (isListLine(l)) {
          return `<ul><li>${applyInline(l.replace(/^[\s-]+/, ""))}</li></ul>`;
        }
        return applyInline(l);
      }).join("<br>");
      parts.push(`<p>${html}</p>`);
    }
  }

  return parts.join("");
}

function applyInline(str) {
  return str.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

// ---- Init ----
connect();
