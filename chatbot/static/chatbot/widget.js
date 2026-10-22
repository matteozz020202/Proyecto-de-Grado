(() => {
  'use strict';
  const root = document.querySelector('[data-booking-chat]');
  if (!root) return;
  const panel = root.querySelector('.booking-chat-panel');
  const launch = root.querySelector('.booking-chat-launch');
  const log = root.querySelector('.booking-chat-log');
  const form = root.querySelector('form');
  const input = root.querySelector('textarea');
  const status = root.querySelector('[role="status"]');
  let busy = false;
  let loaded = false;
  let csrf = '';
  const catalog = '/reservar/';
  function problem(message) { const error = new Error(message); error.safe = true; return error; }
  function bubble(text, user = false) {
    const node = document.createElement('p');
    node.className = `booking-chat-bubble${user ? ' is-user' : ''}`;
    node.textContent = text;
    log.append(node);
    while (log.children.length > 16) log.firstElementChild.remove();
    log.scrollTop = log.scrollHeight;
  }
  function setBusy(value) {
    busy = value;
    root.querySelectorAll('button:not(.booking-chat-close):not(.booking-chat-launch)').forEach(button => { button.disabled = value; });
    status.textContent = value ? 'Buscando opciones…' : '';
    log.setAttribute('aria-busy', String(value));
  }
  async function request(endpoint, data) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 35000);
    try {
      // Obtener token vigente: no conservar el token de un formulario anterior al login.
      const stateResponse = await fetch(root.dataset.state, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal });
      if (!stateResponse.ok) throw problem('No pude recuperar la sesión. Vuelve a intentarlo.');
      const state = await stateResponse.json();
      csrf = state.csrf_token;
      if (!endpoint) return state;
      const response = await fetch(endpoint, { method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify(data) });
      if (!response.ok) {
        if (response.status === 403) throw problem('Tu sesión cambió. Recarga la página y vuelve a intentarlo.');
        const error = await response.json();
        throw problem(error.message || 'No pude procesar la consulta. Inténtalo de nuevo.');
      }
      return await response.json();
    } finally { clearTimeout(timeout); }
  }
  function failure(error) {
    bubble(error.name === 'AbortError' ? 'La consulta tardó demasiado. Inténtalo de nuevo.' : (error.safe ? error.message : 'El asistente no está disponible ahora. Inténtalo de nuevo.'));
    const link = document.createElement('a');
    link.className = 'booking-chat-fallback'; link.href = catalog; link.textContent = 'Ver establecimientos';
    log.append(link); log.scrollTop = log.scrollHeight;
  }
  function render(data) {
    log.querySelectorAll('.booking-chat-options').forEach(node => node.remove());
    bubble(data.message);
    if (!data.options?.length) return;
    const options = document.createElement('div'); options.className = 'booking-chat-options';
    for (const option of data.options) {
      const card = document.createElement('article'); card.className = 'booking-chat-option';
      const day = new Date(`${option.date}T12:00:00`);
      const texts = [option.venue, option.court, `${day.toLocaleDateString('es-CO')} · ${option.start_time} – ${option.end_time}`,
        new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(Number(option.price))];
      texts.forEach((text, index) => { const node = document.createElement(index === 0 ? 'strong' : 'span'); node.textContent = text; card.append(node); });
      const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Reservar esta cancha';
      button.addEventListener('click', async () => {
        if (busy) return; setBusy(true);
        try {
          const result = await request(root.dataset.select, { option_id: option.option_id });
          const url = new URL(result.redirect_url, location.origin);
          if (url.origin !== location.origin) throw problem('No pude abrir esta opción.');
          location.assign(url.href);
        } catch (error) { failure(error); } finally { setBusy(false); }
      });
      card.append(button); options.append(card);
    }
    log.append(options); log.scrollTop = log.scrollHeight;
  }
  async function open() {
    panel.hidden = false; launch.setAttribute('aria-expanded', 'true'); input.focus(); viewport();
    if (loaded || busy) return;
    setBusy(true);
    try { render(await request()); loaded = true; } catch (error) { failure(error); } finally { setBusy(false); }
  }
  function close() { panel.hidden = true; launch.setAttribute('aria-expanded', 'false'); launch.focus(); }
  launch.addEventListener('click', () => panel.hidden ? open() : close());
  root.querySelector('.booking-chat-close').addEventListener('click', close);
  panel.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); close(); } });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault(); const text = input.value.trim();
    if (busy || !text || text.length > 500) return;
    bubble(text, true); input.value = ''; setBusy(true);
    try { render(await request(root.dataset.message, { message: text })); } catch (error) { failure(error); } finally { setBusy(false); input.focus(); }
  });
  root.querySelector('.booking-chat-reset').addEventListener('click', async () => {
    if (busy) return; setBusy(true);
    try { const data = await request(root.dataset.reset, {}); log.replaceChildren(); render(data); input.focus(); } catch (error) { failure(error); } finally { setBusy(false); }
  });
  function viewport() {
    const view = window.visualViewport;
    if (!view || window.innerWidth > 600) return;
    root.style.setProperty('--chat-height', `${Math.max(180, Math.min(720, view.height - 16))}px`);
    root.style.setProperty('--chat-bottom', `${Math.max(8, window.innerHeight - view.height - view.offsetTop + 8)}px`);
  }
  window.visualViewport?.addEventListener('resize', viewport);
  window.visualViewport?.addEventListener('scroll', viewport);
  window.addEventListener('resize', viewport);
})();
