// GET /api/v1/brands/[slug]/top-creators?limit=20&tier=all&min_hits=1

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

  const limit = Math.min(parseInt(String(req.query.limit ?? "20")) || 20, 200);
  const minHits = Math.max(parseInt(String(req.query.min_hits ?? "1")) || 1, 0);
  const tier = String(req.query.tier ?? "all");

  let q = sb()
    .from("creators")
    .select(
      "handle, full_name, platform, category, tier, follower_count, hits_seen, posts_seen, last_hit_at, relevance_score, auto_added_via",
    )
    .eq("brand_id", brandId)
    .gte("hits_seen", minHits)
    .order("hits_seen", { ascending: false })
    .order("last_hit_at", { ascending: false, nullsFirst: false })
    .limit(limit);

  if (tier !== "all") q = q.eq("tier", tier);

  const { data, error } = await q;
  if (error) {
    res.status(500).json({ error: error.message });
    return;
  }
  res.status(200).json(data || []);
}
