import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Card, ClientSelect, PageHeader } from '../components/ui';
import { useVisibleClients } from '../data/scope';
import { useDB } from '../data/store';

const SIZES = [
  { name: 'Instagram feed', ratio: '4:5', w: 1080, h: 1350 },
  { name: 'Instagram / FB square', ratio: '1:1', w: 1080, h: 1080 },
  { name: 'Story / Reel', ratio: '9:16', w: 1080, h: 1920 },
  { name: 'Google Business post', ratio: '4:3', w: 1200, h: 900 },
  { name: 'LinkedIn / link share', ratio: '1.91:1', w: 1200, h: 627 },
  { name: 'YouTube thumbnail', ratio: '16:9', w: 1280, h: 720 },
];

// Renders one variant to a canvas using "cover" cropping of the master image, then downloads a PNG.
async function exportVariant(size: (typeof SIZES)[number], image: string | null, headline: string, cta: string, name: string) {
  const c = document.createElement('canvas');
  c.width = size.w;
  c.height = size.h;
  const ctx = c.getContext('2d')!;
  const g = ctx.createLinearGradient(0, 0, size.w, size.h);
  g.addColorStop(0, '#0f7a45');
  g.addColorStop(1, '#0b3d26');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size.w, size.h);
  if (image) {
    const img = new Image();
    img.src = image;
    await img.decode();
    const s = Math.max(size.w / img.width, size.h / img.height);
    ctx.drawImage(img, (size.w - img.width * s) / 2, (size.h - img.height * s) / 2, img.width * s, img.height * s);
    const shade = ctx.createLinearGradient(0, size.h * 0.4, 0, size.h);
    shade.addColorStop(0, 'rgba(0,0,0,0)');
    shade.addColorStop(1, 'rgba(0,0,0,0.65)');
    ctx.fillStyle = shade;
    ctx.fillRect(0, 0, size.w, size.h);
  }
  const pad = size.w * 0.06;
  const fs = Math.round(Math.min(size.w, size.h) * 0.075);
  ctx.fillStyle = '#fff';
  ctx.font = `700 ${fs}px system-ui, sans-serif`;
  const words = headline.split(' ');
  const lines: string[] = [];
  let line = '';
  for (const w of words) {
    const t = line ? `${line} ${w}` : w;
    if (ctx.measureText(t).width > size.w - pad * 2 && line) { lines.push(line); line = w; } else line = t;
  }
  lines.push(line);
  const ctaH = fs * 1.1;
  let y = size.h - pad - ctaH - fs * 0.6 - (lines.length - 1) * fs * 1.15;
  lines.forEach((l) => { ctx.fillText(l, pad, y); y += fs * 1.15; });
  ctx.font = `700 ${Math.round(fs * 0.5)}px system-ui, sans-serif`;
  const tw = ctx.measureText(cta).width;
  ctx.fillStyle = '#fff';
  ctx.beginPath();
  ctx.roundRect(pad, size.h - pad - ctaH, tw + fs, ctaH, fs * 0.2);
  ctx.fill();
  ctx.fillStyle = '#0b3d26';
  ctx.fillText(cta, pad + fs / 2, size.h - pad - ctaH / 2 + fs * 0.17);

  const a = document.createElement('a');
  a.href = c.toDataURL('image/png');
  a.download = `${name}-${size.ratio.replace(':', 'x')}.png`;
  a.click();
}

export function CreativeStudio() {
  const db = useDB();
  const clients = useVisibleClients();
  const [params] = useSearchParams();
  const [clientId, setClientId] = useState(params.get('client') ?? clients[0].id);
  const client = db.clients.find((c) => c.id === clientId)!;
  const [image, setImage] = useState<string | null>(null);
  const [headline, setHeadline] = useState(params.get('headline') ?? 'Your headline here');
  const [cta, setCta] = useState(client.brandVoice.ctaStyle);

  const onFile = (f?: File) => {
    if (!f) return;
    const r = new FileReader();
    r.onload = () => setImage(r.result as string);
    r.readAsDataURL(f);
  };
  const slug = client.companyName.toLowerCase().replace(/[^a-z0-9]+/g, '-');

  return (
    <>
      <PageHeader title="Creative Studio" subtitle="One master creative → every platform size" actions={<ClientSelect value={clientId} onChange={(v) => { setClientId(v); setCta(db.clients.find((c) => c.id === v)!.brandVoice.ctaStyle); }} allowAll={false} clients={clients} />} />
      <div className="grid cols-3">
        <Card title="Master creative">
          <div className="form">
            <label className="field">Image
              <input className="input" type="file" accept="image/*" onChange={(e) => onFile(e.target.files?.[0])} />
            </label>
            <label className="field">Headline
              <input className="input" value={headline} maxLength={60} onChange={(e) => setHeadline(e.target.value)} />
            </label>
            <label className="field">Call to action
              <input className="input" value={cta} maxLength={24} onChange={(e) => setCta(e.target.value)} />
            </label>
            <button className="btn" onClick={async () => { for (const s of SIZES) await exportVariant(s, image, headline, cta, slug); }}>Export all sizes</button>
            <p className="muted small" style={{ margin: 0 }}>Crops are centre-weighted. For AI-generated imagery, connect an image model on the server.</p>
          </div>
        </Card>
        <Card title="Platform previews" className="span-2">
          <div className="previews">
            {SIZES.map((s) => {
              const [w, h] = [s.w, s.h];
              return (
                <div className="preview" key={s.name}>
                  <div className="frame" style={{ aspectRatio: `${w} / ${h}` }}>
                    {image && <img src={image} alt="" />}
                    <span className="headline">{headline}</span>
                    <span className="cta">{cta}</span>
                  </div>
                  <div className="row between small">
                    <span>{s.name} <span className="muted">{s.ratio}</span></span>
                    <button className="btn ghost sm" onClick={() => exportVariant(s, image, headline, cta, slug)}>PNG</button>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      </div>
    </>
  );
}
