/**
 * HTF Portal Dashboard Logic
 */

document.addEventListener('DOMContentLoaded', function () {
    const UI = {
        totalPages: document.getElementById('total-paginas'),
        totalWorks: document.getElementById('total-trabalhos'),
        processing: document.getElementById('processando'),
        tableBody: document.querySelector('#dados-tabela tbody'),
        refreshIndicator: document.querySelector('.refresh-indicator'),
        noDataSection: document.querySelector('.no-data-container'), // We'll create this container in HTML
        yearSpan: document.getElementById('ano-atual')
    };

    let updateInterval;
    const REFRESH_RATE = 3000;

    // Initial Setup
    if (UI.yearSpan) {
        UI.yearSpan.textContent = new Date().getFullYear();
    }

    if (UI.refreshIndicator) {
        UI.refreshIndicator.addEventListener('click', manualUpdate);
    }

    startUpdating();

    // Page Visibility API to save resources
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            stopUpdating();
        } else {
            manualUpdate(); // Update immediately upon return
            startUpdating();
        }
    });

    function startUpdating() {
        if (!updateInterval) {
            updateInterval = setInterval(fetchData, REFRESH_RATE);
            console.log('▶️ Auto-refresh started');
        }
    }

    function stopUpdating() {
        if (updateInterval) {
            clearInterval(updateInterval);
            updateInterval = null;
            console.log('⏸️ Auto-refresh paused');
        }
    }

    async function manualUpdate() {
        if (UI.refreshIndicator) UI.refreshIndicator.classList.add('refreshing');
        await fetchData();
        setTimeout(() => {
            if (UI.refreshIndicator) UI.refreshIndicator.classList.remove('refreshing');
        }, 500);
    }

    function fetchData() {
        return fetch('/api/data', {
            headers: {
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            }
        })
            .then(response => {
                if (!response.ok) throw new Error('Network response was not ok');
                return response.json();
            })
            .then(data => {
                updateDashboard(data);
            })
            .catch(error => {
                console.error('Fetch error:', error);
                // Optional: Show error state in UI
            });
    }

    function updateDashboard(data) {
        // Update Stats with simplistic animation
        updateNumber(UI.totalPages, data.total_paginas || 0);
        updateNumber(UI.totalWorks, data.total_trabalhos || 0);
        updateNumber(UI.processing, data.processando || 0);

        // Update Table
        renderTable(data.dados || []);

        // Handle Alerts (using a toaster or dedicated section would be better, but sticking to logic)
        handleAlerts(data.mensagem_servico, data.mensagem);
    }

    function updateNumber(element, newValue) {
        if (!element) return;
        const current = parseInt(element.textContent.replace(/\D/g, '')) || 0;
        if (current !== newValue) {
            // Simple flash effect could be added here
            element.textContent = newValue.toLocaleString();
            element.style.color = 'var(--primary-dark)';
            setTimeout(() => element.style.color = '', 300);
        }
    }

    function renderTable(items) {
        if (!UI.tableBody) return;

        if (items.length === 0) {
            UI.tableBody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center py-5">
                        <div class="no-data-placeholder">
                            <i class="fas fa-inbox fa-2x mb-3 text-muted"></i>
                            <p class="text-muted">Nenhum trabalho na fila</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        const html = items.map(item => {
            const statusClass = getStatusClass(item.State);
            const percentage = item.Percentage || 0;

            return `
                <tr class="fade-in">
                    <td data-label="Nome"><strong>${item.Name || 'N/A'}</strong></td>
                    <td data-label="Status">
                        <span class="status-badge ${statusClass}">
                            ${getStatusIcon(statusClass)} ${item.State || 'Desconhecido'}
                        </span>
                    </td>
                    <td data-label="Progresso">
                        <div class="d-flex align-items-center gap-2">
                            <div class="flex-grow-1">
                                <div class="progress-bar-custom">
                                    <div class="progress-fill" style="width: ${percentage}%"></div>
                                </div>
                            </div>
                            <small class="text-muted" style="min-width: 35px">${percentage}%</small>
                        </div>
                    </td>
                    <td data-label="Páginas"><span class="badge bg-light text-dark border">${item.Pages || 0}</span></td>
                    <td data-label="Usuário">${item.User || 'N/A'}</td>
                    <td data-label="Site">${item.Site || 'N/A'}</td>
                    <td data-label="Hora" class="text-muted small">${item.Time || 'N/A'}</td>
                </tr>
            `;
        }).join('');

        // Basic DOM diffing could go here, but full replace is fine for this scale
        if (UI.tableBody.innerHTML !== html) {
            UI.tableBody.innerHTML = html;
        }
    }

    function getStatusClass(status) {
        if (!status) return 'status-pending';
        const s = status.toLowerCase();
        if (s.includes('process')) return 'status-processing';
        if (s.includes('conclu') || s.includes('complete') || s.includes('finaliz')) return 'status-completed';
        if (s.includes('erro') || s.includes('error') || s.includes('falha')) return 'status-error';
        return 'status-pending';
    }

    function getStatusIcon(cssClass) {
        if (cssClass === 'status-processing') return '<i class="fas fa-cog fa-spin"></i>';
        if (cssClass === 'status-completed') return '<i class="fas fa-check"></i>';
        if (cssClass === 'status-error') return '<i class="fas fa-times"></i>';
        return '<i class="fas fa-clock"></i>';
    }

    function handleAlerts(serviceMsg, generalMsg) {
        // Implementation for alerts if needed, or rely on server-side template for initial load
        // Dynamic alerts would need a placeholder in DOM
        const alertArea = document.getElementById('alert-area');
        if (!alertArea) return; // Add this container to HTML

        let html = '';
        if (serviceMsg) {
            html += `<div class="alert alert-danger shadow-sm border-0"><i class="fas fa-exclamation-triangle me-2"></i> ${serviceMsg}</div>`;
        }
        if (generalMsg) {
            html += `<div class="alert alert-warning shadow-sm border-0"><i class="fas fa-info-circle me-2"></i> ${generalMsg}</div>`;
        }
        alertArea.innerHTML = html;
    }
});
