// Reutiliza el placeholder deportivo cuando falla la foto de una reserva.
document.querySelectorAll('.reservation-media').forEach(media => {
    const image = media.querySelector('img');
    if (!image) return;
    const recover = () => {
        image.hidden = true;
        media.querySelector('.court-placeholder').hidden = false;
    };
    image.addEventListener('error', recover);
    if (image.complete && image.naturalWidth === 0) recover();
});
