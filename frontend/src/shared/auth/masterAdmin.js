export const MASTER_ADMIN_EMAIL = 'support@jaspen.ai';

export function isMasterAdminUser(user) {
  return String(user?.email || '').trim().toLowerCase() === MASTER_ADMIN_EMAIL;
}
