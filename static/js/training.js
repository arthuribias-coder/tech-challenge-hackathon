/**
 * Frontend para gerenciamento de fine-tuning YOLOv8.
 * SSE via EventSource (GET) conectado ao endpoint /training/start.
 */

const API = "/training";
let eventSource = null;

// ─── Alert ────────────────────────────────────────────────────────────────────

function showAlert(msg, type = "error") {
  const el = document.getElementById("training-alert");
  el.textContent = msg;
  el.className = `show ${type}`;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 6000);
}

// ─── Dataset ──────────────────────────────────────────────────────────────────

async function downloadDataset() {
  const btn = document.getElementById("btnDownload");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Aguarde...';
  setDatasetStatus("Verificando dataset local... (pode demorar vários minutos se for necessário baixar)");

  try {
    const res = await fetch(`${API}/download`, { method: "POST" });
    const data = await res.json();

    if (!res.ok) throw new Error(data.detail || "Erro ao preparar dataset");

    const sourceIcons = { local: "✅", merged: "🟣" };
    const icon = sourceIcons[data.source] || "📦";
    setDatasetStatus(`✓ ${data.message}`);
    showAlert(`${icon} ${data.message} — Pode iniciar o fine-tuning!`, "success");
  } catch (err) {
    setDatasetStatus("");
    showAlert(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = "⬇ Baixar e Mesclar Datasets";
  }
}

async function useDemoDataset() {
  const btn = document.getElementById("btnDemo");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner" style="border-top-color:#744210"></span> Configurando...';

  try {
    const res = await fetch(`${API}/use-demo`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Erro");

    setDatasetStatus("✓ Modo Demo ativo — COCO128 será usado no treinamento");
    showAlert("Modo Demo (COCO128) configurado. Pode iniciar o fine-tuning!", "info");
  } catch (err) {
    showAlert(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = "🧪 Usar Demo (COCO128)";
  }
}

function setDatasetStatus(msg) {
  const el = document.getElementById("datasetStatus");
  if (el) el.textContent = msg;
}

// ─── Fine-tuning ──────────────────────────────────────────────────────────────

function validateInputs() {
  const epochs = parseInt(document.getElementById("inputEpochs").value);
  const batch = parseInt(document.getElementById("inputBatch").value);
  const img = parseInt(document.getElementById("inputImgSize").value);
  const pat = parseInt(document.getElementById("inputPatience").value);

  if (isNaN(epochs) || epochs < 1 || epochs > 500) {
    showAlert("Épocas: 1 – 500", "error");
    return null;
  }
  if (isNaN(batch) || batch < 1 || batch > 128) {
    showAlert("Batch size: 1 – 128", "error");
    return null;
  }
  if (isNaN(img) || img < 192 || img > 1280) {
    showAlert("Tamanho de imagem: 192 – 1280", "error");
    return null;
  }
  if (isNaN(pat) || pat < 1 || pat > 200) {
    showAlert("Patience: 1 – 200", "error");
    return null;
  }

  return { epochs, batch, img, pat };
}

function startTraining(resume = false) {
  const params = resume ? { epochs: 0, batch: 0, img: 0, pat: 0 } : validateInputs();
  if (!resume && !params) return;

  // Fechar SSE anterior
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }

  // UI: mostrar botão cancelar + container progresso
  document.getElementById("btnStart").style.display = "none";
  document.getElementById("btnResume").style.display = "none";
  document.getElementById("btnCancel").style.display = "inline-flex";
  document.getElementById("progress-container").classList.add("active");
  if (!resume) document.getElementById("epochTotal").textContent = params.epochs;

  // Montar URL com query params (EventSource só suporta GET)
  const url = new URL(`${API}/start`, window.location.origin);
  if (resume) {
    url.searchParams.set("resume", "true");
  } else {
    url.searchParams.set("epochs", params.epochs);
    url.searchParams.set("batch_size", params.batch);
    url.searchParams.set("img_size", params.img);
    url.searchParams.set("patience", params.pat);
  }

  eventSource = new EventSource(url.toString());

  eventSource.onmessage = (evt) => {
    try {
      const state = JSON.parse(evt.data);
      renderProgress(state);
    } catch (e) {
      console.error("SSE parse error:", e);
    }
  };

  eventSource.onerror = () => {
    // Se null: estado terminal já tratado em renderProgress (error/completed/cancelled)
    if (!eventSource) return;
    // Fechar SEMPRE ao detectar erro/reconexão: o endpoint GET /training/start inicia
    // um novo treinamento a cada requisição. Permitir auto-reconexão do EventSource
    // causaria treinamento automático ao reiniciar o servidor sem ação do usuário.
    eventSource.close();
    eventSource = null;
    showAlert("Conexão com o servidor perdida. Verifique o status e clique em 'Iniciar' para continuar.", "warning");
    resetTrainingUI();
  };
}

function renderProgress(state) {
  const pct = state.progress_percent || 0;
  document.getElementById("progressFill").style.width = `${pct}%`;
  document.getElementById("epochCurrent").textContent = state.current_epoch;
  document.getElementById("epochTotal").textContent = state.total_epochs;
  document.getElementById("metricProgress").textContent = `${pct.toFixed(1)}%`;
  document.getElementById("metricLoss").textContent = state.loss ? state.loss.toFixed(4) : "—";
  document.getElementById("metricMap").textContent = state.val_map ? state.val_map.toFixed(4) : "—";
  document.getElementById("metricEta").textContent = formatEta(state.eta_seconds);

  // Badge de status
  const statusText = {
    idle: "Parado",
    download: "Baixando",
    preparing: "Preparando",
    training: "Treinando",
    completed: "Concluído",
    error: "Erro",
    cancelled: "Cancelado",
  };
  const badge = document.getElementById("statusBadge");
  badge.textContent = statusText[state.status] || state.status;
  badge.className = `status-badge s-${state.status || "idle"}`;

  // Label de progresso
  if (state.status === "training") {
    document.getElementById("progressLabel").textContent = `Época ${state.current_epoch}/${state.total_epochs} — ETA: ${formatEta(state.eta_seconds)}`;
  }

  // Fim do treinamento
  if (state.status === "completed") {
    const path = state.model_path ? ` — ${state.model_path}` : "";
    showAlert(`✓ Treinamento concluído${path}`, "success");
    document.getElementById("progressLabel").textContent = "Treinamento concluído!";
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    resetTrainingUI();
    refreshModels();
  } else if (state.status === "error") {
    showAlert(`Erro: ${state.error}`, "error");
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    resetTrainingUI();
  } else if (state.status === "cancelled") {
    showAlert("Treinamento cancelado.", "info");
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    resetTrainingUI();
  }
}

function formatEta(seconds) {
  if (!seconds || seconds <= 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function resetTrainingUI() {
  document.getElementById("btnStart").style.display = "inline-flex";
  document.getElementById("btnCancel").style.display = "none";
  // Re-verifica se o botão resume deve aparecer
  checkResumable();
}

async function cancelTraining() {
  if (!confirm("Cancelar o treinamento em andamento?")) return;

  try {
    await fetch(`${API}/cancel`, { method: "POST" });
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    showAlert("Treinamento cancelado.", "info");
    resetTrainingUI();
  } catch (err) {
    showAlert(`Erro ao cancelar: ${err.message}`, "error");
  }
}

// ─── Modelos ──────────────────────────────────────────────────────────────────

async function refreshModels() {
  try {
    const res = await fetch(`${API}/models`);
    const data = await res.json();
    renderModels(data.models || []);
  } catch (err) {
    console.error("Erro ao carregar modelos:", err);
  }
}

function renderModels(models) {
  const container = document.getElementById("modelsList");

  if (models.length === 0) {
    container.innerHTML = '<div class="models-empty">Nenhum modelo fine-tuned disponível ainda.</div>';
    return;
  }

  container.innerHTML = models
    .map(
      (m) => `
    <div class="model-card">
      <div>
        <div class="model-name">📦 ${m.filename}</div>
        <div class="model-meta">${m.size_mb} MB &mdash; ${new Date(m.created).toLocaleString("pt-BR")}</div>
      </div>
      <div class="model-actions">
        <button class="btn-t btn-secondary" onclick="copyPath('${m.path}')">Copiar Path</button>
        <button class="btn-t btn-danger"    onclick="deleteModel('${m.filename}')">Deletar</button>
      </div>
    </div>
  `,
    )
    .join("");
}

function copyPath(path) {
  navigator.clipboard
    .writeText(path)
    .then(() => showAlert("Path copiado!", "success"))
    .catch(() => showAlert("Não foi possível copiar", "warning"));
}

async function deleteModel(filename) {
  if (!confirm(`Deletar o modelo "${filename}"?`)) return;

  try {
    const res = await fetch(`${API}/delete/${encodeURIComponent(filename)}`, { method: "POST" });
    if (!res.ok) throw new Error((await res.json()).detail || "Erro ao deletar");
    showAlert("Modelo deletado.", "success");
    refreshModels();
  } catch (err) {
    showAlert(`Erro: ${err.message}`, "error");
  }
}

// ─── Init ─────────────────────────────────────────────────────────────────────
async function checkResumable() {
  const btn = document.getElementById("btnResume");
  if (!btn) return;
  try {
    const res = await fetch(`${API}/checkpoint`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.resumable) {
      btn.style.display = "inline-flex";
      btn.title = `Retomar de: ${data.run_name}`;
    } else {
      btn.style.display = "none";
    }
  } catch (_) {
    btn.style.display = "none";
  }
}
async function checkTrainingStatus() {
  try {
    const res = await fetch(`${API}/status`);
    if (!res.ok) return;
    const state = await res.json();
    if (state.is_training) {
      // Treinamento em andamento no servidor: restaurar UI sem iniciar novo treinamento
      document.getElementById("btnStart").style.display = "none";
      document.getElementById("btnCancel").style.display = "inline-flex";
      document.getElementById("progress-container").classList.add("active");
      document.getElementById("epochTotal").textContent = state.total_epochs;
      renderProgress(state);
      showAlert("Treinamento em andamento. Use 'Cancelar' ou aguarde a conclusão.", "info");
    }
  } catch (_) {
    // Ignora erros na verificação inicial de status
  }
}

document.addEventListener("DOMContentLoaded", () => {
  refreshModels();
  checkTrainingStatus();
  checkResumable();
});
