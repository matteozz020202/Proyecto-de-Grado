(() => {
    const toggle = document.querySelector('.admin-nav-toggle');
    const links = document.getElementById('admin-navigation');
    if (toggle && links) {
        function setOpen(open) {
            toggle.setAttribute('aria-expanded', String(open));
            toggle.setAttribute('aria-label', open ? 'Cerrar navegación administrativa' : 'Abrir navegación administrativa');
            links.classList.toggle('is-open', open);
        }
        toggle.addEventListener('click', () => setOpen(toggle.getAttribute('aria-expanded') !== 'true'));
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') { setOpen(false); toggle.focus(); }
        });
        document.addEventListener('click', event => {
            if (!event.target.closest('.home-nav')) setOpen(false);
        });
    }
    const period = document.querySelector('[data-period-filter]');
    if (!period) return;
    function updatePeriod() {
        const active = period.querySelector('input[name=periodo]:checked')?.value || 'day';
        period.querySelectorAll('[data-period-field]').forEach(panel => {
            panel.hidden = panel.dataset.periodField !== active;
            panel.querySelectorAll('input').forEach(input => { input.disabled = panel.hidden; input.required = !panel.hidden; });
        });
    }
    period.addEventListener('change', updatePeriod);
    updatePeriod();
})();
