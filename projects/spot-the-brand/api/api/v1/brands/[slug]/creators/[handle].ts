// GET /api/v1/brands/[slug]/creators/[handle]

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { handleCors, requireAuth } from "../../../../../lib/auth.js";
import { sb, resolveBrandId } from "../../../../../lib/supabase.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (handleCors(req, res)) return;
  if (req.method !== "GET") {
    res.status(405).json({ error: "method not allowed" });
    return;
  }
  if (!requireAuth(req, res)) return;

  const slug = String(req.query.slug || "");
  const handle = String(req.query.handle || "").replace(/^@/, "").trim().toLowerCase();
  if (!handle) {
    res.status(400).json({ error: "missing handle" });
    return;
  }
  const brandId = await resolveBrandId(slug);
  if (!brandId) {
    res.status(404).json({ error: `brand ${slug} not found` });
    return;
  }

  const client = sb();
  const { data: c, error: ce } = await client
    .from("creators")
    .select("id, handle, full_name, platform, category, tier, follower_count, hits_seen, posts_seen, last_hit_at, relevance_score, auto_added_via, bio, ai_summary")
    .eq("brand_id", brandId)
    .eq("handle", handle)
    .maybeSingle();

  if (ce) {
    res.status(500).json({ error: ce.message });
    return;
  }
  if (!c) {
    res.status(404).json({ error: `creator ${handle} not found for ${slug}` });
    return;
  }

  // Recent hits for this creator
  const { data: hits } = await client
    .from("v_detections_full")
    .select(
      "detection_id, detected_at, confidence, size_in_frame, product_line, is_primary_subject, is_false_positive, verified, creator_handle, creator_tier, platform, post_url, image_url, post_caption, likes_count",
    )
    .eq("brand_id", brandId)
    .eq("creator_handle", handle)
    .eq("detected", true)
    .order("detected_at", { ascending: false })
    .limit(20);

  res.status(200).json({ ...c, recent_hits: hits || [] });
}
