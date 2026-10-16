(() => {
    document.querySelectorAll('.venue-image[data-fallback]').forEach(image => {
        let recovered = false;
        const recover = () => {
            if (recovered) return;
            recovered = true;
            image.src = image.dataset.fallback;
            image.alt = 'Imagen de referencia de una cancha de fútbol';
        };
        image.addEventListener('error', recover);
        if (image.complete && image.naturalWidth === 0) recover();
    });
})();
