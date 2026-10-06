(() => {
    const payload = document.getElementById('dashboard-chart-data');
    if (!payload) return;
    const data = JSON.parse(payload.textContent);
    const number = new Intl.NumberFormat('es-CO', {maximumFractionDigits: 2});
    const missingLibrary = typeof Chart === 'undefined';

    function empty(canvas, id, message) {
        canvas.parentElement.hidden = true;
        const text = document.getElementById(id);
        text.hidden = false;
        if (message) text.textContent = message;
    }

    function occupancyChart(id, type, rows) {
        const canvas = document.getElementById(id);
        if (!rows.some(row => row.occupancy_rate !== null)) {
            empty(canvas, `${id}-empty`);
            return;
        }
        if (missingLibrary) {
            empty(canvas, `${id}-empty`, 'No se pudo cargar el gráfico. Consulta la tabla de datos.');
            canvas.closest('section').querySelector('details').open = true;
            return;
        }
        new Chart(canvas, {
            type,
            data: {
                labels: rows.map(row => row.label),
                datasets: [{label: 'Ocupación', data: rows.map(row => row.occupancy_rate),
                    backgroundColor: '#198754', borderColor: '#146c43', borderWidth: 2,
                    tension: 0.2, spanGaps: false}]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {y: {min: 0, max: 100, title: {display: true, text: 'Ocupación %'}}},
                plugins: {
                    legend: {display: false},
                    tooltip: {callbacks: {label: context => {
                        const row = rows[context.dataIndex];
                        return [`Ocupación: ${number.format(row.occupancy_rate)}%`,
                            `Reservadas: ${number.format(row.reserved_hours)} h`,
                            `Disponibles: ${number.format(row.available_hours)} h`];
                    }}}
                }
            }
        });
    }

    occupancyChart('occupancy-day', 'bar', data.occupancy_by_day);
    occupancyChart('occupancy-hour', 'line', data.occupancy_by_time_slot);
    const canvas = document.getElementById('reservation-status');
    const statuses = data.reservation_status_distribution;
    if (!statuses.length) {
        empty(canvas, 'status-empty');
    } else if (missingLibrary) {
        empty(canvas, 'status-empty', 'No se pudo cargar el gráfico. Consulta la tabla de datos.');
        canvas.closest('section').querySelector('details').open = true;
    } else {
        const colors = {PENDING_PAYMENT: '#ffc107', CONFIRMED: '#0d6efd', COMPLETED: '#198754',
            CANCELLED: '#dc3545', EXPIRED: '#6c757d'};
        new Chart(canvas, {
            type: 'doughnut',
            data: {labels: statuses.map(row => row.label), datasets: [{
                data: statuses.map(row => row.count),
                backgroundColor: statuses.map(row => colors[row.status])
            }]},
            options: {responsive: true, maintainAspectRatio: false,
                plugins: {legend: {position: 'bottom'}}}
        });
    }
})();
