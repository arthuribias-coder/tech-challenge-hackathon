/**
 * report-chat.js — Chat contextual sobre o relatório STRIDE
 *
 * Funcionalidades:
 *  - Drawer recolhível (direita) ativado pelo FAB
 *  - Streaming SSE com typewriter e indicador de ferramenta
 *  - Guardrail: mensagens bloqueadas exibem aviso visual
 *  - Contexto é o relatório da análise (upload_id passado via data-atribute)
 *  - Markdown via marked.js + highlight.js
 *  - Sessão por aba (sessionStorage), não persiste entre aberturas
 */

"use strict";

/**
 * Inicializa o chat drawer após o HTML do drawer ser injetado no DOM.
 * Chamado por analysis.js depois de renderReport().
 */
window.reportChatInit = function reportChatInit() {
  // -------------------------------------------------------------------------
  // Referências DOM
  // -------------------------------------------------------------------------
  const fab = document.getElementById("report-chat-fab");
  const drawer = document.getElementById("report-chat-drawer");
  const overlay = document.getElementById("report-chat-overlay");
  const closeBtn = document.getElementById("drawer-close-btn");
  const messagesEl = document.getElementById("drawer-messages");
  const inputEl = document.getElementById("drawer-input");
  const sendBtn = document.getElementById("drawer-send-btn");

  if (!fab || !drawer || !messagesEl) return;

  // uploadId é injetado pelo template via data-upload-id no drawer
  const uploadId = drawer.dataset.uploadId || "";
  if (!uploadId) return;

  // -------------------------------------------------------------------------
  // Estado
  // -------------------------------------------------------------------------
  let sessionId = sessionStorage.getItem("report_chat_session_" + uploadId);
  if (!sessionId) {
    sessionId = crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36);
    sessionStorage.setItem("report_chat_session_" + uploadId, sessionId);
  }

  let isStreaming = false;
  let drawerOpen = false;

  // -------------------------------------------------------------------------
  // Configuração do Markdown
  // -------------------------------------------------------------------------
  if (typeof marked !== "undefined") {
    marked.setOptions({
      breaks: true,
      gfm: true,
      highlight:
        typeof hljs !== "undefined"
          ? (code, lang) => {
              const language = hljs.getLanguage(lang) ? lang : "plaintext";
              return hljs.highlight(code, { language }).value;
            }
          : null,
    });
  }

  function renderMarkdown(text) {
    if (typeof marked !== "undefined") {
      try {
        return marked.parse(text);
      } catch (_) {
        /* fallback */
      }
    }
    return text.replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br>");
  }

  // -------------------------------------------------------------------------
  // Drawer: abrir / fechar
  // -------------------------------------------------------------------------
  function openDrawer() {
    drawerOpen = true;
    drawer.classList.add("report-chat-drawer--open");
    overlay.classList.add("report-chat-overlay--visible");
    fab.classList.add("report-chat-fab--open");
    fab.setAttribute("aria-expanded", "true");
    document.body.style.overflow = "hidden";
    inputEl.focus();
  }

  function closeDrawer() {
    drawerOpen = false;
    drawer.classList.remove("report-chat-drawer--open");
    overlay.classList.remove("report-chat-overlay--visible");
    fab.classList.remove("report-chat-fab--open");
    fab.setAttribute("aria-expanded", "false");
    document.body.style.overflow = "";
  }

  fab.addEventListener("click", () => (drawerOpen ? closeDrawer() : openDrawer()));
  closeBtn && closeBtn.addEventListener("click", closeDrawer);
  overlay.addEventListener("click", closeDrawer);

  // Keyboard: Esc fecha o drawer
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && drawerOpen) closeDrawer();
  });

  // -------------------------------------------------------------------------
  // Input: auto-resize + habilitar botão
  // -------------------------------------------------------------------------
  inputEl.addEventListener("input", function () {
    this.style.height = "auto";
    this.style.height = this.scrollHeight + "px";
    sendBtn.disabled = !this.value.trim() || isStreaming;
  });

  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey) {
      e.preventDefault();
      if (!sendBtn.disabled) sendMessage();
    }
    if (e.key === "Enter" && (e.ctrlKey || e.shiftKey)) {
      // permite nova linha via Ctrl+Enter ou Shift+Enter
    }
  });

  sendBtn.addEventListener("click", sendMessage);

  // Botões de sugestão
  messagesEl.addEventListener("click", function (e) {
    const btn = e.target.closest(".drawer-suggestion-btn");
    if (!btn) return;
    inputEl.value = btn.dataset.msg || btn.textContent.trim();
    inputEl.dispatchEvent(new Event("input"));
    sendMessage();
  });

  // -------------------------------------------------------------------------
  // Renderização de mensagens
  // -------------------------------------------------------------------------
  function appendUserMessage(text) {
    const div = document.createElement("div");
    div.className = "drawer-msg drawer-msg--user";
    div.innerHTML = `
      <div class="drawer-msg__avatar">EU</div>
      <div class="drawer-msg__bubble">${renderMarkdown(text)}</div>`;
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function createAssistantBubble() {
    const div = document.createElement("div");
    div.className = "drawer-msg drawer-msg--assistant";
    div.innerHTML = `
      <div class="drawer-msg__avatar">AI</div>
      <div class="drawer-msg__bubble">
        <div class="drawer-typing">
          <span class="drawer-typing__dot"></span>
          <span class="drawer-typing__dot"></span>
          <span class="drawer-typing__dot"></span>
        </div>
      </div>`;
    messagesEl.appendChild(div);
    scrollToBottom();
    return div;
  }

  function appendToolBadge(toolName) {
    const div = document.createElement("div");
    div.className = "drawer-msg drawer-msg--assistant";
    div.innerHTML = `
      <div class="drawer-msg__avatar">AI</div>
      <div class="drawer-msg__bubble">
        <span class="drawer-tool-badge">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               width="11" height="11" aria-hidden="true">
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77
                     a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3
                     l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
          </svg>
          ${toolName}
        </span>
      </div>`;
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function appendBlockedMessage(reason) {
    const div = document.createElement("div");
    div.className = "drawer-msg drawer-msg--assistant drawer-msg--blocked";
    div.innerHTML = `
      <div class="drawer-msg__avatar">AI</div>
      <div class="drawer-msg__bubble">${renderMarkdown(reason)}</div>`;
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function hideWelcome() {
    const welcome = messagesEl.querySelector(".drawer-welcome");
    if (welcome) welcome.style.display = "none";
  }

  // -------------------------------------------------------------------------
  // Envio de mensagem
  // -------------------------------------------------------------------------
  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || isStreaming) return;

    hideWelcome();
    inputEl.value = "";
    inputEl.style.height = "auto";
    sendBtn.disabled = true;
    isStreaming = true;

    appendUserMessage(text);

    const assistantDiv = createAssistantBubble();
    const bubble = assistantDiv.querySelector(".drawer-msg__bubble");
    let accumulated = "";
    let firstToken = true;

    try {
      const response = await fetch(`/analysis/${uploadId}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: "Erro desconhecido" }));
        bubble.textContent = "Erro: " + (err.detail || response.statusText);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop(); // última linha pode estar incompleta

        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (raw === "[DONE]") break;
          if (!raw) continue;

          let event;
          try {
            event = JSON.parse(raw);
          } catch (_) {
            continue;
          }

          if (event.type === "debug") {
            // eventos de debug agora visíveis em /status
          } else if (event.type === "token") {
            if (firstToken) {
              bubble.innerHTML = "";
              firstToken = false;
            }
            accumulated += event.content;
            bubble.innerHTML = renderMarkdown(accumulated);
            scrollToBottom();
          } else if (event.type === "tool_use") {
            appendToolBadge(event.name);
          } else if (event.type === "blocked") {
            bubble.remove();
            assistantDiv.remove();
            appendBlockedMessage(event.reason || "Pergunta fora do escopo desta análise.");
            break;
          } else if (event.type === "error") {
            bubble.textContent = "Erro: " + event.message;
            break;
          }
        }
      }

      // Se não recebemos nenhum token: mostra mensagem
      if (firstToken) {
        bubble.textContent = "(Sem resposta — verifique os logs em /status)";
      }
    } catch (err) {
      bubble.textContent = "Erro de conexão: " + err.message;
    } finally {
      isStreaming = false;
      sendBtn.disabled = !inputEl.value.trim();
    }
  }
}; // fim window.reportChatInit
