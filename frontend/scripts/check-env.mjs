// FILE: sekki-platform/frontend/scripts/check-env.mjs
// WHY: Validate .env without leaking secrets; optional `--connect` to test SFTP login.

import 'dotenv/config';
import fs from 'fs';
import path from 'path';
import SftpClient from 'ssh2-sftp-client';

const ROOT = process.cwd();
const BUILD_DIR = path.join(ROOT, process.env.LOCAL_BUILD_DIR || 'build');

const required = [
  'SFTP_HOST',
  'SFTP_PORT',
  'SFTP_USER',
  // exactly one of the following must be provided:
  // 'SFTP_PASS' OR 'SSH_KEY_PATH'
  'REMOTE_PATH'
];

function mask(v) {
  if (!v) return '';
  if (v.length <= 4) return '*'.repeat(v.length);
  return `${v.slice(0, 2)}${'*'.repeat(Math.max(1, v.length - 4))}${v.slice(-2)}`;
}

function hasAuth() {
  return !!process.env.SFTP_PASS || !!process.env.SSH_KEY_PATH;
}

function summarizeEnv() {
  const summary = {
    SFTP_HOST: process.env.SFTP_HOST || '',
    SFTP_PORT: process.env.SFTP_PORT || '',
    SFTP_USER: process.env.SFTP_USER || '',
    SFTP_PASS: process.env.SFTP_PASS ? mask(process.env.SFTP_PASS) : '',
    SSH_KEY_PATH: process.env.SSH_KEY_PATH || '',
    SSH_KEY_PASSPHRASE: process.env.SSH_KEY_PASSPHRASE ? mask(process.env.SSH_KEY_PASSPHRASE) : '',
    REMOTE_PATH: process.env.REMOTE_PATH || '',
    LOCAL_BUILD_DIR: process.env.LOCAL_BUILD_DIR || 'build',
    DEPLOY_CLEAN: process.env.DEPLOY_CLEAN || 'false'
  };
  console.log('[env] Loaded (masked):\n', JSON.stringify(summary, null, 2));
}

function assertEnv() {
  const missing = required.filter(k => !process.env[k]);
  if (!hasAuth()) missing.push('SFTP_PASS or SSH_KEY_PATH');
  if (missing.length) {
    console.error('[env] Missing required:', missing.join(', '));
    process.exit(1);
  }
}

async function testConnect() {
  const sftp = new SftpClient();
  const cfg = {
    host: process.env.SFTP_HOST,
    port: parseInt(process.env.SFTP_PORT || '22', 10),
    username: process.env.SFTP_USER,
    password: process.env.SFTP_PASS || undefined,
    privateKey: process.env.SSH_KEY_PATH ? fs.readFileSync(process.env.SSH_KEY_PATH) : undefined,
    passphrase: process.env.SSH_KEY_PASSPHRASE || undefined
  };
  await sftp.connect(cfg);
  const remote = process.env.REMOTE_PATH;
  const exists = await sftp.exists(remote);
  if (!exists) {
    console.warn(`[env] Remote path does not exist yet: ${remote} (will be created by deploy)`);
  } else {
    const list = await sftp.list(remote);
    console.log(`[env] Connected. Remote path ok: ${remote}. Items: ${list.length}`);
  }
  await sftp.end();
}

(function main() {
  summarizeEnv();
  assertEnv();

  const wantsConnect = process.argv.includes('--connect');
  if (wantsConnect) {
    testConnect()
      .then(() => {
        console.log('[env] SFTP connection test ✅');
        process.exit(0);
      })
      .catch(err => {
        console.error('[env] SFTP connection test ❌', err.message);
        process.exit(1);
      });
  } else {
    // Non-connecting checks
    if (!fs.existsSync(BUILD_DIR)) {
      console.warn(`[env] Note: build folder not found (${BUILD_DIR}). Run 'npm run build' before deploy.`);
    }
    console.log('[env] Validation ✅');
  }
})();
