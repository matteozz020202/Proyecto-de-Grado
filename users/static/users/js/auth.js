// El historial puede restaurar un formulario anterior a la rotación CSRF del login.
// Solicita una página nueva: Django genera el token; no se copia ni almacena en JS.
window.addEventListener('pageshow', event => {
    if (event.persisted) window.location.reload();
});
