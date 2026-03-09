// path: scripts/deploy.mjs
import 'dotenv/config';
import SftpClient from 'ssh2-sftp-client';
import fs from 'fs';
import path from 'path';

const ROOT = process.cwd();
const BUILD_DIR = path.join(ROOT, process.env.LOCAL_BUILD_DIR || 'build');

const cfg = {
  host: process.env.SFTP_HOST,
  port: parseInt(process.env.SFTP_PORT || '22', 10),
  username: process.env.SFTP_USER,
  password: process.env.SFTP_PASS || undefined,
  privateKey: process.env.SSH_KEY_PATH ? fs.readFileSync(process.env.SSH_KEY_PATH) : undefined,
  passphrase: process.env.SSH_KEY_PASSPHRASE || undefined,
  remotePath: normalize(process.env.REMOTE_PATH || '/public_html/jaspen')
};

function normalize(p) { return p.startsWith('/') ? p : `/${p}`; }

function assertEnv() {
  const missing = [];
  if (!cfg.host) missing.push('SFTP_HOST');
  if (!cfg.username) missing.push('SFTP_USER');
  if (!cfg.password && !process.env.SSH_KEY_PATH) missing.push('SFTP_PASS or SSH_KEY_PATH');
  if (!process.env.REMOTE_PATH) missing.push('REMOTE_PATH');
  if (!fs.existsSync(BUILD_DIR)) throw new Error(`Build folder not found: ${BUILD_DIR}`);
  if (missing.length) throw new Error(`Missing env: ${missing.join(', ')}`);
}

async function ensureDir(sftp, dir) {
  try { await sftp.mkdir(dir, true); } catch { /* exists */ }
}

async function uploadDir(sftp, local, remote) {
  const entries = fs.readdirSync(local, { withFileTypes: true });
  for (const e of entries) {
    const l = path.join(local, e.name);
    const r = path.posix.join(remote, e.name);
    if (e.isDirectory()) { await ensureDir(sftp, r); await uploadDir(sftp, l, r); }
    else if (e.isFile()) { await sftp.fastPut(l, r); }
  }
}

function resolveLocalHtaccess() {
  const cands = [
    path.join(BUILD_DIR, '.htaccess'),
    path.join(ROOT, 'public', '.htaccess'),
    path.join(ROOT, '.htaccess')
  ];
  for (const p of cands) if (fs.existsSync(p) && fs.statSync(p).isFile()) return p;
  return null;
}

(async () => {
  try {
    assertEnv();
    const sftp = new SftpClient();
    await sftp.connect({
      host: cfg.host, port: cfg.port, username: cfg.username,
      password: cfg.password, privateKey: cfg.privateKey, passphrase: cfg.passphrase
    });

    await ensureDir(sftp, cfg.remotePath);
    console.log(`[deploy] Uploading ${BUILD_DIR} -> ${cfg.remotePath}`);
    await uploadDir(sftp, BUILD_DIR, cfg.remotePath);

    const ht = resolveLocalHtaccess();
    if (ht) {
      const remoteHt = path.posix.join(cfg.remotePath, '.htaccess');
      console.log(`[deploy] Ensuring .htaccess -> ${remoteHt}`);
      await sftp.fastPut(ht, remoteHt);
    } else {
      console.log('[deploy] No local .htaccess found to upload.');
    }

    console.log('[deploy] Done ✅');
    await sftp.end();
  } catch (e) {
    console.error('[deploy] Failed ❌', e.message);
    process.exit(1);
  }
})();
