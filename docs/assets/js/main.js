// Highlight current page in nav
document.addEventListener('DOMContentLoaded', () => {
  const path = location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav-links a').forEach(a => {
    const href = a.getAttribute('href');
    if (href === path) a.classList.add('active');
  });

  // Roadmap milestone expand/collapse
  document.querySelectorAll('.milestone-card').forEach(card => {
    card.addEventListener('click', () => {
      card.classList.toggle('open');
      const toggle = card.querySelector('.toggle');
      if (toggle) toggle.textContent = card.classList.contains('open')
        ? '— collapse'
        : '+ expand details';
    });
  });
});
