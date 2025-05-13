// Control del menú hamburguesa
document.querySelector('.nav-toggle').addEventListener('click', () => {
    document.querySelector('.nav-links').classList.toggle('active');
});

// Cerrar menú al hacer click fuera
document.addEventListener('click', (e) => {
    if (!e.target.closest('.main-nav')) {
        document.querySelector('.nav-links').classList.remove('active');
    }
});

// Ajustar altura del chat en móviles
window.addEventListener('resize', () => {
    const chatBox = document.getElementById('chatBox');
    if (window.innerWidth < 768) {
        chatBox.style.height = `${window.innerHeight - 200}px`;
    }
});