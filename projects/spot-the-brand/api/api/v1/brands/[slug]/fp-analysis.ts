// GET /api/v1/brands/[slug]/fp-analysis
//
// Returns FP rate split by bucket. Buckets:
//   - small_logo_lowconf : size=small, product=logo_only, conf<0.95
//   - small_lowconf      : size=small, conf<0.9
//   - background_lowconf : is_primary_subject=false, conf<0.9
//   - other              : everything else

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

  // Use a raw SQL via PostgREST RPC. If the RPC doesn't exist, fall back to
  // an in-memory aggregation over the verified rows.
  const { data: rows, error } = await sb()
    .from("detections")
    .select("size_in_frame, product_line, confidence, is_primary_subject, verified, is_false_positive")
    .eq("brand_id", brandId)
    .eq("detected", true);

  if (error) {
    res.status(500).json({ error: error.message });
    return;
  }

  type B = { total: number; verified: number; fps: number; tps: number };
  const init = (): B => ({ total: 0, verified: 0, fps: 0, tps: 0 });
  const buckets: Record<string, B> = {
    small_logo_lowconf: init(),
    small_lowconf: init(),
    background_lowconf: init(),
    other: init(),
  };

  for (const r of rows || []) {
    let key: keyof typeof buckets;
    if (r.size_in_frame === "small" && r.product_line === "logo_only" && (r.confidence ?? 0) < 0.95) key = "small_logo_lowconf";
    else if (r.size_in_frame === "small" && (r.confidence ?? 0) < 0.9) key = "small_lowconf";
    else if (r.is_primary_subject === false && (r.confidence ?? 0) < 0.9) key = "background_lowconf";
    else key = "other";

    buckets[key].total += 1;
    if (r.verified) {
      buckets[key].verified += 1;
      if (r.is_false_positive) buckets[key].fps += 1;
      else buckets[key].tps += 1;
    }
  }

  const result = Object.entries(buckets).map(([bucket, b]) => ({
    bucket,
    total: b.total,
    verified: b.verified,
    fps: b.fps,
    tps: b.tps,
    fp_pct: b.verified ? Math.round((1000 * b.fps) / b.verified) / 10 : 0,
  }));
  result.sort((a, b) => b.total - a.total);

  res.status(200).json(result);
}
