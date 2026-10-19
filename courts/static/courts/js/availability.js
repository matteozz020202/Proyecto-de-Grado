(() => {
    const photo = document.querySelector('.availability-image');
    if (photo) {
        const showPlaceholder = () => {
            photo.hidden = true;
            document.querySelector('.court-placeholder').hidden = false;
        };
        photo.addEventListener('error', showPlaceholder);
        if (photo.complete && photo.naturalWidth === 0) showPlaceholder();
    }
    const summary = document.querySelector('.booking-summary');
    if (!summary) return;
    const slots = document.querySelectorAll('.time-slot');
    slots.forEach(slot => slot.addEventListener('click', event => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        slots.forEach(item => item.removeAttribute('aria-current'));
        slot.setAttribute('aria-current', 'true');
        document.getElementById('summary-range').textContent = slot.dataset.range;
        document.getElementById('summary-total').textContent = slot.dataset.total;
        document.getElementById('summary-deposit').textContent = slot.dataset.deposit;
        document.getElementById('continue-booking').href = slot.href;
        summary.hidden = false;
    }));
})();
