// GET /api/v1/brands/[slug]/hits
// Recent hits, defaults to last 7 days, meaningful-only.

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

  const days = Math.min(Math.max(parseInt(String(req.query.days ?? "7")) || 7, 1), 90);
  const limit = Math.min(Math.max(parseInt(String(req.query.limit ?? "50")) || 50, 1), 200);
  const minConf = Math.max(parseFloat(String(req.query.min_confidence ?? "0.7")) || 0.7, 0);
  const tier = String(req.query.tier ?? "all");
  const includeUnverified = String(req.query.include_unverified ?? "true") !== "false";

  const since = new Date(Date.now() - days * 24 * 3600 * 1000).toISOString();

  let q = sb()
    .from("v_detections_full")
    .select(
      "detection_id, detected_at, confidence, size_in_frame, product_line, is_primary_subject, is_false_positive, verified, creator_handle, creator_tier, platform, post_url, image_url, post_caption, likes_count",
    )
    .eq("brand_id", brandId)
    .eq("detected", true)
    .gte("detected_at", since)
    .gte("confidence", minConf)
    .order("detected_at", { ascending: false })
    .limit(limit);

  if (!includeUnverified) q = q.eq("verified", true);
  if (tier !== "all") q = q.eq("creator_tier", tier);

  const { data, error } = await q;
  if (error) {
    res.status(500).json({ error: error.message });
    return;
  }
  // Post-filter: meaningful only (size in medium/large/dominant OR primary subject)
  const meaningful = (data || []).filter(
    (d: any) =>
      ["medium", "large", "dominant"].includes(d.size_in_frame || "") ||
      d.is_primary_subject === true,
  );
  res.status(200).json(meaningful);
}
