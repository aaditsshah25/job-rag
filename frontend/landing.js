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

  document.addEventListener('DOMContentLoaded', () => {
    bindStart(document.getElementById('startSignInBtn'));
    bindStart(document.getElementById('heroStartBtn'));
    bindStart(document.getElementById('howStartBtn'));

    const heroHowBtn = document.getElementById('heroHowBtn');
    heroHowBtn?.addEventListener('click', () => {
      document.getElementById('how-it-works')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
})();
