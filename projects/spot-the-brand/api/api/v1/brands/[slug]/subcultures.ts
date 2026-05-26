// GET /api/v1/brands/[slug]/subcultures

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { handleCors, requireAuth } from "../../../../lib/auth.js";
import { sb, resolveBrandId } from "../../../../lib/supabase.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (handleCors(req, res)) return;
  if (req.method !== "GET") {
    res.status(405).json({ error: "method not allowed" });
    return;
  }
  if (!requireAuth(req, res)) return;

  const slug = String(req.query.slug || "");
  const brandId = await resolveBrandId(slug);
  if (!brandId) {
    res.status(404).json({ error: `brand ${slug} not found` });
    return;
  }

  const { data, error } = await sb()
    .from("v_subculture_stats")
    .select("*")
    .eq("brand_id", brandId);
  if (error) {
    res.status(500).json({ error: error.message });
    return;
  }
  res.status(200).json(data || []);
}
