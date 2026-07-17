// phoebe-data-skills - shared engagement layer
(function () {
  // reading progress bar
  var bar = document.querySelector('.progress');
  if (bar) {
    addEventListener('scroll', function () {
      var h = document.documentElement;
      bar.style.width = (h.scrollTop / (h.scrollHeight - h.clientHeight)) * 100 + '%';
    }, { passive: true });
  }

  // scroll reveal
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
  }, { threshold: 0.08 });
  document.querySelectorAll('.reveal').forEach(function (el) { io.observe(el); });

  // count-up stats
  var cio = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      var el = e.target, target = parseInt(el.dataset.count, 10), t0 = null;
      function tick(t) {
        if (!t0) t0 = t;
        var p = Math.min((t - t0) / 900, 1);
        el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3))).toLocaleString();
        if (p < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
      cio.unobserve(el);
    });
  }, { threshold: 0.4 });
  document.querySelectorAll('[data-count]').forEach(function (el) { cio.observe(el); });

  // copy buttons
  document.querySelectorAll('.copy-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var pre = btn.closest('.code-card').querySelector('pre');
      navigator.clipboard.writeText(pre.textContent).then(function () {
        var old = btn.textContent; btn.textContent = 'Copied!';
        setTimeout(function () { btn.textContent = old; }, 1400);
      });
    });
  });

  // pipeline rail: highlight active step while scrolling
  var nodes = document.querySelectorAll('.rail-node[data-step]');
  if (nodes.length) {
    var sections = Array.prototype.map.call(nodes, function (n) {
      return document.getElementById('step-' + n.dataset.step);
    });
    addEventListener('scroll', function () {
      var y = scrollY + innerHeight * 0.35, idx = -1;
      sections.forEach(function (s, i) { if (s && s.offsetTop <= y) idx = i; });
      nodes.forEach(function (n, i) { n.classList.toggle('active', i === idx); });
    }, { passive: true });
  }

  // lightbox zoom for chart images
  document.querySelectorAll('.chart-card img').forEach(function (img) {
    img.addEventListener('click', function () {
      var o = document.createElement('div');
      o.style.cssText = 'position:fixed;inset:0;background:rgba(15,23,42,.92);z-index:100;display:flex;align-items:center;justify-content:center;cursor:zoom-out;padding:4vw';
      var big = document.createElement('img');
      big.src = img.src; big.style.cssText = 'max-width:100%;max-height:100%;border-radius:8px';
      o.appendChild(big); o.addEventListener('click', function () { o.remove(); });
      document.body.appendChild(o);
    });
  });
})();
