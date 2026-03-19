/**
 * Chord — Backend Server  (server.js)
 * =====================================
 * Node.js + Express + ws + better-sqlite3 + JWT
 *
 * Features:
 *  • Full REST API for users, servers, channels, messages, DMs, friends
 *  • WebSocket channels for real-time messages and presence
 *  • WebRTC signaling for group voice channels (/ws/voice/:id)
 *  • WebRTC signaling for direct 1-on-1 calls (/ws/call/:callId)
 *  • Call REST API: ring, accept, reject/hangup
 *  • Wide-open CORS so remote Chord desktop clients can connect
 *  • /health endpoint for client connectivity checks
 *
 * Install:
 *   npm install express ws better-sqlite3 bcryptjs jsonwebtoken cors uuid
 *
 * Run:
 *   node server.js
 *   PORT=4000 JWT_SECRET=mysecret node server.js
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

// ── Config ────────────────────────────────────────────────────────────────────
const PORT       = process.env.PORT       || 3000;
const SECRET_KEY = process.env.JWT_SECRET || ('chord_dev_' + Math.random().toString(36));
const DB_PATH    = process.env.DB_PATH    || path.join(__dirname, 'chord.db');

// ── Database ──────────────────────────────────────────────────────────────────
const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    UNIQUE NOT NULL,
    display_name  TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    avatar_color  TEXT    NOT NULL DEFAULT '#5865F2',
    status        TEXT    NOT NULL DEFAULT 'online',
    created_at    REAL    NOT NULL
  );
  CREATE TABLE IF NOT EXISTS servers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    owner_id    INTEGER NOT NULL REFERENCES users(id),
    icon_color  TEXT    NOT NULL DEFAULT '#5865F2',
    invite_code TEXT    UNIQUE,
    created_at  REAL    NOT NULL
  );
  CREATE TABLE IF NOT EXISTS server_members (
    server_id INTEGER NOT NULL REFERENCES servers(id),
    user_id   INTEGER NOT NULL REFERENCES users(id),
    joined_at REAL    NOT NULL,
    PRIMARY KEY (server_id, user_id)
  );
  CREATE TABLE IF NOT EXISTS channels (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id  INTEGER NOT NULL REFERENCES servers(id),
    name       TEXT    NOT NULL,
    type       TEXT    NOT NULL DEFAULT 'text',
    position   INTEGER NOT NULL DEFAULT 0,
    created_at REAL    NOT NULL
  );
  CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER REFERENCES channels(id),
    dm_id      INTEGER REFERENCES direct_messages(id),
    author_id  INTEGER NOT NULL REFERENCES users(id),
    content    TEXT    NOT NULL,
    created_at REAL    NOT NULL
  );
  CREATE TABLE IF NOT EXISTS direct_messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user1_id  INTEGER NOT NULL REFERENCES users(id),
    user2_id  INTEGER NOT NULL REFERENCES users(id),
    created_at REAL   NOT NULL,
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
`);

// ── Seed demo data ────────────────────────────────────────────────────────────
(function seed() {
  if (db.prepare('SELECT COUNT(*) as c FROM users').get().c > 0) return;
  const now    = Date.now() / 1000;
  const palette = ['#5865F2','#EB459E','#57F287','#FEE75C','#ED4245','#3BA55C'];
  const hash   = bcrypt.hashSync('password123', 10);
  const ins    = db.prepare('INSERT INTO users (username,display_name,password_hash,avatar_color,status,created_at) VALUES (?,?,?,?,?,?)');
  const demo   = [{un:'alice',dn:'Alice',c:palette[0]},{un:'bob',dn:'Bob',c:palette[1]},{un:'charlie',dn:'Charlie',c:palette[2]}];
  for (const u of demo) ins.run(u.un, u.dn, hash, u.c, 'online', now);

  const alice   = db.prepare('SELECT id FROM users WHERE username=?').get('alice');
  const bob     = db.prepare('SELECT id FROM users WHERE username=?').get('bob');
  const charlie = db.prepare('SELECT id FROM users WHERE username=?').get('charlie');
  const code    = uuidv4().slice(0,8);

  db.prepare('INSERT INTO servers (name,owner_id,icon_color,invite_code,created_at) VALUES (?,?,?,?,?)').run('Chill Zone', alice.id, palette[0], code, now);
  const sid = db.prepare('SELECT last_insert_rowid() as id').get().id;
  for (const uid of [alice.id,bob.id,charlie.id])
    db.prepare('INSERT INTO server_members (server_id,user_id,joined_at) VALUES (?,?,?)').run(sid, uid, now);
  for (const [name,type,pos] of [['general','text',0],['random','text',1],['announcements','text',2],['General VC','voice',3],['Gaming VC','voice',4]])
    db.prepare('INSERT INTO channels (server_id,name,type,position,created_at) VALUES (?,?,?,?,?)').run(sid, name, type, pos, now);

  const gen = db.prepare('SELECT id FROM channels WHERE server_id=? AND name=?').get(sid,'general');
  const msgs = [[alice.id,'Hey everyone! Welcome 🎉'],[bob.id,'Thanks! Looks great'],[charlie.id,'Glad to be here 👋'],[alice.id,'Feel free to explore'],[bob.id,'Anyone up for a call? 📞'],[charlie.id,"I'm in! 🎮"]];
  for (const [uid,content] of msgs)
    db.prepare('INSERT INTO messages (channel_id,author_id,content,created_at) VALUES (?,?,?,?)').run(gen.id, uid, content, now);

  db.prepare('INSERT INTO friendships (requester_id,addressee_id,status,created_at) VALUES (?,?,?,?)').run(alice.id, bob.id, 'accepted', now);
  db.prepare('INSERT INTO friendships (requester_id,addressee_id,status,created_at) VALUES (?,?,?,?)').run(alice.id, charlie.id, 'accepted', now);

  const [u1,u2] = [Math.min(alice.id,bob.id), Math.max(alice.id,bob.id)];
  db.prepare('INSERT INTO direct_messages (user1_id,user2_id,created_at) VALUES (?,?,?)').run(u1, u2, now);
  const dm = db.prepare('SELECT last_insert_rowid() as id').get();
  db.prepare('INSERT INTO messages (dm_id,author_id,content,created_at) VALUES (?,?,?,?)').run(dm.id, bob.id, 'Hey Alice! 👋', now);
  db.prepare('INSERT INTO messages (dm_id,author_id,content,created_at) VALUES (?,?,?,?)').run(dm.id, alice.id, 'Hey Bob! 🔒', now);

  console.log(`✅  Demo seeded. Invite code: ${code}`);
})();

// ── Helpers ───────────────────────────────────────────────────────────────────
const createToken = (id, un) => jwt.sign({ sub: String(id), username: un }, SECRET_KEY, { expiresIn: '7d' });
const verifyToken = tok => { try { return jwt.verify(tok, SECRET_KEY); } catch { return null; } };
const safeUser    = u => { if (!u) return null; const { password_hash, ...s } = u; return s; };

function authMiddleware(req, res, next) {
  const h = req.headers.authorization;
  if (!h?.startsWith('Bearer ')) return res.status(401).json({ error: 'Not authenticated' });
  const p = verifyToken(h.slice(7));
  if (!p) return res.status(401).json({ error: 'Invalid token' });
  req.user = { id: parseInt(p.sub), username: p.username };
  next();
}

// ── WebSocket state ───────────────────────────────────────────────────────────
const channelSubs = new Map(); // channelId -> Set<{ws,userId}>
const userSockets = new Map(); // userId -> ws
const voiceRooms  = new Map(); // vcChannelId -> Map<userId,{ws,info}>
const callRooms   = new Map(); // callId -> {caller:{ws,userId}, callee:{ws,userId}}

function wsUser(userId, msg) {
  const ws = userSockets.get(userId);
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

function broadcastCh(chId, msg, exclude=null) {
  const payload = JSON.stringify(msg);
  for (const {ws} of (channelSubs.get(chId) || [])) {
    if (ws !== exclude && ws.readyState === WebSocket.OPEN) ws.send(payload);
  }
}

// ── Express setup ─────────────────────────────────────────────────────────────
const app    = express();
const server = http.createServer(app);

app.use(cors({ origin: '*', methods: ['GET','POST','PUT','DELETE','OPTIONS'], allowedHeaders: '*' }));
app.use(express.json());

app.get('/health', (_, res) => res.json({ ok:true, server:'Chord', version:'2.0', time:Date.now() }));

// ── Auth ──────────────────────────────────────────────────────────────────────
app.post('/api/register', (req, res) => {
  const { username, display_name, password } = req.body||{};
  if (!username||!password) return res.status(400).json({ error:'Missing fields' });
  const pal = ['#5865F2','#EB459E','#57F287','#FEE75C','#ED4245','#3BA55C','#9B59B6'];
  let h=0; for(const c of username) h=((h<<5)-h+c.charCodeAt(0))|0;
  try {
    db.prepare('INSERT INTO users (username,display_name,password_hash,avatar_color,status,created_at) VALUES (?,?,?,?,?,?)')
      .run(username.toLowerCase(), display_name||username, bcrypt.hashSync(password,10), pal[Math.abs(h)%pal.length], 'online', Date.now()/1000);
    const user = db.prepare('SELECT * FROM users WHERE username=?').get(username.toLowerCase());
    res.json({ token: createToken(user.id,user.username), user: safeUser(user) });
  } catch(e) {
    if (e.message.includes('UNIQUE')) return res.status(400).json({ error:'Username taken' });
    throw e;
  }
});

app.post('/api/login', (req, res) => {
  const { username, password } = req.body||{};
  const user = db.prepare('SELECT * FROM users WHERE username=?').get((username||'').toLowerCase());
  if (!user||!bcrypt.compareSync(password, user.password_hash))
    return res.status(401).json({ error:'Invalid credentials' });
  res.json({ token: createToken(user.id,user.username), user: safeUser(user) });
});

app.get('/api/me', authMiddleware, (req, res) => {
  res.json(safeUser(db.prepare('SELECT * FROM users WHERE id=?').get(req.user.id)));
});

// ── Servers ───────────────────────────────────────────────────────────────────
app.get('/api/servers', authMiddleware, (req, res) => {
  res.json(db.prepare('SELECT s.* FROM servers s JOIN server_members sm ON s.id=sm.server_id WHERE sm.user_id=? ORDER BY s.created_at').all(req.user.id));
});

app.post('/api/servers', authMiddleware, (req, res) => {
  const { name } = req.body||{};
  if (!name) return res.status(400).json({ error:'Name required' });
  const pal = ['#5865F2','#EB459E','#57F287','#FEE75C','#ED4245','#3BA55C'];
  const now = Date.now()/1000;
  const code = uuidv4().slice(0,8);
  db.prepare('INSERT INTO servers (name,owner_id,icon_color,invite_code,created_at) VALUES (?,?,?,?,?)').run(name, req.user.id, pal[Math.floor(Math.random()*pal.length)], code, now);
  const sid = db.prepare('SELECT last_insert_rowid() as id').get().id;
  db.prepare('INSERT INTO server_members (server_id,user_id,joined_at) VALUES (?,?,?)').run(sid, req.user.id, now);
  db.prepare('INSERT INTO channels (server_id,name,type,position,created_at) VALUES (?,?,?,?,?)').run(sid,'general','text',0,now);
  db.prepare('INSERT INTO channels (server_id,name,type,position,created_at) VALUES (?,?,?,?,?)').run(sid,'General VC','voice',1,now);
  res.json(db.prepare('SELECT * FROM servers WHERE id=?').get(sid));
});

app.post('/api/servers/join/:code', authMiddleware, (req, res) => {
  const srv = db.prepare('SELECT * FROM servers WHERE invite_code=?').get(req.params.code);
  if (!srv) return res.status(404).json({ error:'Invalid code' });
  try { db.prepare('INSERT INTO server_members (server_id,user_id,joined_at) VALUES (?,?,?)').run(srv.id, req.user.id, Date.now()/1000); } catch {}
  res.json(srv);
});

app.get('/api/servers/:id/members', authMiddleware, (req, res) => {
  res.json(db.prepare('SELECT u.id,u.username,u.display_name,u.avatar_color,u.status FROM users u JOIN server_members sm ON u.id=sm.user_id WHERE sm.server_id=?').all(req.params.id));
});

// ── Channels ──────────────────────────────────────────────────────────────────
app.get('/api/servers/:id/channels', authMiddleware, (req, res) => {
  res.json(db.prepare('SELECT * FROM channels WHERE server_id=? ORDER BY position,id').all(req.params.id).map(c => {
    if (c.type==='voice') c.voice_members = [...(voiceRooms.get(c.id)||new Map()).keys()];
    return c;
  }));
});

app.post('/api/servers/:id/channels', authMiddleware, (req, res) => {
  if (!db.prepare('SELECT id FROM servers WHERE id=? AND owner_id=?').get(req.params.id, req.user.id))
    return res.status(403).json({ error:'Not owner' });
  const { name, type='text' } = req.body||{};
  const pos = db.prepare('SELECT COUNT(*) as c FROM channels WHERE server_id=?').get(req.params.id).c;
  db.prepare('INSERT INTO channels (server_id,name,type,position,created_at) VALUES (?,?,?,?,?)').run(req.params.id, name, type, pos, Date.now()/1000);
  res.json(db.prepare('SELECT * FROM channels WHERE server_id=? ORDER BY id DESC LIMIT 1').get(req.params.id));
});

// ── Messages ──────────────────────────────────────────────────────────────────
app.get('/api/channels/:id/messages', authMiddleware, (req, res) => {
  res.json(db.prepare('SELECT m.*,u.display_name,u.username,u.avatar_color FROM messages m JOIN users u ON m.author_id=u.id WHERE m.channel_id=? ORDER BY m.created_at DESC LIMIT 50').all(req.params.id).reverse());
});

app.post('/api/channels/:id/messages', authMiddleware, (req, res) => {
  const { content } = req.body||{};
  if (!content) return res.status(400).json({ error:'Empty message' });
  db.prepare('INSERT INTO messages (channel_id,author_id,content,created_at) VALUES (?,?,?,?)').run(req.params.id, req.user.id, content, Date.now()/1000);
  const msg = db.prepare('SELECT m.*,u.display_name,u.username,u.avatar_color FROM messages m JOIN users u ON m.author_id=u.id WHERE m.channel_id=? ORDER BY m.id DESC LIMIT 1').get(req.params.id);
  broadcastCh(parseInt(req.params.id), { type:'new_message', message:msg });
  res.json(msg);
});

// ── DMs ───────────────────────────────────────────────────────────────────────
app.get('/api/dms', authMiddleware, (req, res) => {
  const uid = req.user.id;
  res.json(db.prepare(`
    SELECT dm.*,
      u1.id as u1_id,u1.username as u1_un,u1.display_name as u1_dn,u1.avatar_color as u1_c,
      u2.id as u2_id,u2.username as u2_un,u2.display_name as u2_dn,u2.avatar_color as u2_c
    FROM direct_messages dm JOIN users u1 ON dm.user1_id=u1.id JOIN users u2 ON dm.user2_id=u2.id
    WHERE dm.user1_id=? OR dm.user2_id=? ORDER BY dm.created_at DESC
  `).all(uid,uid).map(dm => {
    const p = dm.user1_id===uid?'u2':'u1';
    return { id:dm.id, created_at:dm.created_at, other_user:{ id:dm[p+'_id'], username:dm[p+'_un'], display_name:dm[p+'_dn'], avatar_color:dm[p+'_c'] } };
  }));
});

app.post('/api/dms/open', authMiddleware, (req, res) => {
  const other = db.prepare('SELECT * FROM users WHERE username=?').get((req.body?.username||'').toLowerCase());
  if (!other) return res.status(404).json({ error:'User not found' });
  const [u1,u2] = [Math.min(req.user.id,other.id), Math.max(req.user.id,other.id)];
  try { db.prepare('INSERT INTO direct_messages (user1_id,user2_id,created_at) VALUES (?,?,?)').run(u1,u2,Date.now()/1000); } catch {}
  res.json({ dm_id: db.prepare('SELECT id FROM direct_messages WHERE user1_id=? AND user2_id=?').get(u1,u2).id });
});

app.get('/api/dms/:id/messages', authMiddleware, (req, res) => {
  res.json(db.prepare('SELECT m.*,u.display_name,u.username,u.avatar_color FROM messages m JOIN users u ON m.author_id=u.id WHERE m.dm_id=? ORDER BY m.created_at DESC LIMIT 50').all(req.params.id).reverse());
});

app.post('/api/dms/:id/messages', authMiddleware, (req, res) => {
  const { content } = req.body||{};
  if (!content) return res.status(400).json({ error:'Empty' });
  const dm = db.prepare('SELECT * FROM direct_messages WHERE id=?').get(req.params.id);
  if (!dm) return res.status(404).json({ error:'Not found' });
  db.prepare('INSERT INTO messages (dm_id,author_id,content,created_at) VALUES (?,?,?,?)').run(req.params.id, req.user.id, content, Date.now()/1000);
  const msg = db.prepare('SELECT m.*,u.display_name,u.username,u.avatar_color FROM messages m JOIN users u ON m.author_id=u.id WHERE m.dm_id=? ORDER BY m.id DESC LIMIT 1').get(req.params.id);
  const otherId = dm.user1_id===req.user.id ? dm.user2_id : dm.user1_id;
  wsUser(otherId, { type:'new_dm', dm_id:dm.id, message:msg });
  res.json(msg);
});

// ── Friends ───────────────────────────────────────────────────────────────────
app.get('/api/friends', authMiddleware, (req, res) => {
  const uid = req.user.id;
  res.json(db.prepare(`
    SELECT f.*,u1.id as r_id,u1.username as r_un,u1.display_name as r_dn,u1.avatar_color as r_c,
           u2.id as a_id,u2.username as a_un,u2.display_name as a_dn,u2.avatar_color as a_c
    FROM friendships f JOIN users u1 ON f.requester_id=u1.id JOIN users u2 ON f.addressee_id=u2.id
    WHERE f.requester_id=? OR f.addressee_id=?
  `).all(uid,uid).map(r => {
    const isReq = r.requester_id===uid, p = isReq?'a':'r';
    return { id:r.id, status:r.status, is_requester:isReq, other:{ id:r[p+'_id'], username:r[p+'_un'], display_name:r[p+'_dn'], avatar_color:r[p+'_c'] } };
  }));
});

app.post('/api/friends/request', authMiddleware, (req, res) => {
  const other = db.prepare('SELECT * FROM users WHERE username=?').get((req.body?.username||'').toLowerCase());
  if (!other) return res.status(404).json({ error:'User not found' });
  if (other.id===req.user.id) return res.status(400).json({ error:'Cannot friend yourself' });
  try { db.prepare('INSERT INTO friendships (requester_id,addressee_id,status,created_at) VALUES (?,?,?,?)').run(req.user.id,other.id,'pending',Date.now()/1000); }
  catch { return res.status(400).json({ error:'Already exists' }); }
  wsUser(other.id, { type:'friend_request', from:req.user.username });
  res.json({ ok:true });
});

app.post('/api/friends/:id/accept', authMiddleware, (req, res) => {
  db.prepare('UPDATE friendships SET status=? WHERE id=? AND addressee_id=?').run('accepted',req.params.id,req.user.id);
  res.json({ ok:true });
});

app.delete('/api/friends/:id', authMiddleware, (req, res) => {
  db.prepare('DELETE FROM friendships WHERE id=? AND (requester_id=? OR addressee_id=?)').run(req.params.id,req.user.id,req.user.id);
  res.json({ ok:true });
});

// ── Call API ──────────────────────────────────────────────────────────────────
// POST /api/call/ring   body: { username }
app.post('/api/call/ring', authMiddleware, (req, res) => {
  const callee = db.prepare('SELECT * FROM users WHERE username=?').get((req.body?.username||'').toLowerCase());
  if (!callee) return res.status(404).json({ error:'User not found' });
  if (callee.id===req.user.id) return res.status(400).json({ error:'Cannot call yourself' });

  // Busy check
  const busy = db.prepare(`SELECT id FROM calls WHERE (caller_id=? OR callee_id=?) AND status IN ('ringing','active')`).get(callee.id,callee.id);
  if (busy) {
    wsUser(req.user.id, { type:'call_busy', callee:callee.username });
    return res.status(409).json({ error:'User is busy' });
  }

  const caller = db.prepare('SELECT * FROM users WHERE id=?').get(req.user.id);
  const callId = uuidv4();
  db.prepare('INSERT INTO calls (id,caller_id,callee_id,status,started_at) VALUES (?,?,?,?,?)').run(callId,req.user.id,callee.id,'ringing',Date.now()/1000);

  wsUser(callee.id, {
    type:'call_ring', callId,
    caller: { id:caller.id, username:caller.username, display_name:caller.display_name, avatar_color:caller.avatar_color }
  });
  wsUser(req.user.id, {
    type:'call_ringing', callId,
    callee: { id:callee.id, username:callee.username, display_name:callee.display_name, avatar_color:callee.avatar_color }
  });

  // Auto-expire after 45 seconds if not answered
  setTimeout(() => {
    const c = db.prepare('SELECT status FROM calls WHERE id=?').get(callId);
    if (c && c.status==='ringing') {
      db.prepare('UPDATE calls SET status=?,ended_at=? WHERE id=?').run('missed',Date.now()/1000,callId);
      wsUser(callee.id,    { type:'call_missed', callId });
      wsUser(req.user.id,  { type:'call_missed', callId });
    }
  }, 45000);

  res.json({ callId, status:'ringing' });
});

// POST /api/call/accept/:callId
app.post('/api/call/accept/:callId', authMiddleware, (req, res) => {
  const call = db.prepare('SELECT * FROM calls WHERE id=? AND callee_id=? AND status=?').get(req.params.callId, req.user.id, 'ringing');
  if (!call) return res.status(404).json({ error:'Call not found or expired' });
  db.prepare('UPDATE calls SET status=?,answered_at=? WHERE id=?').run('active',Date.now()/1000,req.params.callId);
  const callee = safeUser(db.prepare('SELECT * FROM users WHERE id=?').get(req.user.id));
  wsUser(call.caller_id, { type:'call_accepted', callId:req.params.callId, callee });
  res.json({ callId:req.params.callId, status:'active' });
});

// POST /api/call/reject/:callId  (also used for hang-up mid-call)
app.post('/api/call/reject/:callId', authMiddleware, (req, res) => {
  const call = db.prepare('SELECT * FROM calls WHERE id=? AND (caller_id=? OR callee_id=?)').get(req.params.callId, req.user.id, req.user.id);
  if (!call) return res.status(404).json({ error:'Not found' });
  const wasActive = call.status==='active';
  db.prepare('UPDATE calls SET status=?,ended_at=? WHERE id=?').run('ended',Date.now()/1000,req.params.callId);
  const otherId = call.caller_id===req.user.id ? call.callee_id : call.caller_id;
  const msgType = wasActive ? 'call_ended' : (call.caller_id===req.user.id ? 'call_cancelled' : 'call_rejected');
  wsUser(otherId,      { type:msgType, callId:req.params.callId });
  wsUser(req.user.id,  { type:msgType, callId:req.params.callId });
  callRooms.delete(req.params.callId);
  res.json({ ok:true });
});

// ── WebSocket server ──────────────────────────────────────────────────────────
const wss = new WebSocket.Server({ server });

wss.on('connection', (ws, req) => {
  const url     = new URL(req.url, 'http://localhost');
  const parts   = url.pathname.split('/').filter(Boolean); // ['ws','type','id']
  const token   = url.searchParams.get('token');
  const payload = verifyToken(token);
  if (!payload) { ws.close(4001,'Unauthorized'); return; }

  const userId  = parseInt(payload.sub);
  const wsType  = parts[1];
  const wsIdRaw = parts[2]; // may be uuid (call) or int (channel/user/voice)
  const wsId    = parseInt(wsIdRaw);

  // ── Text channel sub ──────────────────────────────────────────────────────
  if (wsType==='channel') {
    const entry = { ws, userId };
    if (!channelSubs.has(wsId)) channelSubs.set(wsId, new Set());
    channelSubs.get(wsId).add(entry);
    ws.on('message', ()=>{});
    ws.on('close', ()=>channelSubs.get(wsId)?.delete(entry));
  }

  // ── User presence (DM notifs, call events) ────────────────────────────────
  else if (wsType==='user') {
    if (userId!==wsId) { ws.close(4001,'Forbidden'); return; }
    userSockets.set(userId, ws);
    ws.on('message', ()=>{});
    ws.on('close', ()=>{ if (userSockets.get(userId)===ws) userSockets.delete(userId); });
  }

  // ── Group voice channel (WebRTC signaling) ────────────────────────────────
  else if (wsType==='voice') {
    const userRow  = db.prepare('SELECT * FROM users WHERE id=?').get(userId);
    const userInfo = { id:userId, display_name:userRow.display_name, avatar_color:userRow.avatar_color, muted:false };
    if (!voiceRooms.has(wsId)) voiceRooms.set(wsId, new Map());
    const room = voiceRooms.get(wsId);
    for (const [uid,peer] of room.entries()) {
      if (peer.ws.readyState===WebSocket.OPEN) {
        peer.ws.send(JSON.stringify({ type:'voice_user_joined', userId, userInfo }));
        ws.send(JSON.stringify({ type:'voice_peer_exists', userId:uid, userInfo:peer.info }));
      }
    }
    room.set(userId, { ws, info:userInfo });
    ws.on('message', raw=>{
      try {
        const msg = JSON.parse(raw);
        if (msg.type==='voice_signal') {
          const peer = room.get(msg.toUserId);
          if (peer?.ws.readyState===WebSocket.OPEN)
            peer.ws.send(JSON.stringify({ type:'voice_signal', fromUserId:userId, signal:msg.signal }));
        }
      } catch {}
    });
    ws.on('close', ()=>{
      room.delete(userId);
      for (const [,peer] of room.entries())
        if (peer.ws.readyState===WebSocket.OPEN)
          peer.ws.send(JSON.stringify({ type:'voice_user_left', userId }));
      if (room.size===0) voiceRooms.delete(wsId);
    });
  }

  // ── Direct call WebRTC relay (/ws/call/<uuid>) ────────────────────────────
  else if (wsType==='call') {
    const callId = wsIdRaw; // uuid string
    const call   = db.prepare('SELECT * FROM calls WHERE id=? AND (caller_id=? OR callee_id=?)').get(callId, userId, userId);
    if (!call) { ws.close(4003,'Not in this call'); return; }

    if (!callRooms.has(callId)) callRooms.set(callId, { caller:null, callee:null });
    const room = callRooms.get(callId);
    const role = call.caller_id===userId ? 'caller' : 'callee';
    room[role] = { ws, userId };

    const other = role==='caller' ? room.callee : room.caller;
    if (other?.ws.readyState===WebSocket.OPEN) {
      other.ws.send(JSON.stringify({ type:'call_peer_ready', peerId:userId }));
      ws.send(JSON.stringify({ type:'call_peer_ready', peerId:other.userId }));
    }

    ws.on('message', raw=>{
      try {
        const msg  = JSON.parse(raw);
        const r    = callRooms.get(callId);
        const peer = role==='caller' ? r?.callee : r?.caller;
        if (msg.type==='call_signal' && peer?.ws.readyState===WebSocket.OPEN)
          peer.ws.send(JSON.stringify({ type:'call_signal', fromUserId:userId, signal:msg.signal }));
      } catch {}
    });
    ws.on('close', ()=>{
      const r = callRooms.get(callId);
      if (r) r[role] = null;
      const peer = role==='caller' ? callRooms.get(callId)?.callee : callRooms.get(callId)?.caller;
      if (peer?.ws.readyState===WebSocket.OPEN)
        peer.ws.send(JSON.stringify({ type:'call_ended', callId }));
    });
  }

  else { ws.close(4004,'Unknown type'); }
});

// ── Start ─────────────────────────────────────────────────────────────────────
server.listen(PORT, '0.0.0.0', ()=>{
  console.log(`\n🚀  Chord backend   http://0.0.0.0:${PORT}`);
  console.log(`📡  WebSocket ready`);
  console.log(`🗄️   DB: ${DB_PATH}`);
  console.log(`\n   Demo: alice / bob / charlie  (pw: password123)\n`);
});

module.exports = { app, server, db };
