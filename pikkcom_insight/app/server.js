//const http = require('http');
//const fs = require('fs');
//const path = require('path');
//const crypto = require('crypto');
//const url = require('url');
//
//const USERS_FILE = path.join(__dirname, 'users.json');
//const PUBLIC_DIR = path.join(__dirname, 'public');
//const PORT = process.env.PORT || 3000;
//
//// --- user storage (a simple JSON file; swap for a real DB later) ---
//
//function loadUsers() {
//  if (!fs.existsSync(USERS_FILE)) return {};
//  return JSON.parse(fs.readFileSync(USERS_FILE, 'utf8'));
//}
//
//function saveUsers(users) {
//  fs.writeFileSync(USERS_FILE, JSON.stringify(users, null, 2));
//}
//
//function hashPassword(password, salt) {
//  return crypto.scryptSync(password, salt, 64).toString('hex');
//}
//
//// --- small helpers ---
//
//function sendJSON(res, status, data) {
//  res.writeHead(status, { 'Content-Type': 'application/json' });
//  res.end(JSON.stringify(data));
//}
//
//function readBody(req) {
//  return new Promise((resolve, reject) => {
//    let body = '';
//    req.on('data', (chunk) => {
//      body += chunk;
//      if (body.length > 1e6) req.destroy(); // basic guard against huge payloads
//    });
//    req.on('end', () => {
//      try {
//        resolve(body ? JSON.parse(body) : {});
//      } catch (e) {
//        reject(e);
//      }
//    });
//    req.on('error', reject);
//  });
//}
//
//function serveStatic(req, res) {
//  const parsed = url.parse(req.url);
//  let filePath = parsed.pathname === '/' ? '/index.html' : parsed.pathname;
//  filePath = path.normalize(filePath).replace(/^(\.\.[/\\])+/, ''); // no path traversal
//  const fullPath = path.join(PUBLIC_DIR, filePath);
//
//  const ext = path.extname(fullPath);
//  const types = {
//    '.html': 'text/html',
//    '.css': 'text/css',
//    '.js': 'application/javascript',
//  };
//
//  fs.readFile(fullPath, (err, data) => {
//    if (err) {
//      res.writeHead(404, { 'Content-Type': 'text/plain' });
//      res.end('Not found');
//      return;
//    }
//    res.writeHead(200, { 'Content-Type': types[ext] || 'application/octet-stream' });
//    res.end(data);
//  });
//}
//
//// --- routes ---
//
//const server = http.createServer(async (req, res) => {
//  const parsed = url.parse(req.url, true);
//
//  if (req.method === 'POST' && parsed.pathname === '/api/signup') {
//    try {
//      const { username, password } = await readBody(req);
//
//      if (!username || !password) {
//        return sendJSON(res, 400, { error: 'username and password are required' });
//      }
//      if (password.length < 6) {
//        return sendJSON(res, 400, { error: 'password must be at least 6 characters' });
//      }
//
//      const users = loadUsers();
//      if (users[username]) {
//        return sendJSON(res, 409, { error: 'that username is already taken' });
//      }
//
//      const salt = crypto.randomBytes(16).toString('hex');
//      const hash = hashPassword(password, salt);
//      users[username] = { salt, hash, createdAt: new Date().toISOString() };
//      saveUsers(users);
//
//      return sendJSON(res, 201, { message: 'account created', username });
//    } catch (e) {
//      return sendJSON(res, 400, { error: 'invalid request body' });
//    }
//  }
//
//  if (req.method === 'POST' && parsed.pathname === '/api/login') {
//    try {
//      const { username, password } = await readBody(req);
//
//      if (!username || !password) {
//        return sendJSON(res, 400, { error: 'username and password are required' });
//      }
//
//      const users = loadUsers();
//      const user = users[username];
//      if (!user) {
//        return sendJSON(res, 401, { error: 'no account found for that username' });
//      }
//
//      const hash = hashPassword(password, user.salt);
//      if (hash !== user.hash) {
//        return sendJSON(res, 401, { error: 'incorrect password' });
//      }
//
//      return sendJSON(res, 200, { message: 'signed in', username });
//    } catch (e) {
//      return sendJSON(res, 400, { error: 'invalid request body' });
//    }
//  }
//
//  if (req.method === 'GET') {
//    return serveStatic(req, res);
//  }
//
//  res.writeHead(404, { 'Content-Type': 'text/plain' });
//  res.end('Not found');
//});
//
//server.listen(PORT, () => {
//  console.log(`reflexn backend running at http://localhost:${PORT}`);
//});

const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const url = require('url');

const USERS_FILE = path.join(__dirname, 'users.json');
const PUBLIC_DIR = path.join(__dirname, 'public');
const PORT = process.env.PORT || 3000;

// --- user storage (a simple JSON file; swap for a real DB later) ---

function loadUsers() {
  if (!fs.existsSync(USERS_FILE)) return {};
  return JSON.parse(fs.readFileSync(USERS_FILE, 'utf8'));
}

function saveUsers(users) {
  fs.writeFileSync(USERS_FILE, JSON.stringify(users, null, 2));
}

function hashPassword(password, salt) {
  return crypto.scryptSync(password, salt, 64).toString('hex');
}

// --- small helpers ---

function sendJSON(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > 1e6) req.destroy(); // basic guard against huge payloads
    });
    req.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch (e) {
        reject(e);
      }
    });
    req.on('error', reject);
  });
}

function serveStatic(req, res) {
  const parsed = url.parse(req.url);
  let filePath = parsed.pathname === '/' ? '/index.html' : parsed.pathname;
  filePath = path.normalize(filePath).replace(/^(\.\.[/\\])+/, ''); // no path traversal
  const fullPath = path.join(PUBLIC_DIR, filePath);

  const ext = path.extname(fullPath);
  const types = {
    '.html': 'text/html',
    '.css': 'text/css',
    '.js': 'application/javascript',
  };

  fs.readFile(fullPath, (err, data) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain' });
      res.end('Not found');
      return;
    }
    res.writeHead(200, { 'Content-Type': types[ext] || 'application/octet-stream' });
    res.end(data);
  });
}

// --- routes ---

const server = http.createServer(async (req, res) => {
  const parsed = url.parse(req.url, true);

  if (req.method === 'POST' && parsed.pathname === '/api/signup') {
    try {
      const { username, password } = await readBody(req);

      if (!username || !password) {
        return sendJSON(res, 400, { error: 'username and password are required' });
      }
      if (password.length < 6) {
        return sendJSON(res, 400, { error: 'password must be at least 6 characters' });
      }

      const users = loadUsers();
      if (users[username]) {
        return sendJSON(res, 409, { error: 'that username is already taken' });
      }

      const salt = crypto.randomBytes(16).toString('hex');
      const hash = hashPassword(password, salt);
      users[username] = { salt, hash, createdAt: new Date().toISOString() };
      saveUsers(users);

      return sendJSON(res, 201, { message: 'account created', username });
    } catch (e) {
      return sendJSON(res, 400, { error: 'invalid request body' });
    }
  }

  if (req.method === 'POST' && parsed.pathname === '/api/login') {
    try {
      const { username, password } = await readBody(req);

      if (!username || !password) {
        return sendJSON(res, 400, { error: 'username and password are required' });
      }

      const users = loadUsers();
      const user = users[username];
      if (!user) {
        return sendJSON(res, 401, { error: 'no account found for that username' });
      }

      const hash = hashPassword(password, user.salt);
      if (hash !== user.hash) {
        return sendJSON(res, 401, { error: 'incorrect password' });
      }

      return sendJSON(res, 200, { message: 'signed in', username });
    } catch (e) {
      return sendJSON(res, 400, { error: 'invalid request body' });
    }
  }

  if (req.method === 'GET') {
    return serveStatic(req, res);
  }

  res.writeHead(404, { 'Content-Type': 'text/plain' });
  res.end('Not found');
});

server.listen(PORT, () => {
  console.log(`reflexn backend running at http://localhost:${PORT}`);
});