/**
 * Chord — Backend  server.js  v3
 * ================================
 * Install:  npm install express ws better-sqlite3 bcryptjs jsonwebtoken cors uuid
 * Run:      node server.js
 */
'use strict';

const express   = require('express');
const http      = require('http');
const WebSocket = require('ws');
const Database  = require('better-sqlite3');
const bcrypt    = require('bcryptjs');
const jwt       = require('jsonwebtoken');
const cors      = require('cors');
const { v4: uuidv4 } = require('uuid');
const path      = require('path');

const PORT       = process.env.PORT       || 3000;
const SECRET_KEY = process.env.JWT_SECRET || ('chord_dev_' + Math.random().toString(36));
const DB_PATH    = process.env.DB_PATH    || path.join(__dirname, 'chord.db');

// ─── Database ─────────────────────────────────────────────────────────────────
const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    UNIQUE NOT NULL COLLATE NOCASE,
    display_name  TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    avatar_color  TEXT    NOT NULL DEFAULT '#5865F2',
    status        TEXT    NOT NULL DEFAULT 'online',
    bio           TEXT    NOT NULL DEFAULT '',
    created_at    REAL    NOT NULL
  );

  CREATE TABLE IF NOT EXISTS servers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    owner_id    INTEGER NOT NULL REFERENCES users(id),
    icon_color  TEXT    NOT NULL DEFAULT '#5865F2',
    icon_emoji  TEXT    NOT NULL DEFAULT '',
    invite_code TEXT    UNIQUE NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    created_at  REAL    NOT NULL
  );

  CREATE TABLE IF NOT EXISTS server_members (
    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    role      TEXT    NOT NULL DEFAULT 'member',
    joined_at REAL    NOT NULL,
    PRIMARY KEY (server_id, user_id)
  );

  CREATE TABLE IF NOT EXISTS channels (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id  INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    name       TEXT    NOT NULL,
    type       TEXT    NOT NULL DEFAULT 'text',
    topic      TEXT    NOT NULL DEFAULT '',
    position   INTEGER NOT NULL DEFAULT 0,
    created_at REAL    NOT NULL
  );

  CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER REFERENCES channels(id) ON DELETE CASCADE,
    dm_id      INTEGER REFERENCES direct_messages(id) ON DELETE CASCADE,
    author_id  INTEGER NOT NULL REFERENCES users(id),
    content    TEXT    NOT NULL,
    edited     INTEGER NOT NULL DEFAULT 0,
    created_at REAL    NOT NULL
  );

  CREATE TABLE IF NOT EXISTS direct_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user1_id   INTEGER NOT NULL REFERENCES users(id),
    user2_id   INTEGER NOT NULL REFERENCES users(id),
    created_at REAL    NOT NULL,
    UNIQUE(user1_id, user2_id)
  );

  CREATE TABLE IF NOT EXISTS friendships (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_id INTEGER NOT NULL REFERENCES users(id),
    addressee_id INTEGER NOT NULL REFERENCES users(id),
    status       TEXT    NOT NULL DEFAULT 'pending',
    created_at   REAL    NOT NULL,
    UNIQUE(requester_id, addressee_id)
  );

  CREATE TABLE IF NOT EXISTS calls (
    id          TEXT    PRIMARY KEY,
    caller_id   INTEGER NOT NULL REFERENCES users(id),
    callee_id   INTEGER NOT NULL REFERENCES users(id),
    status      TEXT    NOT NULL DEFAULT 'ringing',
    started_at  REAL    NOT NULL,
    answered_at REAL,
    ended_at    REAL
  );

  CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    type       TEXT    NOT NULL,
    data       TEXT    NOT NULL DEFAULT '{}',
    read       INTEGER NOT NULL DEFAULT 0,
    created_at REAL    NOT NULL
  );
`);

// ─── Migrations (handles old chord.db missing new columns) ───────────────────
(function migrate() {
  // Helper: does a column exist in a table?
  function hasCol(table, col) {
    return !!db.pragma(`table_info(${table})`).find(c => c.name === col);
  }
  function addCol(table, col, def) {
    if (!hasCol(table, col)) {
      try { db.exec(`ALTER TABLE ${table} ADD COLUMN ${col} ${def}`); console.log(`[migrate] +${table}.${col}`); }
      catch(e) { console.warn(`[migrate] skip ${table}.${col}: ${e.message}`); }
    }
  }

  addCol('users',          'bio',         "TEXT NOT NULL DEFAULT ''");
  addCol('servers',        'icon_emoji',  "TEXT NOT NULL DEFAULT ''");
  addCol('servers',        'description', "TEXT NOT NULL DEFAULT ''");
  addCol('server_members', 'role',        "TEXT NOT NULL DEFAULT 'member'");
  addCol('channels',       'topic',       "TEXT NOT NULL DEFAULT ''");

  // invite_code needs unique values filled in for existing rows
  if (!hasCol('servers', 'invite_code')) {
    try {
      db.exec("ALTER TABLE servers ADD COLUMN invite_code TEXT");
      db.prepare('SELECT id FROM servers').all().forEach(s => {
        db.prepare('UPDATE servers SET invite_code=? WHERE id=?').run(uuidv4().slice(0,8), s.id);
      });
      console.log('[migrate] +servers.invite_code');
    } catch(e) { console.warn('[migrate] invite_code:', e.message); }
  }

  // notifications table may not exist in old databases
  db.exec(`CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    read INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
  )`);

  // edited column on messages
  addCol('messages', 'edited', "INTEGER NOT NULL DEFAULT 0");
})();

// ─── Seed ─────────────────────────────────────────────────────────────────────
(function seed() {
  if (db.prepare('SELECT COUNT(*) as c FROM users').get().c > 0) return;
  const now  = Date.now() / 1000;
  const hash = bcrypt.hashSync('password123', 10);
  const pal  = ['#5865F2','#EB459E','#57F287','#FEE75C','#ED4245','#3BA55C'];
  const ins  = db.prepare('INSERT INTO users (username,display_name,password_hash,avatar_color,status,bio,created_at) VALUES (?,?,?,?,?,?,?)');
  ins.run('alice',   'Alice',   hash, pal[0], 'online', 'Hey there, I use Chord!', now);
  ins.run('bob',     'Bob',     hash, pal[1], 'online', 'Gaming enthusiast 🎮', now);
  ins.run('charlie', 'Charlie', hash, pal[2], 'online', 'Just vibing ✌️', now);

  const [alice, bob, charlie] = ['alice','bob','charlie'].map(u => db.prepare('SELECT id FROM users WHERE username=?').get(u));
  const code = uuidv4().slice(0,8);

  db.prepare('INSERT INTO servers (name,owner_id,icon_color,icon_emoji,invite_code,description,created_at) VALUES (?,?,?,?,?,?,?)')
    .run('Chill Zone', alice.id, pal[0], '🎮', code, 'A cool place to hang out', now);
  const sid = db.prepare('SELECT last_insert_rowid() as id').get().id;
  for (const uid of [alice.id, bob.id, charlie.id])
    db.prepare('INSERT INTO server_members (server_id,user_id,role,joined_at) VALUES (?,?,?,?)').run(sid, uid, uid===alice.id?'owner':'member', now);

  for (const [name,type,topic,pos] of [
    ['general','text','General chat',0],['random','text','Anything goes',1],
    ['announcements','text','Server news',2],['General VC','voice','',3],['Gaming VC','voice','',4]
  ]) db.prepare('INSERT INTO channels (server_id,name,type,topic,position,created_at) VALUES (?,?,?,?,?,?)').run(sid,name,type,topic,pos,now);

  const gen = db.prepare('SELECT id FROM channels WHERE server_id=? AND name=?').get(sid,'general');
  for (const [uid,msg] of [
    [alice.id,'Hey everyone! Welcome to Chill Zone 🎉'],
    [bob.id,'Thanks! Looks awesome in here'],
    [charlie.id,'Glad to be here 👋'],
    [alice.id,'Feel free to explore all the channels!'],
  ]) db.prepare('INSERT INTO messages (channel_id,author_id,content,created_at) VALUES (?,?,?,?)').run(gen.id,uid,msg,now);

  db.prepare('INSERT INTO friendships (requester_id,addressee_id,status,created_at) VALUES (?,?,?,?)').run(alice.id,bob.id,'accepted',now);
  db.prepare('INSERT INTO friendships (requester_id,addressee_id,status,created_at) VALUES (?,?,?,?)').run(alice.id,charlie.id,'accepted',now);

  const [u1,u2] = [Math.min(alice.id,bob.id), Math.max(alice.id,bob.id)];
  db.prepare('INSERT INTO direct_messages (user1_id,user2_id,created_at) VALUES (?,?,?)').run(u1,u2,now);
  const dm = db.prepare('SELECT last_insert_rowid() as id').get();
  db.prepare('INSERT INTO messages (dm_id,author_id,content,created_at) VALUES (?,?,?,?)').run(dm.id,bob.id,'Hey Alice! 👋',now);
  db.prepare('INSERT INTO messages (dm_id,author_id,content,created_at) VALUES (?,?,?,?)').run(dm.id,alice.id,'Hey Bob! Great to see you here 😄',now);

  console.log(`✅  Demo seeded. Server invite code: ${code}`);
})();

// ─── Auth helpers ──────────────────────────────────────────────────────────────
const mkToken = (id, un) => jwt.sign({ sub: String(id), username: un }, SECRET_KEY, { expiresIn: '7d' });
const chkToken = t => { try { return jwt.verify(t, SECRET_KEY); } catch { return null; } };
const safe = u => { if (!u) return null; const { password_hash, ...s } = u; return s; };

function auth(req, res, next) {
  const h = req.headers.authorization;
  if (!h?.startsWith('Bearer ')) return res.status(401).json({ error: 'Not authenticated' });
  const p = chkToken(h.slice(7));
  if (!p) return res.status(401).json({ error: 'Invalid token' });
  req.user = { id: parseInt(p.sub), username: p.username };
  next();
}

// ─── WebSocket state ───────────────────────────────────────────────────────────
const channelSubs = new Map(); // channelId -> Set<{ws,userId}>
const userSockets = new Map(); // userId -> ws
const voiceRooms  = new Map(); // vcChannelId -> Map<userId,{ws,info}>
const callRooms   = new Map(); // callId -> {caller,callee}

function wsUser(uid, msg) {
  const ws = userSockets.get(uid);
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}
function broadcastCh(chId, msg, exclude=null) {
  const p = JSON.stringify(msg);
  for (const {ws} of (channelSubs.get(chId)||[])) {
    if (ws !== exclude && ws.readyState === WebSocket.OPEN) ws.send(p);
  }
}

// ─── Express ──────────────────────────────────────────────────────────────────
const app    = express();
const server = http.createServer(app);
app.use(cors({ origin:'*', methods:['GET','POST','PUT','PATCH','DELETE','OPTIONS'], allowedHeaders:'*' }));
app.use(express.json());

app.get('/health', (_, res) => res.json({ ok:true, server:'Chord', version:'3.0', time:Date.now() }));

// ─── Auth ──────────────────────────────────────────────────────────────────────
app.post('/api/register', (req, res) => {
  const { username, display_name, password } = req.body||{};
  if (!username||!password) return res.status(400).json({ error:'Missing fields' });
  const pal = ['#5865F2','#EB459E','#57F287','#FEE75C','#ED4245','#3BA55C','#9B59B6','#E67E22'];
  let h=0; for(const c of username) h=((h<<5)-h+c.charCodeAt(0))|0;
  try {
    db.prepare('INSERT INTO users (username,display_name,password_hash,avatar_color,status,bio,created_at) VALUES (?,?,?,?,?,?,?)')
      .run(username.toLowerCase(), display_name||username, bcrypt.hashSync(password,10), pal[Math.abs(h)%pal.length], 'online', '', Date.now()/1000);
    const user = db.prepare('SELECT * FROM users WHERE username=?').get(username.toLowerCase());
    res.json({ token: mkToken(user.id,user.username), user: safe(user) });
  } catch(e) {
    res.status(400).json({ error: e.message.includes('UNIQUE') ? 'Username already taken' : e.message });
  }
});

app.post('/api/login', (req, res) => {
  const { username, password } = req.body||{};
  const user = db.prepare('SELECT * FROM users WHERE username=?').get((username||'').toLowerCase());
  if (!user||!bcrypt.compareSync(password, user.password_hash))
    return res.status(401).json({ error:'Invalid credentials' });
  db.prepare('UPDATE users SET status=? WHERE id=?').run('online', user.id);
  res.json({ token: mkToken(user.id,user.username), user: safe(user) });
});

app.get('/api/me', auth, (req, res) => {
  res.json(safe(db.prepare('SELECT * FROM users WHERE id=?').get(req.user.id)));
});

app.patch('/api/me', auth, (req, res) => {
  const { display_name, bio, status } = req.body||{};
  const user = db.prepare('SELECT * FROM users WHERE id=?').get(req.user.id);
  db.prepare('UPDATE users SET display_name=?,bio=?,status=? WHERE id=?')
    .run(display_name||user.display_name, bio??user.bio, status||user.status, req.user.id);
  res.json(safe(db.prepare('SELECT * FROM users WHERE id=?').get(req.user.id)));
});

// Search users by username prefix (for adding friends)
app.get('/api/users/search', auth, (req, res) => {
  const q = (req.query.q||'').toLowerCase().trim();
  if (q.length < 2) return res.json([]);
  const users = db.prepare(`
    SELECT id,username,display_name,avatar_color,status FROM users
    WHERE username LIKE ? AND id != ? LIMIT 20
  `).all(q+'%', req.user.id);
  res.json(users);
});

app.get('/api/users/:username', auth, (req, res) => {
  const user = db.prepare('SELECT id,username,display_name,avatar_color,status,bio,created_at FROM users WHERE username=?').get(req.params.username.toLowerCase());
  if (!user) return res.status(404).json({ error:'User not found' });
  // Include friendship status
  const uid = req.user.id;
  const fr = db.prepare('SELECT * FROM friendships WHERE (requester_id=? AND addressee_id=?) OR (requester_id=? AND addressee_id=?)').get(uid,user.id,user.id,uid);
  res.json({ ...user, friendship: fr || null });
});

// ─── Friends ───────────────────────────────────────────────────────────────────
app.get('/api/friends', auth, (req, res) => {
  const uid = req.user.id;
  const rows = db.prepare(`
    SELECT f.*,
      r.id as r_id, r.username as r_un, r.display_name as r_dn, r.avatar_color as r_c, r.status as r_st,
      a.id as a_id, a.username as a_un, a.display_name as a_dn, a.avatar_color as a_c, a.status as a_st
    FROM friendships f
    JOIN users r ON f.requester_id=r.id
    JOIN users a ON f.addressee_id=a.id
    WHERE f.requester_id=? OR f.addressee_id=?
    ORDER BY f.created_at DESC
  `).all(uid,uid);
  res.json(rows.map(r => {
    const isReq = r.requester_id===uid, p=isReq?'a':'r';
    return {
      id: r.id, status: r.status, is_requester: isReq, created_at: r.created_at,
      other: { id:r[p+'_id'], username:r[p+'_un'], display_name:r[p+'_dn'], avatar_color:r[p+'_c'], status:r[p+'_st'] }
    };
  }));
});

app.post('/api/friends/request', auth, (req, res) => {
  const { username } = req.body||{};
  const other = db.prepare('SELECT * FROM users WHERE username=?').get((username||'').toLowerCase());
  if (!other) return res.status(404).json({ error:'User not found' });
  if (other.id===req.user.id) return res.status(400).json({ error:'Cannot friend yourself' });

  // Check if already friends or pending
  const existing = db.prepare('SELECT * FROM friendships WHERE (requester_id=? AND addressee_id=?) OR (requester_id=? AND addressee_id=?)').get(req.user.id,other.id,other.id,req.user.id);
  if (existing) {
    if (existing.status==='accepted') return res.status(400).json({ error:'Already friends' });
    if (existing.status==='pending') return res.status(400).json({ error:'Request already pending' });
  }

  try {
    db.prepare('INSERT INTO friendships (requester_id,addressee_id,status,created_at) VALUES (?,?,?,?)').run(req.user.id,other.id,'pending',Date.now()/1000);
  } catch(e) { return res.status(400).json({ error:'Request already exists' }); }

  const caller = db.prepare('SELECT * FROM users WHERE id=?').get(req.user.id);
  // Real-time notification
  wsUser(other.id, { type:'friend_request', from: safe(caller) });
  // Persist notification
  db.prepare('INSERT INTO notifications (user_id,type,data,created_at) VALUES (?,?,?,?)').run(other.id,'friend_request',JSON.stringify({from_id:req.user.id,from_un:caller.username,from_dn:caller.display_name,from_c:caller.avatar_color}),Date.now()/1000);
  res.json({ ok:true });
});

app.post('/api/friends/:id/accept', auth, (req, res) => {
  const f = db.prepare('SELECT * FROM friendships WHERE id=? AND addressee_id=? AND status=?').get(req.params.id,req.user.id,'pending');
  if (!f) return res.status(404).json({ error:'Request not found' });
  db.prepare('UPDATE friendships SET status=? WHERE id=?').run('accepted',req.params.id);
  const me = db.prepare('SELECT * FROM users WHERE id=?').get(req.user.id);
  wsUser(f.requester_id, { type:'friend_accepted', by: safe(me) });
  res.json({ ok:true });
});

app.post('/api/friends/:id/decline', auth, (req, res) => {
  db.prepare('DELETE FROM friendships WHERE id=? AND addressee_id=?').run(req.params.id,req.user.id);
  res.json({ ok:true });
});

app.delete('/api/friends/:id', auth, (req, res) => {
  db.prepare('DELETE FROM friendships WHERE id=? AND (requester_id=? OR addressee_id=?)').run(req.params.id,req.user.id,req.user.id);
  res.json({ ok:true });
});

// ─── Notifications ─────────────────────────────────────────────────────────────
app.get('/api/notifications', auth, (req, res) => {
  const notifs = db.prepare('SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50').all(req.user.id);
  res.json(notifs.map(n => ({ ...n, data: JSON.parse(n.data) })));
});
app.post('/api/notifications/read', auth, (req, res) => {
  db.prepare('UPDATE notifications SET read=1 WHERE user_id=?').run(req.user.id);
  res.json({ ok:true });
});

// ─── Servers ───────────────────────────────────────────────────────────────────
app.get('/api/servers', auth, (req, res) => {
  res.json(db.prepare('SELECT s.* FROM servers s JOIN server_members sm ON s.id=sm.server_id WHERE sm.user_id=? ORDER BY s.created_at').all(req.user.id));
});

app.post('/api/servers', auth, (req, res) => {
  const { name, description='', icon_emoji='' } = req.body||{};
  if (!name) return res.status(400).json({ error:'Name required' });
  const pal=['#5865F2','#EB459E','#57F287','#FEE75C','#ED4245','#3BA55C'];
  const now=Date.now()/1000, code=uuidv4().slice(0,8);
  db.prepare('INSERT INTO servers (name,owner_id,icon_color,icon_emoji,invite_code,description,created_at) VALUES (?,?,?,?,?,?,?)')
    .run(name, req.user.id, pal[Math.floor(Math.random()*pal.length)], icon_emoji, code, description, now);
  const sid = db.prepare('SELECT last_insert_rowid() as id').get().id;
  db.prepare('INSERT INTO server_members (server_id,user_id,role,joined_at) VALUES (?,?,?,?)').run(sid,req.user.id,'owner',now);
  db.prepare('INSERT INTO channels (server_id,name,type,topic,position,created_at) VALUES (?,?,?,?,?,?)').run(sid,'general','text','General chat',0,now);
  db.prepare('INSERT INTO channels (server_id,name,type,topic,position,created_at) VALUES (?,?,?,?,?,?)').run(sid,'General VC','voice','',1,now);
  res.json(db.prepare('SELECT * FROM servers WHERE id=?').get(sid));
});

// Preview a server by invite code (before joining)
app.get('/api/servers/invite/:code', auth, (req, res) => {
  const srv = db.prepare('SELECT * FROM servers WHERE invite_code=?').get(req.params.code);
  if (!srv) return res.status(404).json({ error:'Invalid invite code' });
  const memberCount = db.prepare('SELECT COUNT(*) as c FROM server_members WHERE server_id=?').get(srv.id).c;
  const owner = db.prepare('SELECT id,username,display_name,avatar_color FROM users WHERE id=?').get(srv.owner_id);
  const alreadyMember = !!db.prepare('SELECT 1 FROM server_members WHERE server_id=? AND user_id=?').get(srv.id,req.user.id);
  res.json({ ...srv, member_count: memberCount, owner, already_member: alreadyMember });
});

// Join by invite code
app.post('/api/servers/invite/:code/join', auth, (req, res) => {
  const srv = db.prepare('SELECT * FROM servers WHERE invite_code=?').get(req.params.code);
  if (!srv) return res.status(404).json({ error:'Invalid invite code' });
  try {
    db.prepare('INSERT INTO server_members (server_id,user_id,role,joined_at) VALUES (?,?,?,?)').run(srv.id,req.user.id,'member',Date.now()/1000);
  } catch { /* already member, that's fine */ }
  res.json(db.prepare('SELECT * FROM servers WHERE id=?').get(srv.id));
});

// Get server info + invite code (for sharing)
app.get('/api/servers/:id', auth, (req, res) => {
  const isMember = db.prepare('SELECT 1 FROM server_members WHERE server_id=? AND user_id=?').get(req.params.id,req.user.id);
  if (!isMember) return res.status(403).json({ error:'Not a member' });
  const srv = db.prepare('SELECT * FROM servers WHERE id=?').get(req.params.id);
  const mc  = db.prepare('SELECT COUNT(*) as c FROM server_members WHERE server_id=?').get(req.params.id).c;
  res.json({ ...srv, member_count: mc });
});

// Regenerate invite code
app.post('/api/servers/:id/invite/reset', auth, (req, res) => {
  const srv = db.prepare('SELECT * FROM servers WHERE id=? AND owner_id=?').get(req.params.id,req.user.id);
  if (!srv) return res.status(403).json({ error:'Not owner' });
  const code = uuidv4().slice(0,8);
  db.prepare('UPDATE servers SET invite_code=? WHERE id=?').run(code,req.params.id);
  res.json({ invite_code: code });
});

app.delete('/api/servers/:id', auth, (req, res) => {
  const srv = db.prepare('SELECT * FROM servers WHERE id=? AND owner_id=?').get(req.params.id,req.user.id);
  if (!srv) return res.status(403).json({ error:'Not owner' });
  db.prepare('DELETE FROM server_members WHERE server_id=?').run(req.params.id);
  db.prepare('DELETE FROM channels WHERE server_id=?').run(req.params.id);
  db.prepare('DELETE FROM servers WHERE id=?').run(req.params.id);
  res.json({ ok:true });
});

app.delete('/api/servers/:id/leave', auth, (req, res) => {
  db.prepare('DELETE FROM server_members WHERE server_id=? AND user_id=?').run(req.params.id,req.user.id);
  res.json({ ok:true });
});

app.get('/api/servers/:id/members', auth, (req, res) => {
  const members = db.prepare(`
    SELECT u.id,u.username,u.display_name,u.avatar_color,u.status,u.bio,sm.role,sm.joined_at
    FROM users u JOIN server_members sm ON u.id=sm.user_id
    WHERE sm.server_id=? ORDER BY sm.role='owner' DESC, sm.joined_at ASC
  `).all(req.params.id);
  res.json(members);
});

// ─── Channels ──────────────────────────────────────────────────────────────────
app.get('/api/servers/:id/channels', auth, (req, res) => {
  res.json(db.prepare('SELECT * FROM channels WHERE server_id=? ORDER BY position,id').all(req.params.id).map(c => ({
    ...c,
    ...(c.type==='voice' ? { voice_members: [...(voiceRooms.get(c.id)||new Map()).keys()] } : {})
  })));
});

app.post('/api/servers/:id/channels', auth, (req, res) => {
  const role = db.prepare('SELECT role FROM server_members WHERE server_id=? AND user_id=?').get(req.params.id,req.user.id)?.role;
  if (!['owner','admin'].includes(role)) return res.status(403).json({ error:'No permission' });
  const { name, type='text', topic='' } = req.body||{};
  if (!name) return res.status(400).json({ error:'Name required' });
  const pos = db.prepare('SELECT COUNT(*) as c FROM channels WHERE server_id=?').get(req.params.id).c;
  db.prepare('INSERT INTO channels (server_id,name,type,topic,position,created_at) VALUES (?,?,?,?,?,?)').run(req.params.id,name,type,topic,pos,Date.now()/1000);
  res.json(db.prepare('SELECT * FROM channels WHERE server_id=? ORDER BY id DESC LIMIT 1').get(req.params.id));
});

app.delete('/api/servers/:id/channels/:cid', auth, (req, res) => {
  const role = db.prepare('SELECT role FROM server_members WHERE server_id=? AND user_id=?').get(req.params.id,req.user.id)?.role;
  if (!['owner','admin'].includes(role)) return res.status(403).json({ error:'No permission' });
  db.prepare('DELETE FROM channels WHERE id=? AND server_id=?').run(req.params.cid,req.params.id);
  res.json({ ok:true });
});

// ─── Messages ──────────────────────────────────────────────────────────────────
app.get('/api/channels/:id/messages', auth, (req, res) => {
  const before = req.query.before ? parseFloat(req.query.before) : Date.now()/1000+1;
  const msgs = db.prepare(`
    SELECT m.*,u.display_name,u.username,u.avatar_color
    FROM messages m JOIN users u ON m.author_id=u.id
    WHERE m.channel_id=? AND m.created_at<? ORDER BY m.created_at DESC LIMIT 50
  `).all(req.params.id,before).reverse();
  res.json(msgs);
});

app.post('/api/channels/:id/messages', auth, (req, res) => {
  const { content } = req.body||{};
  if (!content?.trim()) return res.status(400).json({ error:'Empty message' });
  const now = Date.now()/1000;
  db.prepare('INSERT INTO messages (channel_id,author_id,content,created_at) VALUES (?,?,?,?)').run(req.params.id,req.user.id,content.trim(),now);
  const msg = db.prepare('SELECT m.*,u.display_name,u.username,u.avatar_color FROM messages m JOIN users u ON m.author_id=u.id WHERE m.channel_id=? ORDER BY m.id DESC LIMIT 1').get(req.params.id);
  broadcastCh(parseInt(req.params.id), { type:'new_message', message:msg });
  res.json(msg);
});

app.delete('/api/messages/:id', auth, (req, res) => {
  const msg = db.prepare('SELECT * FROM messages WHERE id=?').get(req.params.id);
  if (!msg) return res.status(404).json({ error:'Not found' });
  if (msg.author_id !== req.user.id) return res.status(403).json({ error:'Not your message' });
  db.prepare('DELETE FROM messages WHERE id=?').run(req.params.id);
  if (msg.channel_id) broadcastCh(msg.channel_id, { type:'message_deleted', message_id: parseInt(req.params.id) });
  res.json({ ok:true });
});

// ─── Direct Messages ───────────────────────────────────────────────────────────
app.get('/api/dms', auth, (req, res) => {
  const uid = req.user.id;
  const dms = db.prepare(`
    SELECT dm.*,
      u1.id as u1i, u1.username as u1u, u1.display_name as u1d, u1.avatar_color as u1c, u1.status as u1s,
      u2.id as u2i, u2.username as u2u, u2.display_name as u2d, u2.avatar_color as u2c, u2.status as u2s,
      (SELECT content FROM messages WHERE dm_id=dm.id ORDER BY created_at DESC LIMIT 1) as last_msg,
      (SELECT created_at FROM messages WHERE dm_id=dm.id ORDER BY created_at DESC LIMIT 1) as last_msg_at
    FROM direct_messages dm
    JOIN users u1 ON dm.user1_id=u1.id JOIN users u2 ON dm.user2_id=u2.id
    WHERE dm.user1_id=? OR dm.user2_id=?
    ORDER BY last_msg_at DESC NULLS LAST
  `).all(uid,uid);
  res.json(dms.map(dm => {
    const p=dm.user1_id===uid?'u2':'u1';
    return {
      id:dm.id, created_at:dm.created_at, last_msg:dm.last_msg, last_msg_at:dm.last_msg_at,
      other_user:{ id:dm[p+'i'],username:dm[p+'u'],display_name:dm[p+'d'],avatar_color:dm[p+'c'],status:dm[p+'s'] }
    };
  }));
});

app.post('/api/dms/open', auth, (req, res) => {
  const { username, user_id } = req.body||{};
  let other;
  if (user_id) other = db.prepare('SELECT * FROM users WHERE id=?').get(user_id);
  else other = db.prepare('SELECT * FROM users WHERE username=?').get((username||'').toLowerCase());
  if (!other) return res.status(404).json({ error:'User not found' });
  if (other.id===req.user.id) return res.status(400).json({ error:'Cannot DM yourself' });
  const [u1,u2] = [Math.min(req.user.id,other.id),Math.max(req.user.id,other.id)];
  try { db.prepare('INSERT INTO direct_messages (user1_id,user2_id,created_at) VALUES (?,?,?)').run(u1,u2,Date.now()/1000); } catch {}
  const dm = db.prepare('SELECT * FROM direct_messages WHERE user1_id=? AND user2_id=?').get(u1,u2);
  res.json({ dm_id: dm.id });
});

app.get('/api/dms/:id/messages', auth, (req, res) => {
  const dm = db.prepare('SELECT * FROM direct_messages WHERE id=? AND (user1_id=? OR user2_id=?)').get(req.params.id,req.user.id,req.user.id);
  if (!dm) return res.status(403).json({ error:'Not your DM' });
  const before = req.query.before ? parseFloat(req.query.before) : Date.now()/1000+1;
  const msgs = db.prepare(`
    SELECT m.*,u.display_name,u.username,u.avatar_color
    FROM messages m JOIN users u ON m.author_id=u.id
    WHERE m.dm_id=? AND m.created_at<? ORDER BY m.created_at DESC LIMIT 50
  `).all(req.params.id,before).reverse();
  res.json(msgs);
});

app.post('/api/dms/:id/messages', auth, (req, res) => {
  const { content } = req.body||{};
  if (!content?.trim()) return res.status(400).json({ error:'Empty' });
  const dm = db.prepare('SELECT * FROM direct_messages WHERE id=? AND (user1_id=? OR user2_id=?)').get(req.params.id,req.user.id,req.user.id);
  if (!dm) return res.status(403).json({ error:'Not your DM' });
  const now = Date.now()/1000;
  db.prepare('INSERT INTO messages (dm_id,author_id,content,created_at) VALUES (?,?,?,?)').run(req.params.id,req.user.id,content.trim(),now);
  const msg = db.prepare('SELECT m.*,u.display_name,u.username,u.avatar_color FROM messages m JOIN users u ON m.author_id=u.id WHERE m.dm_id=? ORDER BY m.id DESC LIMIT 1').get(req.params.id);
  const otherId = dm.user1_id===req.user.id ? dm.user2_id : dm.user1_id;
  wsUser(otherId, { type:'new_dm', dm_id:dm.id, message:msg });
  res.json(msg);
});

// ─── Calls ─────────────────────────────────────────────────────────────────────
app.post('/api/call/ring', auth, (req, res) => {
  const { username, user_id } = req.body||{};
  let callee;
  if (user_id) callee = db.prepare('SELECT * FROM users WHERE id=?').get(user_id);
  else callee = db.prepare('SELECT * FROM users WHERE username=?').get((username||'').toLowerCase());
  if (!callee) return res.status(404).json({ error:'User not found' });
  if (callee.id===req.user.id) return res.status(400).json({ error:'Cannot call yourself' });
  const busy = db.prepare(`SELECT id FROM calls WHERE (caller_id=? OR callee_id=?) AND status IN ('ringing','active')`).get(callee.id,callee.id);
  if (busy) { wsUser(req.user.id,{type:'call_busy',callee:callee.username}); return res.status(409).json({error:'User is busy'}); }
  const caller = db.prepare('SELECT * FROM users WHERE id=?').get(req.user.id);
  const callId = uuidv4();
  db.prepare('INSERT INTO calls (id,caller_id,callee_id,status,started_at) VALUES (?,?,?,?,?)').run(callId,req.user.id,callee.id,'ringing',Date.now()/1000);
  wsUser(callee.id, { type:'call_ring', callId, caller:safe(caller) });
  wsUser(req.user.id, { type:'call_ringing', callId, callee:safe(callee) });
  setTimeout(()=>{ const c=db.prepare('SELECT status FROM calls WHERE id=?').get(callId); if(c?.status==='ringing'){db.prepare('UPDATE calls SET status=?,ended_at=? WHERE id=?').run('missed',Date.now()/1000,callId);wsUser(callee.id,{type:'call_missed',callId});wsUser(req.user.id,{type:'call_missed',callId});}},45000);
  res.json({ callId, status:'ringing' });
});

app.post('/api/call/accept/:callId', auth, (req, res) => {
  const call = db.prepare('SELECT * FROM calls WHERE id=? AND callee_id=? AND status=?').get(req.params.callId,req.user.id,'ringing');
  if (!call) return res.status(404).json({ error:'Not found' });
  db.prepare('UPDATE calls SET status=?,answered_at=? WHERE id=?').run('active',Date.now()/1000,req.params.callId);
  wsUser(call.caller_id, { type:'call_accepted', callId:req.params.callId, callee:safe(db.prepare('SELECT * FROM users WHERE id=?').get(req.user.id)) });
  res.json({ callId:req.params.callId, status:'active' });
});

app.post('/api/call/reject/:callId', auth, (req, res) => {
  const call = db.prepare('SELECT * FROM calls WHERE id=? AND (caller_id=? OR callee_id=?)').get(req.params.callId,req.user.id,req.user.id);
  if (!call) return res.status(404).json({ error:'Not found' });
  const wasActive = call.status==='active';
  db.prepare('UPDATE calls SET status=?,ended_at=? WHERE id=?').run('ended',Date.now()/1000,req.params.callId);
  const otherId = call.caller_id===req.user.id ? call.callee_id : call.caller_id;
  const t = wasActive?'call_ended':call.caller_id===req.user.id?'call_cancelled':'call_rejected';
  wsUser(otherId,{type:t,callId:req.params.callId}); wsUser(req.user.id,{type:t,callId:req.params.callId});
  callRooms.delete(req.params.callId);
  res.json({ ok:true });
});

// ─── WebSocket ─────────────────────────────────────────────────────────────────
const wss = new WebSocket.Server({ server });
wss.on('connection', (ws, req) => {
  const url    = new URL(req.url, 'http://x');
  const parts  = url.pathname.split('/').filter(Boolean);
  const token  = url.searchParams.get('token');
  const p      = chkToken(token);
  if (!p) { ws.close(4001,'Unauthorized'); return; }
  const userId = parseInt(p.sub);
  const wsType = parts[1], wsIdRaw = parts[2], wsId = parseInt(wsIdRaw);

  if (wsType==='channel') {
    const e={ws,userId}; if(!channelSubs.has(wsId)) channelSubs.set(wsId,new Set()); channelSubs.get(wsId).add(e);
    ws.on('message',()=>{}); ws.on('close',()=>channelSubs.get(wsId)?.delete(e));
  }
  else if (wsType==='user') {
    if (userId!==wsId){ws.close(4001,'Forbidden');return;}
    userSockets.set(userId,ws);
    ws.on('message',()=>{}); ws.on('close',()=>{if(userSockets.get(userId)===ws)userSockets.delete(userId);});
  }
  else if (wsType==='voice') {
    const row=db.prepare('SELECT * FROM users WHERE id=?').get(userId);
    const info={id:userId,display_name:row.display_name,avatar_color:row.avatar_color,muted:false};
    if(!voiceRooms.has(wsId))voiceRooms.set(wsId,new Map());
    const room=voiceRooms.get(wsId);
    for(const[uid,peer]of room.entries()){if(peer.ws.readyState===WebSocket.OPEN){peer.ws.send(JSON.stringify({type:'voice_user_joined',userId,userInfo:info}));ws.send(JSON.stringify({type:'voice_peer_exists',userId:uid,userInfo:peer.info}));}}
    room.set(userId,{ws,info});
    ws.on('message',raw=>{try{const msg=JSON.parse(raw);if(msg.type==='voice_signal'){const peer=room.get(msg.toUserId);if(peer?.ws.readyState===WebSocket.OPEN)peer.ws.send(JSON.stringify({type:'voice_signal',fromUserId:userId,signal:msg.signal}));}}catch{}});
    ws.on('close',()=>{room.delete(userId);for(const[,peer]of room.entries())if(peer.ws.readyState===WebSocket.OPEN)peer.ws.send(JSON.stringify({type:'voice_user_left',userId}));if(room.size===0)voiceRooms.delete(wsId);});
  }
  else if (wsType==='call') {
    const call=db.prepare('SELECT * FROM calls WHERE id=? AND (caller_id=? OR callee_id=?)').get(wsIdRaw,userId,userId);
    if(!call){ws.close(4003,'Not in call');return;}
    if(!callRooms.has(wsIdRaw))callRooms.set(wsIdRaw,{caller:null,callee:null});
    const room=callRooms.get(wsIdRaw), role=call.caller_id===userId?'caller':'callee';
    room[role]={ws,userId};
    const other=role==='caller'?room.callee:room.caller;
    if(other?.ws.readyState===WebSocket.OPEN){other.ws.send(JSON.stringify({type:'call_peer_ready',peerId:userId}));ws.send(JSON.stringify({type:'call_peer_ready',peerId:other.userId}));}
    ws.on('message',raw=>{try{const msg=JSON.parse(raw),r=callRooms.get(wsIdRaw),peer=role==='caller'?r?.callee:r?.caller;if(msg.type==='call_signal'&&peer?.ws.readyState===WebSocket.OPEN)peer.ws.send(JSON.stringify({type:'call_signal',fromUserId:userId,signal:msg.signal}));}catch{}});
    ws.on('close',()=>{const r=callRooms.get(wsIdRaw);if(r)r[role]=null;const peer=role==='caller'?callRooms.get(wsIdRaw)?.callee:callRooms.get(wsIdRaw)?.caller;if(peer?.ws.readyState===WebSocket.OPEN)peer.ws.send(JSON.stringify({type:'call_ended',callId:wsIdRaw}));});
  }
  else { ws.close(4004,'Unknown type'); }
});

server.listen(PORT,'0.0.0.0',()=>{
  console.log(`\n🚀  Chord v3  http://0.0.0.0:${PORT}`);
  console.log(`📡  WebSocket ready  |  🗄️  DB: ${DB_PATH}`);
  console.log(`\n   Demo accounts: alice / bob / charlie  (password: password123)\n`);
});

module.exports = { app, server, db };