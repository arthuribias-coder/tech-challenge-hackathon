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
  const dropzone        = document.getElementById("dropzone");
  const fileInput       = document.getElementById("diagram");
  const placeholder     = document.getElementById("dropzone-placeholder");
  const previewEl       = document.getElementById("dropzone-preview");
  const previewImg      = document.getElementById("preview-img");
  const previewName     = document.getElementById("preview-name");
  const notesInput      = document.getElementById("notes");
  const submitBtn       = document.getElementById("submit-btn");
  const btnText         = document.getElementById("btn-text");
  const btnLoading      = document.getElementById("btn-loading");
  const stepperEl       = document.getElementById("analysis-stepper");
  const reportSection   = document.getElementById("report-section");

  if (!dropzone) return; // página não é a de análise

  // -----------------------------------------------------------------------
  // Passos do stepper (alinhado ao NODE_LABELS do backend)
  // -----------------------------------------------------------------------
  const STEPS = [
    { node: "detect_shapes",   label: "Detecção Visual",    icon: "🔍" },
    { node: "map_components",   label: "Mapeamento",         icon: "🗺️" },
    { node: "vision_fallback",  label: "IA Vision",          icon: "👁️" },
    { node: "analyze_stride",   label: "STRIDE",             icon: "🛡️" },
    { node: "compile_report",   label: "Relatório",          icon: "📋" },
  ];

  // -----------------------------------------------------------------------
  // Drag & drop
  // -----------------------------------------------------------------------
  ["dragenter", "dragover"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("dropzone--active"); })
  );
  ["dragleave", "drop"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("dropzone--active"); })
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
      previewEl.style.display   = "flex";
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
          handleStreamEvent(payload, image_filename);
        } catch (_) { /* ignora JSON inválido */ }
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
  function handleStreamEvent(payload, imageName) {
    if (payload.type === "progress") {
      activateStep(payload.node);
    } else if (payload.type === "complete") {
      completeAllSteps();
      renderReport(payload.report, imageName || payload.image_filename);
    } else if (payload.type === "error") {
      showToast(`Erro na análise: ${payload.message}`, "error");
      setLoading(false);
    }
  }

  // -----------------------------------------------------------------------
  // Stepper
  // -----------------------------------------------------------------------
  function clearStepper() {
    if (!stepperEl) return;
    stepperEl.innerHTML = STEPS.map((s) =>
      `<div class="step" id="step-${s.node}" data-node="${s.node}">
        <div class="step__icon">${s.icon}</div>
        <div class="step__label">${s.label}</div>
        <div class="step__status"></div>
       </div>`
    ).join('<div class="step__connector"></div>');
    stepperEl.style.display = "flex";
  }

  function activateStep(nodeName) {
    // Marca o passo anterior como concluído
    stepperEl?.querySelectorAll(".step--active").forEach((el) => {
      el.classList.remove("step--active");
      el.classList.add("step--done");
      el.querySelector(".step__status").textContent = "✓";
    });

    const step = stepperEl?.querySelector(`#step-${nodeName}`);
    if (step) {
      step.classList.add("step--active");
      step.querySelector(".step__status").textContent = "...";
    }
  }

  function completeAllSteps() {
    stepperEl?.querySelectorAll(".step").forEach((el) => {
      el.classList.remove("step--active");
      el.classList.add("step--done");
      el.querySelector(".step__status").textContent = "✓";
    });
  }

  // -----------------------------------------------------------------------
  // Renderização inline do relatório
  // -----------------------------------------------------------------------
  function renderReport(report, imageName) {
    const threats = report.threats || [];
    const components = report.components || [];

    // Distribuição STRIDE para o gráfico
    const strideCounts = {};
    threats.forEach((t) => {
      strideCounts[t.stride_category] = (strideCounts[t.stride_category] || 0) + 1;
    });

    const highCount   = threats.filter((t) => t.severity === "Alta").length;
    const mediumCount = threats.filter((t) => t.severity === "Média").length;
    const lowCount    = threats.filter((t) => t.severity === "Baixa").length;

    const CAT_MAP = { S: "Spoofing", T: "Tampering", R: "Repudiation",
                      I: "Information Disclosure", D: "Denial of Service", E: "Elevation of Privilege" };
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

      ${report.summary ? `
      <div class="card">
        <h3 class="section-title">Resumo Executivo</h3>
        <div class="summary-text">${report.summary}</div>
      </div>` : ""}

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
            ${components.map((c) => `
              <div class="component-card">
                <div class="component-card__type">${escHtml(c.component_type)}</div>
                <div class="component-card__name">${escHtml(c.name)}</div>
                <div class="component-card__desc">${escHtml(c.description)}</div>
              </div>`).join("") || '<p class="empty-state">Nenhum componente.</p>'}
          </div>
        </div>
      </div>

      <div class="card">
        <h3 class="section-title">Ameaças Identificadas</h3>
        <div class="filter-bar">
          <button class="filter-btn filter-btn--active" data-filter="all">Todas</button>
          ${Object.entries(CAT_MAP).map(([k, v]) =>
            `<button class="filter-btn stride-btn--${k}" data-filter="${v}">${k} — ${v.split(" ")[0]}</button>`
          ).join("")}
        </div>
        <div class="threats-list" id="threats-list">
          ${threats.map((t) => {
            const catKey = KEY_MAP[t.stride_category] || "S";
            const sevClass = t.severity?.toLowerCase().replace("é","e") || "baixa";
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
          }).join("") || '<p class="empty-state">Nenhuma ameaça identificada.</p>'}
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
  }

  // -----------------------------------------------------------------------
  // Chart.js — rosca STRIDE
  // -----------------------------------------------------------------------
  function renderStrideChart(counts) {
    const ctx = document.getElementById("stride-chart");
    if (!ctx || typeof Chart === "undefined") return;

    const labels = Object.keys(counts);
    const data   = Object.values(counts);
    const colors = ["#7c3aed","#2563eb","#d97706","#dc2626","#16a34a","#0891b2"];

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
    btnText.style.display    = loading ? "none" : "inline";
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
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
})();
