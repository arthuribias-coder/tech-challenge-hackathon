/**
 * analysis.js — Pipeline de análise com SSE streaming
 *
 * Fluxo:
 *  1. Drag & drop / input → pré-visualização da imagem
 *  2. POST /analysis/upload → recebe upload_id
 *  3. EventSource /analysis/stream/{upload_id} → progresso em tempo real
 *  4. Evento "complete" → renderiza relatório inline (sem reload)
 *  5. Exportação para PDF via window.print()
 */

"use strict";

(function () {
  // -----------------------------------------------------------------------
  // Referências DOM
  // -----------------------------------------------------------------------
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("diagram");
  const placeholder = document.getElementById("dropzone-placeholder");
  const previewEl = document.getElementById("dropzone-preview");
  const previewImg = document.getElementById("preview-img");
  const previewName = document.getElementById("preview-name");
  const notesInput = document.getElementById("notes");
  const submitBtn = document.getElementById("submit-btn");
  const btnText = document.getElementById("btn-text");
  const btnLoading = document.getElementById("btn-loading");
  const stepperEl = document.getElementById("analysis-stepper");
  const reportSection = document.getElementById("report-section");

  if (!dropzone) return; // página não é a de análise

  // -----------------------------------------------------------------------
  // Passos do stepper (alinhado ao NODE_LABELS do backend)
  // -----------------------------------------------------------------------
  const STEPS = [
    { node: "validate_diagram", label: "Validação", icon: "🔎" },
    { node: "detect_shapes", label: "Detecção Visual", icon: "🔍" },
    { node: "map_components", label: "Mapeamento", icon: "🗺️" },
    { node: "vision_fallback", label: "IA Vision", icon: "👁️" },
    { node: "analyze_stride", label: "STRIDE", icon: "🛡️" },
    { node: "compile_report", label: "Relatório", icon: "📋" },
  ];

  // -----------------------------------------------------------------------
  // Drag & drop
  // -----------------------------------------------------------------------
  ["dragenter", "dragover"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.add("dropzone--active");
    }),
  );
  ["dragleave", "drop"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.remove("dropzone--active");
    }),
  );
  dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    if (file) applyFile(file);
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) applyFile(fileInput.files[0]);
  });

  dropzone.addEventListener("click", (e) => {
    if (e.target !== fileInput) fileInput.click();
  });

  function applyFile(file) {
    if (!file.type.startsWith("image/")) {
      showToast("Formato inválido. Use JPEG, PNG, GIF ou WebP.", "error");
      return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
      previewImg.src = e.target.result;
      previewName.textContent = file.name;
      placeholder.style.display = "none";
      previewEl.style.display = "flex";
    };
    reader.readAsDataURL(file);

    // Sincroniza com o input nativo (para o FormData)
    const dt = new DataTransfer();
    dt.items.add(file);
    fileInput.files = dt.files;

    submitBtn.disabled = false;
  }

  // -----------------------------------------------------------------------
  // Submit: upload → SSE streaming
  // -----------------------------------------------------------------------
  document.getElementById("upload-form").addEventListener("submit", async (e) => {
    e.preventDefault();

    if (!fileInput.files[0]) {
      showToast("Selecione uma imagem primeiro.", "error");
      return;
    }

    setLoading(true);
    clearStepper();
    reportSection.innerHTML = "";

    try {
      // Passo 1: upload do arquivo
      const formData = new FormData();
      formData.append("diagram", fileInput.files[0]);
      formData.append("notes", notesInput.value || "");

      const uploadRes = await fetch("/analysis/upload", {
        method: "POST",
        body: formData,
      });

      if (!uploadRes.ok) {
        const err = await uploadRes.json().catch(() => ({}));
        throw new Error(err.detail || `Erro no upload: ${uploadRes.status}`);
      }

      const { upload_id, image_filename, notes, mime_type } = await uploadRes.json();

      // Passo 2: SSE streaming do pipeline
      const params = new URLSearchParams({ notes: notes || "", mime_type });
      const evtSource = new EventSource(`/analysis/stream/${upload_id}?${params}`);

      evtSource.onmessage = (event) => {
        if (event.data === "[DONE]") {
          evtSource.close();
          setLoading(false);
          return;
        }

        try {
          const payload = JSON.parse(event.data);
          handleStreamEvent(payload, image_filename, upload_id);
        } catch (_) {
          /* ignora JSON inválido */
        }
      };

      evtSource.onerror = () => {
        evtSource.close();
        setLoading(false);
        showToast("Conexão SSE perdida. Tente novamente.", "error");
      };
    } catch (err) {
      setLoading(false);
      showToast(err.message, "error");
    }
  });

  // -----------------------------------------------------------------------
  // Eventos SSE
  // -----------------------------------------------------------------------
  function handleStreamEvent(payload, imageName, uploadId) {
    if (payload.type === "progress") {
      activateStep(payload.node);
    } else if (payload.type === "invalid_diagram") {
      setLoading(false);
      renderInvalidDiagram(payload.detected_type, payload.message);
    } else if (payload.type === "complete") {
      completeAllSteps();
      renderReport(payload.report, imageName || payload.image_filename, uploadId);
    } else if (payload.type === "error") {
      showToast(`Erro na análise: ${payload.message}`, "error");
      setLoading(false);
    }
  }

  function renderInvalidDiagram(detectedType, message) {
    reportSection.innerHTML = `
      <div class="invalid-diagram-card">
        <div class="invalid-diagram-icon">⚠️</div>
        <h2 class="invalid-diagram-title">Imagem não reconhecida</h2>
        <p class="invalid-diagram-detected">
          Tipo detectado: <strong>${escHtml(detectedType || "Desconhecido")}</strong>
        </p>
        <p class="invalid-diagram-message">${escHtml(message || "A imagem enviada não parece ser um diagrama de arquitetura.")}</p>
        <p class="invalid-diagram-hint">
          Por favor, envie um diagrama de arquitetura válido (ex.: diagramas C4, AWS, Azure, UML de componentes ou sequência).
        </p>
      </div>
    `;
    reportSection.style.display = "block";
  }

  // -----------------------------------------------------------------------
  // Stepper
  // -----------------------------------------------------------------------
  function clearStepper() {
    if (!stepperEl) return;

    // Barra de progresso + contador (inserida antes do stepper)
    const container = document.getElementById("stepper-container");
    const existingTop = container?.querySelector(".stepper-top");
    if (existingTop) existingTop.remove();

    if (container) {
      const top = document.createElement("div");
      top.className = "stepper-top";
      top.innerHTML = `
        <div class="stepper-progress-bar">
          <div class="stepper-progress-fill" id="stepper-fill" style="width:0%"></div>
        </div>
        <p class="stepper-counter" id="stepper-counter">Iniciando an\u00e1lise\u2026</p>
      `;
      container.insertBefore(top, stepperEl);
    }

    // Gera etapas horizontais com connectors entre elas
    const parts = [];
    STEPS.forEach((s, i) => {
      parts.push(
        `<div class="step" id="step-${s.node}" data-idx="${i}">
          <div class="step__icon"><span class="step__emoji">${s.icon}</span></div>
          <div class="step__label">${s.label}</div>
        </div>`,
      );
      if (i < STEPS.length - 1) {
        parts.push(`<div class="step__track" id="track-${i}"></div>`);
      }
    });

    stepperEl.innerHTML = parts.join("");
    stepperEl.style.display = "flex";
  }

  function activateStep(nodeName) {
    const activeIdx = STEPS.findIndex((s) => s.node === nodeName);
    if (activeIdx === -1) return;

    // Marca etapas anteriores como conclu\u00eddas
    stepperEl?.querySelectorAll(".step").forEach((el) => {
      const idx = parseInt(el.dataset.idx);
      if (idx < activeIdx) {
        el.classList.remove("step--active");
        el.classList.add("step--done");
        const emoji = el.querySelector(".step__emoji");
        if (emoji) emoji.textContent = "\u2713";
        const track = document.getElementById(`track-${idx}`);
        if (track) {
          track.classList.remove("step__track--active");
          track.classList.add("step__track--done");
        }
      }
    });

    // Marca conector anterior como ativo (preenchimento parcial)
    if (activeIdx > 0) {
      const prevTrack = document.getElementById(`track-${activeIdx - 1}`);
      if (prevTrack) {
        prevTrack.classList.remove("step__track--active");
        prevTrack.classList.add("step__track--done");
      }
    }
    const currTrack = document.getElementById(`track-${activeIdx}`);
    if (currTrack) currTrack.classList.add("step__track--active");

    // Ativa etapa atual
    const step = stepperEl?.querySelector(`#step-${nodeName}`);
    if (step) step.classList.add("step--active");

    // Atualiza barra de progresso
    const pct = Math.round((activeIdx / STEPS.length) * 100);
    const fill = document.getElementById("stepper-fill");
    if (fill) fill.style.width = `${pct}%`;

    // Atualiza contador
    const counter = document.getElementById("stepper-counter");
    const stepObj = STEPS[activeIdx];
    if (counter && stepObj) {
      counter.textContent = `Etapa ${activeIdx + 1} de ${STEPS.length}\u00a0\u00b7\u00a0${stepObj.label}\u2026`;
    }
  }

  function completeAllSteps() {
    stepperEl?.querySelectorAll(".step").forEach((el) => {
      el.classList.remove("step--active");
      el.classList.add("step--done");
      const emoji = el.querySelector(".step__emoji");
      if (emoji) emoji.textContent = "\u2713";
    });
    stepperEl?.querySelectorAll(".step__track").forEach((t) => {
      t.classList.remove("step__track--active");
      t.classList.add("step__track--done");
    });

    const fill = document.getElementById("stepper-fill");
    if (fill) fill.style.width = "100%";

    const counter = document.getElementById("stepper-counter");
    if (counter) counter.textContent = `An\u00e1lise conclu\u00edda \u2014 ${STEPS.length} etapas processadas \u2713`;
  }

  // -----------------------------------------------------------------------
  // Renderização inline do relatório
  // -----------------------------------------------------------------------
  function renderReport(report, imageName, uploadId) {
    const threats = report.threats || [];
    const components = report.components || [];

    // Distribuição STRIDE para o gráfico
    const strideCounts = {};
    threats.forEach((t) => {
      strideCounts[t.stride_category] = (strideCounts[t.stride_category] || 0) + 1;
    });

    const highCount = threats.filter((t) => t.severity === "Alta").length;
    const mediumCount = threats.filter((t) => t.severity === "Média").length;
    const lowCount = threats.filter((t) => t.severity === "Baixa").length;

    const CAT_MAP = { S: "Spoofing", T: "Tampering", R: "Repudiation", I: "Information Disclosure", D: "Denial of Service", E: "Elevation of Privilege" };
    const KEY_MAP = Object.fromEntries(Object.entries(CAT_MAP).map(([k, v]) => [v, k]));

    reportSection.innerHTML = `
      <div class="report-header" id="report-anchor">
        <h2 class="report-header__title">Relatório de Modelagem de Ameaças</h2>
        <p class="report-header__meta">
          <strong>${threats.length}</strong> ameaça(s) em
          <strong>${components.length}</strong> componente(s)
        </p>
        <button class="btn btn--secondary btn--sm" onclick="window.print()">Exportar PDF</button>
      </div>

      <div class="card">
        <h3 class="section-title">Diagrama Analisado</h3>
        <div class="diagram-preview">
          <img src="/uploads/${imageName}" alt="Diagrama analisado" />
        </div>
      </div>

      ${
        report.summary
          ? `
      <div class="card">
        <h3 class="section-title">Resumo Executivo</h3>
        <div class="summary-text">${report.summary}</div>
      </div>`
          : ""
      }

      <div class="stats-row">
        <div class="stat-card stat-card--high">
          <span class="stat-card__number">${highCount}</span>
          <span class="stat-card__label">Alta</span>
        </div>
        <div class="stat-card stat-card--medium">
          <span class="stat-card__number">${mediumCount}</span>
          <span class="stat-card__label">Média</span>
        </div>
        <div class="stat-card stat-card--low">
          <span class="stat-card__number">${lowCount}</span>
          <span class="stat-card__label">Baixa</span>
        </div>
        <div class="stat-card stat-card--total">
          <span class="stat-card__number">${components.length}</span>
          <span class="stat-card__label">Componentes</span>
        </div>
      </div>

      <div class="report-charts-row">
        <div class="card chart-card">
          <h3 class="section-title">Distribuição STRIDE</h3>
          <canvas id="stride-chart" width="260" height="260"></canvas>
        </div>
        <div class="card chart-card">
          <h3 class="section-title">Componentes Identificados</h3>
          <div class="components-grid">
            ${
              components
                .map(
                  (c) => `
              <div class="component-card">
                <div class="component-card__type">${escHtml(c.component_type)}</div>
                <div class="component-card__name">${escHtml(c.name)}</div>
                <div class="component-card__desc">${escHtml(c.description)}</div>
              </div>`,
                )
                .join("") || '<p class="empty-state">Nenhum componente.</p>'
            }
          </div>
        </div>
      </div>

      <div class="card">
        <h3 class="section-title">Ameaças Identificadas</h3>
        <div class="filter-bar">
          <button class="filter-btn filter-btn--active" data-filter="all">Todas</button>
          ${Object.entries(CAT_MAP)
            .map(([k, v]) => `<button class="filter-btn stride-btn--${k}" data-filter="${v}">${k} — ${v.split(" ")[0]}</button>`)
            .join("")}
        </div>
        <div class="threats-list" id="threats-list">
          ${
            threats
              .map((t) => {
                const catKey = KEY_MAP[t.stride_category] || "S";
                const sevClass = t.severity?.toLowerCase().replace("é", "e") || "baixa";
                return `
              <div class="threat-card threat-card--${sevClass}" data-category="${escHtml(t.stride_category)}">
                <div class="threat-card__header">
                  <span class="stride-badge stride-badge--${catKey}">${catKey} — ${escHtml(t.stride_category)}</span>
                  <span class="severity-badge severity-badge--${sevClass}">${escHtml(t.severity)}</span>
                </div>
                <h4 class="threat-card__title">${escHtml(t.title)}</h4>
                <p class="threat-card__component">Componente: <strong>${escHtml(t.affected_component)}</strong></p>
                <p class="threat-card__desc">${escHtml(t.description)}</p>
                <div class="threat-card__countermeasures">
                  <strong>Contramedidas:</strong>
                  <ul>${(t.countermeasures || []).map((cm) => `<li>${escHtml(cm)}</li>`).join("")}</ul>
                </div>
              </div>`;
              })
              .join("") || '<p class="empty-state">Nenhuma ameaça identificada.</p>'
          }
        </div>
      </div>`;

    // Filtros dinâmicos
    document.querySelectorAll(".filter-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("filter-btn--active"));
        btn.classList.add("filter-btn--active");
        const filter = btn.dataset.filter;
        document.querySelectorAll(".threat-card").forEach((card) => {
          card.style.display = filter === "all" || card.dataset.category === filter ? "" : "none";
        });
      });
    });

    // Gráfico de rosca STRIDE (Chart.js)
    renderStrideChart(strideCounts);

    // Scroll suave para o relatório
    document.getElementById("report-anchor")?.scrollIntoView({ behavior: "smooth" });

    // -----------------------------------------------------------------------
    // Injeta drawer de chat contextual (remove versão anterior se existir)
    // -----------------------------------------------------------------------
    document.getElementById("report-chat-fab")?.remove();
    document.getElementById("report-chat-overlay")?.remove();
    document.getElementById("report-chat-drawer")?.remove();

    const drawerFrag = document.createElement("template");
    drawerFrag.innerHTML = `
      <button class="report-chat-fab" id="report-chat-fab" aria-expanded="false" aria-label="Consultar IA sobre este relatório">
        <svg class="fab-icon-chat" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
        <svg class="fab-icon-close" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
        <span>Consultar IA</span>
      </button>
      <div class="report-chat-overlay" id="report-chat-overlay"></div>
      <aside class="report-chat-drawer" id="report-chat-drawer" data-upload-id="${uploadId || ""}">
        <div class="drawer-header">
          <div class="drawer-header__info">
            <span class="drawer-header__icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
              </svg>
            </span>
            <div>
              <strong class="drawer-header__title">Analista STRIDE</strong>
              <p class="drawer-header__subtitle">Especialista em segurança &bull; contexto deste relatório</p>
            </div>
          </div>
          <button class="drawer-debug-btn" id="drawer-debug-btn" aria-label="Painel de debug" title="Debug">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline>
            </svg>
          </button>
          <button class="drawer-close-btn" id="drawer-close-btn" aria-label="Fechar chat">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
        <!-- Painel de debug: oculto por padrão -->
        <div class="drawer-debug-panel" id="drawer-debug-panel" style="display:none">
          <div class="drawer-debug-toolbar">
            <span class="drawer-debug-title">LangGraph Events</span>
            <button class="drawer-debug-copy-btn" id="drawer-debug-copy-btn" title="Copiar todos os eventos">Copiar</button>
            <button class="drawer-debug-clear-btn" id="drawer-debug-clear-btn" title="Limpar">Limpar</button>
          </div>
          <pre class="drawer-debug-log" id="drawer-debug-log"></pre>
        </div>
        <div class="drawer-messages" id="drawer-messages">
          <div class="drawer-welcome">
            <p>Olá! Sou seu analista de segurança focado neste relatório. Posso ajudá-lo a:</p>
            <div class="drawer-suggestions">
              <button class="drawer-suggestion-btn" data-msg="Quais são as ameaças mais críticas deste relatório?">Ameaças críticas</button>
              <button class="drawer-suggestion-btn" data-msg="Explique as contramedidas recomendadas">Contramedidas</button>
              <button class="drawer-suggestion-btn" data-msg="Como priorizar a correção das vulnerabilidades?">Priorizar correções</button>
              <button class="drawer-suggestion-btn" data-msg="Mapear as ameaças para o MITRE ATT&amp;CK">MITRE ATT&amp;CK</button>
            </div>
          </div>
        </div>
        <div class="drawer-input-area">
          <div class="drawer-input-wrapper">
            <textarea class="drawer-input" id="drawer-input" rows="1" placeholder="Pergunte sobre este relatório..."></textarea>
            <button class="drawer-send-btn" id="drawer-send-btn" aria-label="Enviar" disabled>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
              </svg>
            </button>
          </div>
          <p class="drawer-input-hint">Enter para enviar &nbsp;·&nbsp; Shift+Enter para nova linha</p>
        </div>
      </aside>`;

    document.body.append(drawerFrag.content.cloneNode(true));

    // Inicializa o módulo de chat (report-chat.js deve estar carregado na página)
    window.reportChatInit && window.reportChatInit();
  }

  // -----------------------------------------------------------------------
  // Chart.js — rosca STRIDE
  // -----------------------------------------------------------------------
  function renderStrideChart(counts) {
    const ctx = document.getElementById("stride-chart");
    if (!ctx || typeof Chart === "undefined") return;

    const labels = Object.keys(counts);
    const data = Object.values(counts);
    const colors = ["#7c3aed", "#2563eb", "#d97706", "#dc2626", "#16a34a", "#0891b2"];

    new Chart(ctx, {
      type: "doughnut",
      data: {
        labels,
        datasets: [{ data, backgroundColor: colors.slice(0, labels.length), borderWidth: 0 }],
      },
      options: {
        responsive: false,
        plugins: {
          legend: { position: "right", labels: { color: "#e5e7eb", font: { size: 12 } } },
        },
      },
    });
  }

  // -----------------------------------------------------------------------
  // Utilitários
  // -----------------------------------------------------------------------
  function setLoading(loading) {
    submitBtn.disabled = loading;
    btnText.style.display = loading ? "none" : "inline";
    btnLoading.style.display = loading ? "inline" : "none";
  }

  function showToast(msg, type = "info") {
    const existing = document.querySelector(".toast");
    existing?.remove();

    const toast = document.createElement("div");
    toast.className = `toast toast--${type}`;
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
  }

  function escHtml(str) {
    if (!str) return "";
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
})();
