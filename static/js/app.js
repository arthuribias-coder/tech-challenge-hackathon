/* STRIDE Threat Modeler — Frontend JS */

(function () {
    "use strict";

    /* ---- Dropzone com preview de imagem ---- */
    const input = document.getElementById("diagram");
    const dropzone = document.getElementById("dropzone");
    const placeholder = document.getElementById("dropzone-placeholder");
    const preview = document.getElementById("dropzone-preview");
    const previewImg = document.getElementById("preview-img");
    const previewName = document.getElementById("preview-name");

    if (input) {
        input.addEventListener("change", () => {
            const file = input.files[0];
            if (!file) return;
            showPreview(file);
        });

        dropzone.addEventListener("dragover", (e) => {
            e.preventDefault();
            dropzone.classList.add("dropzone--active");
        });

        dropzone.addEventListener("dragleave", () => {
            dropzone.classList.remove("dropzone--active");
        });

        dropzone.addEventListener("drop", (e) => {
            e.preventDefault();
            dropzone.classList.remove("dropzone--active");
            const file = e.dataTransfer.files[0];
            if (!file) return;
            const dt = new DataTransfer();
            dt.items.add(file);
            input.files = dt.files;
            showPreview(file);
        });
    }

    function showPreview(file) {
        const reader = new FileReader();
        reader.onload = (e) => {
            previewImg.src = e.target.result;
            previewName.textContent = `${file.name} (${formatBytes(file.size)})`;
            placeholder.style.display = "none";
            preview.style.display = "block";
        };
        reader.readAsDataURL(file);
    }

    function formatBytes(bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
        return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    }

    /* ---- Loading state no submit ---- */
    const form = document.getElementById("upload-form");
    const submitBtn = document.getElementById("submit-btn");
    const btnText = document.getElementById("btn-text");
    const btnLoading = document.getElementById("btn-loading");

    if (form) {
        form.addEventListener("submit", () => {
            if (submitBtn) {
                submitBtn.disabled = true;
                if (btnText) btnText.style.display = "none";
                if (btnLoading) btnLoading.style.display = "inline";
            }
        });
    }
})();
