// Supabase client singleton for the spot API.
//
// We use the service-role key because the API enforces its own auth via
// SPOT_API_TOKEN. When we migrate to per-user JWTs the call sites will
// switch to a request-scoped client that respects RLS.

import { createClient, SupabaseClient } from "@supabase/supabase-js";

let _client: SupabaseClient | null = null;

export function sb(): SupabaseClient {
  if (_client) return _client;
  const url = process.env.SUPABASE_URL;
  const key =
    process.env.SUPABASE_SERVICE_ROLE_KEY ||
    process.env.SUPABASE_SECRET_KEY;
  if (!url || !key) {
    throw new Error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required");
  }
  _client = createClient(url, key, {
    auth: { persistSession: false },
  });
  return _client;
}

/** Resolve a brand_slug to its id. Throws 404 via helper. */
export async function resolveBrandId(slug: string): Promise<string | null> {
  const { data } = await sb()
    .from("brands")
    .select("id")
    .eq("slug", slug)
    .maybeSingle();
  return data?.id || null;
}
