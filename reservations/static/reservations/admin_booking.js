(() => {
    const form = document.getElementById('manual-booking-form');
    if (!form) return;
    const search = form.querySelector('.user-search');
    const input = document.getElementById('user-query');
    const userId = document.getElementById('usuario');
    const results = document.getElementById('user-results');
    const status = document.getElementById('user-search-status');
    const selected = document.getElementById('selected-user');
    const court = document.getElementById('cancha');
    const date = document.getElementById('fecha');
    const start = document.getElementById('hora_inicio');
    const end = document.getElementById('hora_fin');
    let timer, controller, sequence = 0, active = -1, matches = [];
    function preview() {
        document.getElementById('preview-user').textContent = userId.value ? document.getElementById('selected-user-username').textContent : '—';
        document.getElementById('preview-court').textContent = court.value ? court.selectedOptions[0].textContent.trim() : '—';
        document.getElementById('preview-date').textContent = date.value ? date.value.split('-').reverse().join('/') : '—';
        document.getElementById('preview-time').textContent = start.value && end.value ? `${start.value} – ${end.value}` : '—';
    }
    function close() {
        results.hidden = true;
        input.setAttribute('aria-expanded', 'false');
        input.removeAttribute('aria-activedescendant');
        active = -1;
    }
    function cancelSearch() {
        clearTimeout(timer);
        if (controller) controller.abort();
        sequence += 1;
    }
    function select(user) {
        cancelSearch();
        userId.value = user.id;
        input.value = user.username;
        input.setCustomValidity('');
        document.getElementById('selected-user-name').textContent = user.name || user.username;
        document.getElementById('selected-user-username').textContent = `@${user.username}`;
        document.getElementById('selected-user-email').textContent = user.email;
        selected.hidden = false;
        status.textContent = 'Usuario seleccionado.';
        close();
        preview();
    }
    function mark(index) {
        active = (index + matches.length) % matches.length;
        Array.from(results.children).forEach((item, i) => item.setAttribute('aria-selected', String(i === active)));
        input.setAttribute('aria-activedescendant', results.children[active].id);
        results.children[active].scrollIntoView({block: 'nearest'});
    }
    input.addEventListener('input', () => {
        cancelSearch();
        userId.value = '';
        selected.hidden = true;
        input.setCustomValidity('');
        close();
        preview();
        const query = input.value.trim();
        if (query.length < 2) {
            status.textContent = 'Escribe al menos 2 caracteres para buscar un usuario.';
            return;
        }
        const requestSequence = sequence;
        status.textContent = 'Buscando usuarios…';
        timer = setTimeout(async () => {
            controller = new AbortController();
            try {
                const url = new URL(search.dataset.searchUrl, location.origin);
                url.searchParams.set('q', query);
                const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal, headers: {Accept: 'application/json'}});
                if (!response.ok || response.redirected) throw new Error('search');
                const data = await response.json();
                if (requestSequence !== sequence) return;
                matches = data.results;
                results.replaceChildren();
                matches.forEach((user, i) => {
                    const item = document.createElement('li');
                    item.id = `user-option-${i}`;
                    item.setAttribute('role', 'option');
                    item.setAttribute('aria-selected', 'false');
                    const name = document.createElement('strong');
                    name.textContent = `${user.username}${user.name ? ` — ${user.name}` : ''}`;
                    const email = document.createElement('small');
                    email.textContent = user.email;
                    item.append(name, email);
                    item.addEventListener('click', () => { select(user); input.focus(); });
                    results.append(item);
                });
                results.hidden = !matches.length;
                input.setAttribute('aria-expanded', String(Boolean(matches.length)));
                status.textContent = matches.length ? `${matches.length} resultados. Usa las flechas y Enter para seleccionar.` : 'No se encontraron usuarios.';
            } catch (error) {
                if (error.name === 'AbortError' || requestSequence !== sequence) return;
                status.textContent = 'No se pudo buscar. Revisa tu conexión o vuelve a iniciar sesión.';
                close();
            }
        }, 300);
    });
    input.addEventListener('keydown', event => {
        if (event.key === 'Escape') { cancelSearch(); close(); return; }
        if (results.hidden || !matches.length) return;
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            mark(active < 0 ? (event.key === 'ArrowDown' ? 0 : matches.length - 1) : active + (event.key === 'ArrowDown' ? 1 : -1));
        } else if (event.key === 'Enter') {
            event.preventDefault();
            if (active >= 0) select(matches[active]);
        }
    });
    document.getElementById('change-user').addEventListener('click', () => {
        input.value = '';
        input.dispatchEvent(new Event('input'));
        input.focus();
    });
    document.addEventListener('click', event => { if (!search.contains(event.target)) { cancelSearch(); close(); } });
    form.addEventListener('submit', event => {
        if (!userId.value) {
            event.preventDefault();
            input.setCustomValidity('Selecciona un usuario de los resultados.');
            input.reportValidity();
            input.focus();
        }
    });
    [court, date, start, end].forEach(field => field.addEventListener('input', preview));
    preview();
})();
