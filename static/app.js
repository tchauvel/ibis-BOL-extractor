/**
 * app.js — Upload logic, API communication, and JSON result display.
 *
 * Single-file script for the one-button upload UI.
 * Handles drag-and-drop, file input, progress indication, and
 * syntax-highlighted JSON rendering.
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
        if (e.target !== uploadBtn && !uploadBtn.contains(e.target)) {
            fileInput.click();
        }
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
        if (files.length > 0) {
            processFiles(files);
        }
    });

    fileInput.addEventListener('change', (e) => {
        const files = Array.from(e.target.files);
        if (files.length > 0) {
            processFiles(files);
        }
        fileInput.value = ''; // Reset for re-uploads
    });

    // ─── Clear Results ───────────────────────────────────────────────────────

    clearBtn.addEventListener('click', () => {
        resultsList.innerHTML = '';
        resultsSection.classList.remove('visible');
    });

    // ─── Process Files ───────────────────────────────────────────────────────

    async function processFiles(files) {
        resultsSection.classList.add('visible');
        
        await Promise.all(files.map(async (file) => {
            const processingId = showProcessing(file.name);
            try {
                const result = await uploadAndProcess(file);
                removeProcessing(processingId);
                showResult(file.name, result);
            } catch (error) {
                removeProcessing(processingId);
                showError(file.name, error.message);
            }
        }));
    }

    async function uploadAndProcess(file) {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch('/api/process', {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(errorData.detail || `Server error: ${response.status}`);
        }

        return await response.json();
    }

    // ─── Processing Indicator ────────────────────────────────────────────────

    function showProcessing(filename) {
        const id = `processing-${Date.now()}`;
        const card = document.createElement('div');
        card.className = 'processing-card';
        card.id = id;
        card.innerHTML = `
            <div class="spinner"></div>
            <div class="processing-text">
                Processing <span class="processing-filename">${escapeHtml(filename)}</span>…
            </div>
        `;
        resultsList.prepend(card);
        return id;
    }

    function removeProcessing(id) {
        const card = document.getElementById(id);
        if (card) card.remove();
    }

    // ─── Result Card ─────────────────────────────────────────────────────────

    function showResult(filename, data) {
        const cardId = `result-${Date.now()}`;
        const confidence = data.extraction_confidence || 0;
        const confLevel = confidence >= 0.7 ? 'high' : confidence >= 0.4 ? 'medium' : 'low';
        const docType = data.document_subtype || data.document_type || 'unknown';
        const method = data.extraction_method || 'unknown';
        const warnings = data.extraction_warnings || [];

        const card = document.createElement('div');
        card.className = 'result-card';
        card.id = cardId;

        // Remove raw_text from display (keep it clean)
        const displayData = { ...data };
        if (displayData.raw_text && displayData.raw_text.length > 200) {
            displayData.raw_text = displayData.raw_text.substring(0, 200) + '… [truncated]';
        }

        const jsonStr = JSON.stringify(displayData, null, 2);

        card.innerHTML = `
            <div class="card-header" onclick="toggleCard('${cardId}')">
                <div class="card-file-info">
                    <div class="file-icon">
                        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                            <rect x="3" y="2" width="12" height="14" rx="1.5" stroke="currentColor" stroke-width="1.5" fill="none"/>
                            <line x1="6" y1="6" x2="12" y2="6" stroke="currentColor" stroke-width="1"/>
                            <line x1="6" y1="9" x2="11" y2="9" stroke="currentColor" stroke-width="1"/>
                            <line x1="6" y1="12" x2="9" y2="12" stroke="currentColor" stroke-width="1"/>
                        </svg>
                    </div>
                    <div>
                        <div class="file-name">${escapeHtml(filename)}</div>
                        <div class="file-meta">${docType} · ${method}</div>
                    </div>
                </div>
                <div class="card-badges">
                    <span class="confidence-badge confidence-${confLevel}">
                        ${Math.round(confidence * 100)}% confidence
                    </span>
                    <svg class="toggle-icon expanded" width="16" height="16" viewBox="0 0 16 16" fill="none">
                        <path d="M4 6L8 10L12 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </div>
            </div>
            ${warnings.length > 0 ? `
                <div class="warnings-section">
                    ${warnings.map(w => `<div class="warning-item">${escapeHtml(w)}</div>`).join('')}
                </div>
            ` : ''}
            <div class="card-body expanded">
                <div class="json-toolbar">
                    <div class="json-toolbar-left">
                        <span class="json-label">JSON Output</span>
                    </div>
                    <button class="copy-btn" onclick="copyJson(this, '${cardId}')">
                        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                            <rect x="4" y="4" width="7" height="7" rx="1" stroke="currentColor" stroke-width="1.2"/>
                            <path d="M8 4V2.5C8 1.67 7.33 1 6.5 1H2.5C1.67 1 1 1.67 1 2.5V6.5C1 7.33 1.67 8 2.5 8H4" stroke="currentColor" stroke-width="1.2"/>
                        </svg>
                        Copy
                    </button>
                </div>
                <div class="json-content">
                    <pre>${syntaxHighlight(jsonStr)}</pre>
                </div>
            </div>
        `;

        // Store raw JSON for copy
        card.dataset.json = JSON.stringify(displayData, null, 2);

        resultsList.prepend(card);
    }

    function showError(filename, message) {
        const card = document.createElement('div');
        card.className = 'result-card';
        card.innerHTML = `
            <div class="card-header">
                <div class="card-file-info">
                    <div class="file-icon" style="background: var(--error-bg); color: var(--error);">
                        <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                            <circle cx="9" cy="9" r="7" stroke="currentColor" stroke-width="1.5"/>
                            <path d="M6 6L12 12M12 6L6 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                        </svg>
                    </div>
                    <div>
                        <div class="file-name">${escapeHtml(filename)}</div>
                        <div class="file-meta" style="color: var(--error);">${escapeHtml(message)}</div>
                    </div>
                </div>
                <span class="confidence-badge confidence-low">Failed</span>
            </div>
        `;
        resultsList.prepend(card);
    }

    // ─── Helpers ─────────────────────────────────────────────────────────────

    window.toggleCard = function(cardId) {
        const card = document.getElementById(cardId);
        if (!card) return;
        const body = card.querySelector('.card-body');
        const icon = card.querySelector('.toggle-icon');
        if (body) body.classList.toggle('expanded');
        if (icon) icon.classList.toggle('expanded');
    };

    window.copyJson = function(btn, cardId) {
        const card = document.getElementById(cardId);
        if (!card) return;
        const json = card.dataset.json;
        navigator.clipboard.writeText(json).then(() => {
            btn.classList.add('copied');
            btn.innerHTML = `
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <path d="M2 6L5 9L10 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                Copied!
            `;
            setTimeout(() => {
                btn.classList.remove('copied');
                btn.innerHTML = `
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                        <rect x="4" y="4" width="7" height="7" rx="1" stroke="currentColor" stroke-width="1.2"/>
                        <path d="M8 4V2.5C8 1.67 7.33 1 6.5 1H2.5C1.67 1 1 1.67 1 2.5V6.5C1 7.33 1.67 8 2.5 8H4" stroke="currentColor" stroke-width="1.2"/>
                    </svg>
                    Copy
                `;
            }, 2000);
        });
    };

    function syntaxHighlight(json) {
        return json.replace(
            /("(\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?|null)/g,
            (match) => {
                let cls = 'json-number';
                if (/^"/.test(match)) {
                    if (/:$/.test(match)) {
                        cls = 'json-key';
                        // Remove the colon from the match for cleaner display
                        return `<span class="${cls}">${match.slice(0, -1)}</span>:`;
                    } else {
                        cls = 'json-string';
                    }
                } else if (/true|false/.test(match)) {
                    cls = 'json-boolean';
                } else if (/null/.test(match)) {
                    cls = 'json-null';
                }
                return `<span class="${cls}">${match}</span>`;
            }
        );
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
});
