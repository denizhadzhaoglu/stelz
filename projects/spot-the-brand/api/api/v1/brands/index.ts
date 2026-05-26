// GET /api/v1/brands — list brands the caller can see.
//
// Staff token sees every active brand.

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { handleCors, requireAuth } from "../../../lib/auth.js";
import { sb } from "../../../lib/supabase.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (handleCors(req, res)) return;
  if (req.method !== "GET") {
    res.status(405).json({ error: "method not allowed" });
    return;
  }
  const auth = requireAuth(req, res);
  if (!auth) return;

  const { data, error } = await sb()
    .from("brands")
    .select("id, slug, name, is_public_demo, active, created_at")
    .eq("active", true)
    .order("created_at", { ascending: true });

  if (error) {
    res.status(500).json({ error: error.message });
    return;
  }
  res.status(200).json(data || []);
}
