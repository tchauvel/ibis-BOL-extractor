/**
 * app.js — Unified Vision Extractor UI Logic
 * Migrated to Event Delegation for CSP Compliance.
 */

document.addEventListener('DOMContentLoaded', () => {
    const uploadZone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('file-input');
    const uploadBtn = document.getElementById('upload-btn');
    const resultsSection = document.getElementById('results-section');
    const resultsList = document.getElementById('results-list');
    const clearBtn = document.getElementById('clear-btn');

    // ─── Drag & Drop ─────────────────────────────────────────────────────────

    uploadZone.addEventListener('click', (e) => {
        if (e.target !== uploadBtn && !uploadBtn.contains(e.target)) fileInput.click();
    });

    uploadBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput.click();
    });

    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('drag-over');
    });

    uploadZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('drag-over');
    });

    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('drag-over');
        const validExts = ['.pdf', '.png', '.jpg', '.jpeg', '.webp'];
        const files = Array.from(e.dataTransfer.files).filter(f => {
            const name = f.name.toLowerCase();
            return validExts.some(ext => name.endsWith(ext));
        });
        if (files.length > 0) processFiles(files);
    });

    fileInput.addEventListener('change', (e) => {
        const files = Array.from(e.target.files);
        if (files.length > 0) processFiles(files);
        fileInput.value = ''; 
    });

    clearBtn.addEventListener('click', () => {
        resultsList.innerHTML = '';
        resultsSection.classList.remove('visible');
    });

    // ─── Event Delegation (CSP Compliant) ────────────────────────────────────

    resultsList.addEventListener('click', (e) => {
        // 1. Toggle Card
        const header = e.target.closest('.card-header');
        if (header) {
            const cardId = header.parentElement.id;
            toggleCard(cardId);
            return;
        }

        // 2. JSON Actions (Copy/Download)
        const actionBtn = e.target.closest('.json-action-btn');
        if (actionBtn) {
            e.stopPropagation();
            const action = actionBtn.dataset.action;
            const card = actionBtn.closest('.result-card');
            const cardId = card.id;

            if (action === 'copy') {
                copyJson(actionBtn, cardId);
            } else if (action === 'download') {
                downloadJson(cardId);
            }
        }
    });

    // ─── Process Files ───────────────────────────────────────────────────────

    async function processFiles(files) {
        resultsSection.classList.add('visible');
        for (const file of files) {
            const processingId = showProcessing(file.name);
            try {
                const result = await uploadAndProcess(file);
                removeProcessing(processingId);
                showResult(file.name, result);
            } catch (error) {
                removeProcessing(processingId);
                showError(file.name, error.message);
            }
        }
    }

    async function uploadAndProcess(file) {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(`/extract`, {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Server error' }));
            throw new Error(error.detail || 'Extraction failed');
        }

        return await response.json();
    }

    function showProcessing(filename) {
        const id = `proc-${Date.now()}`;
        const card = document.createElement('div');
        card.className = 'processing-card';
        card.id = id;
        card.innerHTML = `
            <div class="spinner"></div>
            <div class="processing-text">
                Analyzing <span class="processing-filename">${escapeHtml(filename)}</span> with Advanced AI Vision...
            </div>
        `;
        resultsList.prepend(card);
        return id;
    }

    function removeProcessing(id) {
        const card = document.getElementById(id);
        if (card) card.remove();
    }

    // ─── Result Card Rendering ───────────────────────────────────────────────

    function showResult(filename, response) {
        const cardId = `res-${Date.now()}`;
        const card = document.createElement('div');
        card.className = 'result-card';
        card.id = cardId;

        const pipeline = response._pipeline || {};
        const latency = pipeline.processing_time_ms;
        const timeStr = latency ? (latency > 1000 ?
            `${(latency / 1000).toFixed(1)}s` :
            `${latency}ms`) : '--';

        // Support both new envelope { document_type, data } and legacy flat format
        const docType = response.document_type || 'bol';
        const data = response.data || response;

        // Card subtitle: pick the most meaningful identifier per document type
        const primaryRef = data.bol_number || data.shipment_number || data.house_bol_number || 'N/A';
        const secondaryRef = data.carrier_name || data.container_number || data.consol_number || 'Unknown';
        const docTypeLabel = docType.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

        const displayData = { ...data };

        card.innerHTML = `
            <div class="card-header">
                <div class="card-file-info">
                    <div class="file-icon">📜</div>
                    <div>
                        <div class="file-name">${escapeHtml(filename)}</div>
                        <div class="file-meta">${escapeHtml(docTypeLabel)} · ${escapeHtml(primaryRef)} · ${escapeHtml(secondaryRef)}</div>
                    </div>
                </div>
                <div class="card-badges">
                    <span class="confidence-badge confidence-high">Verified Vision Audit</span>
                    <svg class="toggle-icon expanded" width="16" height="16"><path d="M4 6L8 10L12 6" stroke="currentColor" stroke-width="2"/></svg>
                </div>
            </div>
            
            <div class="pipeline-bar">
                <div class="pipeline-item">
                    <span class="pipeline-label">Model</span>
                    <span class="pipeline-value">${escapeHtml(pipeline.model || 'Gemini 3.1 Flash-Lite')}</span>
                </div>
                <div class="pipeline-divider"></div>
                <div class="pipeline-item">
                    <span class="pipeline-label">Latency</span>
                    <span class="pipeline-value">${timeStr}</span>
                </div>
                <div class="pipeline-divider"></div>
                <div class="pipeline-item">
                    <span class="pipeline-label">Pages</span>
                    <span class="pipeline-value">${pipeline.pages_processed || 1}</span>
                </div>
            </div>

            <div class="card-body expanded">
                <div class="json-toolbar">
                    <span class="json-label">STRUCTURED LOGISTICS DATA</span>
                    <div class="json-actions">
                        <button class="json-action-btn" data-action="copy">Copy JSON</button>
                        <button class="json-action-btn" data-action="download">Download JSON</button>
                    </div>
                </div>
                <div class="json-content">
                    <pre>${syntaxHighlight(JSON.stringify(displayData, null, 2))}</pre>
                </div>
            </div>
        `;

        card.dataset.json = JSON.stringify(response, null, 2);
        card.dataset.filename = filename;
        resultsList.prepend(card);
    }

    function showError(filename, message) {
        const card = document.createElement('div');
        card.className = 'result-card error';
        card.innerHTML = `<div class="card-header"><div class="file-name">${escapeHtml(filename)}</div><div class="file-meta">${escapeHtml(message)}</div></div>`;
        resultsList.prepend(card);
    }

    // ─── Helpers (Local Scope) ───────────────────────────────────────────────

    function toggleCard(id) {
        const card = document.getElementById(id);
        if (!card) return;
        const body = card.querySelector('.card-body');
        const icon = card.querySelector('.toggle-icon');

        body.classList.toggle('expanded');
        icon.classList.toggle('expanded');
    }

    function copyJson(btn, id) {
        const card = document.getElementById(id);
        const json = card.dataset.json;
        navigator.clipboard.writeText(json).then(() => {
            const oldText = btn.innerText;
            btn.innerText = 'Copied!';
            btn.classList.add('success');
            setTimeout(() => {
                btn.innerText = oldText;
                btn.classList.remove('success');
            }, 2000);
        });
    }

    function downloadJson(id) {
        const card = document.getElementById(id);
        const json = card.dataset.json;
        const rawFilename = card.dataset.filename || 'document';
        const blob = new Blob([json], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.download = rawFilename.replace(/\.[^/.]+$/, '') + '_extracted.json';
        a.href = url;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function syntaxHighlight(json) {
        return json.replace(/("(\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?|null)/g, (m) => {
            let cls = 'json-number';
            if (/^"/.test(m)) {
                cls = /:$/.test(m) ? 'json-key' : 'json-string';
            } else if (/true|false/.test(m)) cls = 'json-boolean';
            else if (/null/.test(m)) cls = 'json-null';
            return `<span class="${cls}">${m}</span>`;
        });
    }

    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }
});
