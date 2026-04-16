// Marketing page interactions
(function () {
  function bindStart(el) {
    if (!el) return;
    el.addEventListener('click', () => {
      if (typeof window.startSignInFlow === 'function') {
        window.startSignInFlow();
      }
    });
  }

  function scrollToTarget(targetId) {
    const target = document.getElementById(targetId);
    if (!target) return;
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  document.addEventListener('DOMContentLoaded', () => {
    bindStart(document.getElementById('startSignInBtn'));
    bindStart(document.getElementById('heroStartBtn'));
    bindStart(document.getElementById('howStartBtn'));
    bindStart(document.getElementById('ctaStartBtn'));

    document.querySelectorAll('[data-scroll-target]').forEach((button) => {
      button.addEventListener('click', () => {
        const targetId = button.getAttribute('data-scroll-target');
        if (targetId) {
          scrollToTarget(targetId);
        }
      });
    });

    const heroHowBtn = document.getElementById('heroHowBtn');
    heroHowBtn?.addEventListener('click', () => {
      scrollToTarget('workflow');
    });
  });
})();
