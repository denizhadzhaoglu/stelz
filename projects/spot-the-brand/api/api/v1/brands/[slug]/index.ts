// GET /api/v1/brands/[slug]

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

  const client = sb();
  const [brandRes, creatorsRes, hitsTotal, hits7d, tier1Res] = await Promise.all([
    client.from("brands").select("*").eq("id", brandId).single(),
    client.from("creators").select("id", { count: "exact", head: true }).eq("brand_id", brandId),
    client.from("detections").select("id", { count: "exact", head: true }).eq("brand_id", brandId).eq("detected", true),
    client.from("detections").select("id", { count: "exact", head: true }).eq("brand_id", brandId).eq("detected", true).gte("created_at", new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString()),
    client.from("creators").select("id", { count: "exact", head: true }).eq("brand_id", brandId).eq("tier", "tier_1"),
  ]);

  if (brandRes.error || !brandRes.data) {
    res.status(404).json({ error: "brand not found" });
    return;
  }

  res.status(200).json({
    ...brandRes.data,
    creators_total: creatorsRes.count || 0,
    hits_total: hitsTotal.count || 0,
    hits_last_7d: hits7d.count || 0,
    tier_1_creators: tier1Res.count || 0,
  });
}
