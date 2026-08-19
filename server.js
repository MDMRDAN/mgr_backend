'use strict';

const express = require('express');
const cors = require('cors');
const multer = require('multer');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const app = express();
const PORT = Number(process.env.PORT || 3000);
const ROOT = __dirname;
const DATA = path.join(ROOT, 'data');
const UPLOADS = path.join(ROOT, 'uploads');
for (const dir of [DATA, UPLOADS]) fs.mkdirSync(dir, { recursive: true });

app.use(cors());
app.use(express.json({ limit: '2mb' }));
app.use(express.urlencoded({ extended: true, limit: '2mb' }));

const upload = multer({
  dest: UPLOADS,
  limits: { fileSize: 8 * 1024 * 1024 }
});

function file(name) { return path.join(DATA, name + '.json'); }
function read(name, fallback = []) {
  try { return JSON.parse(fs.readFileSync(file(name), 'utf8')); }
  catch { return fallback; }
}
function write(name, value) {
  fs.writeFileSync(file(name), JSON.stringify(value, null, 2));
}
function id(prefix) { return prefix + '-' + crypto.randomBytes(7).toString('hex'); }
function now() { return new Date().toISOString(); }

function tokenFor(email, role) {
  return Buffer.from(JSON.stringify({ email, role, exp: Date.now() + 8 * 60 * 60 * 1000 })).toString('base64url');
}
function auth(req) {
  const h = req.headers.authorization || '';
  if (!h.startsWith('Bearer ')) return null;
  try {
    const data = JSON.parse(Buffer.from(h.slice(7), 'base64url').toString('utf8'));
    return data.exp > Date.now() ? data : null;
  } catch { return null; }
}
function requireAuth(req, res, next) {
  const user = auth(req);
  if (!user) return res.status(401).json({ error: 'Authentication required.' });
  req.user = user; next();
}

app.get('/api/health', (req, res) => res.json({ ok: true, service: 'MGR Global Records API', time: now() }));

app.get('/api/events', (req, res) => {
  const events = read('events', []);
  const sorted = events.filter(Boolean).sort((a,b) => new Date(a.starts_at || 0) - new Date(b.starts_at || 0));
  res.json(sorted);
});
app.post('/api/events', requireAuth, (req, res) => {
  const rows = read('events', []);
  const e = { id: id('evt'), title: String(req.body.title || '').trim(), starts_at: req.body.starts_at || null, status: req.body.status || 'scheduled', description: String(req.body.description || '') };
  if (!e.title) return res.status(400).json({ error: 'title is required' });
  rows.push(e); write('events', rows); res.status(201).json(e);
});

app.get('/api/notifications', (req, res) => res.json(read('notifications', []).slice().sort((a,b) => new Date(b.created_at||0)-new Date(a.created_at||0))));
app.post('/api/notifications', requireAuth, (req, res) => {
  const rows = read('notifications', []);
  const n = { id: id('news'), title: String(req.body.title || '').trim(), body: String(req.body.body || ''), audience: req.body.audience || 'all', created_at: now() };
  if (!n.title) return res.status(400).json({ error: 'title is required' });
  rows.unshift(n); write('notifications', rows); res.status(201).json(n);
});

app.get('/api/posts', (req, res) => res.json(read('posts', []).slice(0,100)));
app.post('/api/posts', requireAuth, upload.single('media'), (req, res) => {
  const rows = read('posts', []);
  const type = req.body.type || 'text';
  const post = { id: id('post'), type, body: String(req.body.body || req.body.text || ''), author: req.user.email, created_at: now() };
  if (req.file) {
    post.media = { original_name: req.file.originalname, filename: req.file.filename, path: '/uploads/' + req.file.filename, mime: req.file.mimetype, size: req.file.size };
  }
  rows.unshift(post); write('posts', rows); res.status(201).json(post);
});

app.get('/api/sponsors', (req, res) => res.json(read('sponsors', [])));
app.get('/api/stats', (req, res) => {
  const regs = read('registrations', []), posts = read('posts', []), events = read('events', []), sponsors = read('sponsors', []);
  res.json({ members: regs.length, partners: sponsors.length, achievements: posts.filter(p => /achievement/i.test(p.body || '')).length, support: 0, events: events.length });
});

app.post('/api/registrations', upload.none(), (req, res) => {
  const rows = read('registrations', []);
  const record = { id: id('reg'), ...req.body, created_at: now() };
  rows.unshift(record); write('registrations', rows); res.status(201).json({ ok: true, registration: record });
});

app.post('/api/auth/login', (req, res) => {
  const email = String(req.body.email || '').trim().toLowerCase();
  const password = String(req.body.password || '');
  const role = req.body.role === 'developer' ? 'developer' : 'admin';
  const expectedEmail = (role === 'developer' ? process.env.DEVELOPER_EMAIL : process.env.ADMIN_EMAIL) || (role === 'developer' ? 'developer@mgr.local' : 'admin@mgr.local');
  const expectedPassword = (role === 'developer' ? process.env.DEVELOPER_PASSWORD : process.env.ADMIN_PASSWORD) || 'change-this-password';
  if (email !== expectedEmail.toLowerCase() || password !== expectedPassword) return res.status(401).json({ error: 'Invalid credentials.' });
  res.json({ token: tokenFor(email, role), role, email });
});

app.post('/api/admin/verification/request', (req, res) => {
  const email = String(req.body.email || '').trim().toLowerCase();
  const code = String(Math.floor(100000 + Math.random() * 900000));
  // Demo backend: code is returned so the installation works without an email provider.
  console.log('[MGR verification]', email, code);
  res.json({ ok: true, email, code, demo: true });
});
app.post('/api/admin/verification/confirm', (req, res) => res.json({ ok: true, verified: true, email: req.body.email || '' }));

// EI learning endpoint. It always returns a useful fallback and YouTube searches.
// Add a YouTube Data API key to receive real video IDs instead of search links.
app.post('/api/ei/ask', async (req, res) => {
  const question = String(req.body.question || '').trim();
  if (!question) return res.status(400).json({ error: 'question is required' });
  const q = encodeURIComponent(question);
  let youtube = [
    { title: 'Best match', url: `https://www.youtube.com/results?search_query=${q}`, channelTitle: 'YouTube search' },
    { title: 'Explained', url: `https://www.youtube.com/results?search_query=${encodeURIComponent(question + ' explained')}`, channelTitle: 'YouTube search' },
    { title: 'Visual lesson', url: `https://www.youtube.com/results?search_query=${encodeURIComponent(question + ' visual lesson')}`, channelTitle: 'YouTube search' }
  ];

  if (process.env.YOUTUBE_API_KEY) {
    try {
      const u = 'https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&maxResults=5&q=' + q + '&key=' + encodeURIComponent(process.env.YOUTUBE_API_KEY);
      const r = await fetch(u);
      if (r.ok) {
        const d = await r.json();
        youtube = (d.items || []).map(x => ({ videoId: x.id?.videoId, title: x.snippet?.title, channelTitle: x.snippet?.channelTitle }));
      }
    } catch {}
  }

  const visual = [
    { title: 'Question', text: question },
    { title: 'Break it down', text: 'Identify the main concepts, parts, or steps.' },
    { title: 'Connect', text: 'Show how the ideas relate to one another.' },
    { title: 'Apply', text: 'Use an example or practical situation to test understanding.' }
  ];
  res.json({
    answer: `Here is a structured learning path for: ${question}. Start with the core idea, break it into smaller parts, connect those parts, then apply the idea to an example.`,
    visual,
    youtube
  });
});

app.use('/uploads', express.static(UPLOADS));
app.use(express.static(ROOT, { index: 'index.html' }));
app.get('*', (req, res) => res.sendFile(path.join(ROOT, 'index.html')));

app.listen(PORT, () => console.log(`MGR backend running at http://localhost:${PORT}`));
