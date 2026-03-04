/**
 * chat.js — Chat agêntico STRIDE com SSE streaming
 *
 * Funcionalidades:
 *  - Streaming typewriter via EventSource
 *  - Múltiplas sessões com persistência em localStorage
 *  - Indicador de ferramenta em uso (visibilidade do agente)
 *  - Markdown renderizado via marked.js + highlight.js
 *  - Botão de copiar por mensagem
 *  - Enter = enviar, Shift+Enter = nova linha
 */

"use strict";

(function () {
  // -----------------------------------------------------------------------
  // Referências DOM
  // -----------------------------------------------------------------------
  const sessionListEl   = document.getElementById("session-list");
  const newSessionBtn   = document.getElementById("new-session-btn");
  const messagesEl      = document.getElementById("chat-messages");
  const inputEl         = document.getElementById("chat-input");
  const sendBtn         = document.getElementById("chat-send-btn");
  const sessionTitleEl  = document.getElementById("session-title");

  if (!messagesEl) return;

  // -----------------------------------------------------------------------
  // Estado
  // -----------------------------------------------------------------------
  const STORAGE_KEY = "stride_chat_sessions";
  let currentSessionId  = null;
  let isStreaming       = false;

  // -----------------------------------------------------------------------
  // Configuração do Markdown
  // -----------------------------------------------------------------------
  if (typeof marked !== "undefined") {
    marked.setOptions({
      breaks: true,
      gfm: true,
      highlight: typeof hljs !== "undefined"
        ? (code, lang) => {
            const language = hljs.getLanguage(lang) ? lang : "plaintext";
            return hljs.highlight(code, { language }).value;
          }
        : null,
    });
  }

  // -----------------------------------------------------------------------
  // Sessões (localStorage)
  // -----------------------------------------------------------------------
  function loadSessions() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    } catch {
      return {};
    }
  }

  function saveSessions(sessions) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  }

  function createSession() {
    const id    = crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36);
    const title = "Nova conversa";
    const sessions = loadSessions();
    sessions[id] = { id, title, messages: [], createdAt: Date.now() };
    saveSessions(sessions);
    return id;
  }

  function getSessionMessages(id) {
    return loadSessions()[id]?.messages || [];
  }

  function appendToSession(id, role, content) {
    const sessions = loadSessions();
    if (!sessions[id]) return;
    sessions[id].messages.push({ role, content });
    // Atualiza o título com a primeira mensagem do usuário
    if (role === "user" && sessions[id].title === "Nova conversa") {
      sessions[id].title = content.slice(0, 40) + (content.length > 40 ? "…" : "");
    }
    saveSessions(sessions);
  }

  function deleteSession(id) {
    const sessions = loadSessions();
    delete sessions[id];
    saveSessions(sessions);
  }

  function renderSessionList() {
    if (!sessionListEl) return;
    const sessions = loadSessions();
    const sorted   = Object.values(sessions).sort((a, b) => b.createdAt - a.createdAt);

    sessionListEl.innerHTML = sorted.map((s) => `
      <div class="session-item ${s.id === currentSessionId ? "session-item--active" : ""}"
           data-id="${s.id}">
        <span class="session-item__title">${escHtml(s.title)}</span>
        <button class="session-item__del" data-del="${s.id}" title="Excluir">×</button>
      </div>`
    ).join("") || '<p class="session-empty">Nenhuma conversa</p>';

    // Eventos
    sessionListEl.querySelectorAll(".session-item").forEach((el) => {
      el.addEventListener("click", (e) => {
        if (e.target.dataset.del) return;
        switchSession(el.dataset.id);
      });
    });
    sessionListEl.querySelectorAll(".session-item__del").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const delId = btn.dataset.del;
        if (delId === currentSessionId) {
          const ids = Object.keys(loadSessions()).filter((k) => k !== delId);
          deleteSession(delId);
          switchSession(ids[0] || null);
        } else {
          deleteSession(delId);
          renderSessionList();
        }
      });
    });
  }

  function switchSession(id) {
    if (!id) {
      currentSessionId = createSession();
    } else {
      currentSessionId = id;
    }
    renderSessionList();
    renderMessages();
    if (sessionTitleEl) {
      sessionTitleEl.textContent = loadSessions()[currentSessionId]?.title || "Conversa";
    }
  }

  // -----------------------------------------------------------------------
  // Renderiza as mensagens da sessão ativa
  // -----------------------------------------------------------------------
  function renderMessages() {
    messagesEl.innerHTML = "";
    appendWelcomeMessage();

    getSessionMessages(currentSessionId).forEach(({ role, content }) => {
      appendMessageEl(role, content, false);
    });
    scrollToBottom();
  }

  function appendWelcomeMessage() {
    if (getSessionMessages(currentSessionId).length > 0) return;
    const div = document.createElement("div");
    div.className = "chat-msg chat-msg--assistant";
    div.innerHTML = `
      <div class="chat-msg__avatar chat-msg__avatar--assistant">G</div>
      <div class="chat-msg__bubble">
        <p>Olá! Sou seu assistente especialista em <strong>Modelagem de Ameaças STRIDE</strong>.</p>
        <p style="margin-top:0.5rem">Posso identificar vulnerabilidades, calcular riscos, mapear ameaças para MITRE ATT&CK e sugerir contramedidas. Como posso ajudar?</p>
      </div>`;
    messagesEl.appendChild(div);
  }

  // -----------------------------------------------------------------------
  // Input handlers
  // -----------------------------------------------------------------------
  inputEl.addEventListener("input", () => {
    autoResize(inputEl);
    sendBtn.disabled = inputEl.value.trim().length === 0 || isStreaming;
  });

  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!sendBtn.disabled) sendMessage();
    }
  });

  sendBtn.addEventListener("click", sendMessage);

  newSessionBtn?.addEventListener("click", () => switchSession(null));

  document.querySelectorAll(".suggestion-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      inputEl.value = btn.dataset.msg;
      inputEl.dispatchEvent(new Event("input"));
      inputEl.focus();
    });
  });

  // -----------------------------------------------------------------------
  // Envio e streaming
  // -----------------------------------------------------------------------
  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || isStreaming) return;

    isStreaming = true;
    sendBtn.disabled = true;

    // Persiste e renderiza mensagem do usuário
    appendToSession(currentSessionId, "user", text);
    appendMessageEl("user", text, false);

    inputEl.value = "";
    autoResize(inputEl);

    // Cria elemento de resposta com streaming
    const { msgEl, bubbleEl } = appendMessageEl("assistant", "", true);
    const toolBadgeEl = createToolBadge(msgEl);

    let fullReply = "";

    try {
      const body = JSON.stringify({
        message: text,
        session_id: currentSessionId,
      });

      const response = await fetch("/chat/message/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || `Erro ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop(); // guarda linha incompleta

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6).trim();
          if (data === "[DONE]") { isStreaming = false; break; }

          try {
            const payload = JSON.parse(data);
            handleChatEvent(payload, bubbleEl, toolBadgeEl, (t) => { fullReply += t; });
          } catch (_) { /* ignora JSON inválido */ }
        }
      }
    } catch (err) {
      bubbleEl.innerHTML = `<span class="error-text">Erro: ${escHtml(err.message)}</span>`;
    }

    // Finaliza
    toolBadgeEl.style.display = "none";
    isStreaming = false;
    sendBtn.disabled = inputEl.value.trim().length === 0;

    if (fullReply) {
      appendToSession(currentSessionId, "assistant", fullReply);
      renderSessionList(); // atualiza título se foi primeira mensagem
    }
  }

  function handleChatEvent(payload, bubbleEl, toolBadgeEl, onToken) {
    if (payload.type === "token") {
      onToken(payload.content);
      // Renderiza Markdown incremental
      const rawText = bubbleEl.dataset.raw || "";
      bubbleEl.dataset.raw = rawText + payload.content;
      if (typeof marked !== "undefined") {
        bubbleEl.innerHTML = marked.parse(bubbleEl.dataset.raw);
        // Re-aplica highlight.js em novos blocos
        if (typeof hljs !== "undefined") {
          bubbleEl.querySelectorAll("pre code:not(.hljs)").forEach((el) => hljs.highlightElement(el));
        }
        addCopyButtons(bubbleEl);
      } else {
        bubbleEl.textContent = bubbleEl.dataset.raw;
      }
      scrollToBottom();
    } else if (payload.type === "tool_use") {
      toolBadgeEl.textContent = `Usando: ${payload.name}...`;
      toolBadgeEl.style.display = "block";
    } else if (payload.type === "tool_result") {
      toolBadgeEl.style.display = "none";
    } else if (payload.type === "error") {
      bubbleEl.innerHTML = `<span class="error-text">Erro: ${escHtml(payload.message)}</span>`;
    }
  }

  // -----------------------------------------------------------------------
  // Elementos de UI
  // -----------------------------------------------------------------------
  function appendMessageEl(role, content, streaming) {
    const isUser = role === "user";
    const div    = document.createElement("div");
    div.className = `chat-msg chat-msg--${isUser ? "user" : "assistant"}`;

    const avatar = document.createElement("div");
    avatar.className = `chat-msg__avatar chat-msg__avatar--${isUser ? "user" : "assistant"}`;
    avatar.textContent = isUser ? "EU" : "G";

    const bubble = document.createElement("div");
    bubble.className = "chat-msg__bubble";
    bubble.dataset.raw = "";

    if (streaming) {
      bubble.innerHTML = `<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>`;
    } else if (isUser) {
      bubble.textContent = content;
    } else if (content) {
      bubble.dataset.raw = content;
      bubble.innerHTML   = typeof marked !== "undefined" ? marked.parse(content) : content;
      addCopyButtons(bubble);
    }

    const actions = document.createElement("div");
    actions.className = "chat-msg__actions";
    if (!isUser && !streaming) {
      actions.innerHTML = `<button class="copy-btn" title="Copiar resposta">📋</button>`;
      actions.querySelector(".copy-btn")?.addEventListener("click", () => {
        navigator.clipboard?.writeText(bubble.dataset.raw || bubble.textContent || "");
      });
    }

    if (isUser) {
      div.appendChild(bubble);
      div.appendChild(avatar);
    } else {
      div.appendChild(avatar);
      const inner = document.createElement("div");
      inner.className = "chat-msg__inner";
      inner.appendChild(bubble);
      if (!streaming) inner.appendChild(actions);
      div.appendChild(inner);
    }

    messagesEl.appendChild(div);
    scrollToBottom();
    return { msgEl: div, bubbleEl: bubble };
  }

  function createToolBadge(parentEl) {
    const badge = document.createElement("div");
    badge.className = "tool-badge";
    badge.style.display = "none";
    parentEl.appendChild(badge);
    return badge;
  }

  function addCopyButtons(bubbleEl) {
    bubbleEl.querySelectorAll("pre:not(.has-copy)").forEach((pre) => {
      pre.classList.add("has-copy");
      const btn = document.createElement("button");
      btn.className = "code-copy-btn";
      btn.textContent = "Copiar";
      btn.addEventListener("click", () => {
        navigator.clipboard?.writeText(pre.querySelector("code")?.textContent || "");
        btn.textContent = "Copiado!";
        setTimeout(() => { btn.textContent = "Copiar"; }, 2000);
      });
      pre.style.position = "relative";
      pre.appendChild(btn);
    });
  }

  // -----------------------------------------------------------------------
  // Utilitários
  // -----------------------------------------------------------------------
  function autoResize(el) {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function escHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // -----------------------------------------------------------------------
  // Inicialização
  // -----------------------------------------------------------------------
  function init() {
    const sessions = loadSessions();
    const ids = Object.keys(sessions);
    if (ids.length === 0) {
      currentSessionId = createSession();
    } else {
      // Última sessão criada
      currentSessionId = Object.values(sessions).sort((a, b) => b.createdAt - a.createdAt)[0].id;
    }
    renderSessionList();
    renderMessages();
  }

  init();
})();
