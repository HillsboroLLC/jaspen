import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.REACT_APP_SUPABASE_URL;
const supabaseAnonKey = process.env.REACT_APP_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  console.warn('[Supabase] Env vars missing. REACT_APP_SUPABASE_URL:', supabaseUrl ? 'set' : 'MISSING', 'REACT_APP_SUPABASE_ANON_KEY:', supabaseAnonKey ? 'set' : 'MISSING');
} else {
  console.log('[Supabase] Client initialized for:', supabaseUrl);
}

export const supabase =
  supabaseUrl && supabaseAnonKey
    ? createClient(supabaseUrl, supabaseAnonKey, {
        auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
      })
    : null;

export const isSupabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey);
