(() => {
    const form = document.getElementById('dashboard-analysis-form');
    if (!form) return;
    const button = document.getElementById('generate-analysis');
    const result = document.getElementById('dashboard-analysis-result');
    let loading = false;

    function message(text, state) {
        result.replaceChildren();
        const paragraph = document.createElement('p');
        paragraph.className = state === 'ERROR' ? 'alert alert-warning mb-0' : 'text-muted';
        paragraph.textContent = text;
        result.append(paragraph);
        result.dataset.state = state;
    }

    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (loading || button.disabled) return;
        loading = true;
        button.disabled = true;
        button.textContent = 'Generando análisis…';
        result.setAttribute('aria-busy', 'true');
        message('Analizando los indicadores de los filtros aplicados…', 'LOADING');
        try {
            const response = await fetch(form.action, {
                method: 'POST', body: new FormData(form), credentials: 'same-origin',
                headers: {'Accept': 'application/json'}
            });
            if (response.redirected) throw new Error('session');
            const payload = await response.json();
            if (!['SUCCESS', 'ERROR'].includes(payload.state) || typeof payload.html !== 'string') {
                throw new Error('format');
            }
            // HTML de nuestro endpoint: Django escapa todos los textos generados por IA.
            result.innerHTML = payload.html;
            result.dataset.state = payload.state;
        } catch (error) {
            message('No se pudo completar el análisis. Revisa tu conexión o recarga la página para comprobar tu sesión; los indicadores siguen disponibles.', 'ERROR');
        } finally {
            loading = false;
            button.disabled = false;
            button.textContent = 'Generar análisis';
            result.removeAttribute('aria-busy');
        }
    });
})();
