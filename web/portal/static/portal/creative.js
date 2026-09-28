// Creative Studio: live previews + client-side PNG export per platform size (cover-cropped master image).
(() => {
  const $ = (s) => document.querySelector(s);
  let image = null;
  const headline = () => $('#cr-headline').value;
  const cta = () => $('#cr-cta').value;

  function refresh() {
    document.querySelectorAll('.preview').forEach((p) => {
      p.querySelector('.headline').textContent = headline();
      p.querySelector('.cta').textContent = cta();
      const img = p.querySelector('img');
      if (image) { img.src = image.src; img.hidden = false; }
    });
  }

  async function exportSize(p) {
    const w = +p.dataset.w, h = +p.dataset.h;
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    const g = ctx.createLinearGradient(0, 0, w, h);
    g.addColorStop(0, '#0f7a45'); g.addColorStop(1, '#0b3d26');
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    if (image) {
      const s = Math.max(w / image.width, h / image.height);
      ctx.drawImage(image, (w - image.width * s) / 2, (h - image.height * s) / 2, image.width * s, image.height * s);
      const shade = ctx.createLinearGradient(0, h * 0.4, 0, h);
      shade.addColorStop(0, 'rgba(0,0,0,0)'); shade.addColorStop(1, 'rgba(0,0,0,0.65)');
      ctx.fillStyle = shade; ctx.fillRect(0, 0, w, h);
    }
    const pad = w * 0.06, fs = Math.round(Math.min(w, h) * 0.075);
    ctx.fillStyle = '#fff';
    ctx.font = `700 ${fs}px system-ui, sans-serif`;
    const lines = []; let line = '';
    for (const word of headline().split(' ')) {
      const t = line ? `${line} ${word}` : word;
      if (ctx.measureText(t).width > w - pad * 2 && line) { lines.push(line); line = word; } else line = t;
    }
    lines.push(line);
    const ctaH = fs * 1.1;
    let y = h - pad - ctaH - fs * 0.6 - (lines.length - 1) * fs * 1.15;
    lines.forEach((l) => { ctx.fillText(l, pad, y); y += fs * 1.15; });
    ctx.font = `700 ${Math.round(fs * 0.5)}px system-ui, sans-serif`;
    const tw = ctx.measureText(cta()).width;
    ctx.beginPath(); ctx.roundRect(pad, h - pad - ctaH, tw + fs, ctaH, fs * 0.2); ctx.fill();
    ctx.fillStyle = '#0b3d26';
    ctx.fillText(cta(), pad + fs / 2, h - pad - ctaH / 2 + fs * 0.17);
    const a = document.createElement('a');
    a.href = c.toDataURL('image/png');
    a.download = `${document.querySelector('.previews').dataset.slug}-${p.dataset.ratio.replace(':', 'x')}.png`;
    a.click();
  }

  $('#cr-file').addEventListener('change', (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const img = new Image();
    img.onload = () => { image = img; refresh(); };
    img.src = URL.createObjectURL(f);
  });
  $('#cr-headline').addEventListener('input', refresh);
  $('#cr-cta').addEventListener('input', refresh);
  document.querySelectorAll('[data-export]').forEach((b) => b.addEventListener('click', () => exportSize(b.closest('.preview'))));
  $('#cr-all').addEventListener('click', async () => { for (const p of document.querySelectorAll('.preview')) await exportSize(p); });
})();
