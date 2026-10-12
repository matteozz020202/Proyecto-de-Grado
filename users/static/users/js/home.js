(() => {
    const image = document.querySelector('.featured-image[data-fallback]');
    if (image) {
        let recovered = false;
        const fallback = () => {
            if (recovered) return;
            recovered = true;
            image.src = image.dataset.fallback;
            image.alt = 'Imagen de referencia de una cancha de fútbol';
        };
        image.addEventListener('error', fallback);
        if (image.complete && image.naturalWidth === 0) fallback();
    }
    const account = document.querySelector('.account-menu');
    if (!account) return;
    document.addEventListener('click', event => {
        if (!account.contains(event.target)) account.open = false;
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && account.open) {
            account.open = false;
            account.querySelector('summary').focus();
        }
    });
})();
