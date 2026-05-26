// GET /api/v1/brands/[slug]/health
//
// Health snapshot: scan throughput, FP rate, pending detections,
// stuck scans. The single-most-useful endpoint for ops.

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
  if (!slug) {
    res.status(400).json({ error: "missing slug" });
    return;
  }
  const brandId = await resolveBrandId(slug);
  if (!brandId) {
    res.status(404).json({ error: `brand ${slug} not found` });
    return;
  }

  const client = sb();
  // Run aggregates in parallel.
  const [
    lastDet, lastScan, dets24h, hits24h, creatorsTotal, scansPending, scansStuck, fpStats,
  ] = await Promise.all([
    client.from("detections").select("created_at").eq("brand_id", brandId).order("created_at", { ascending: false }).limit(1),
    client.from("scan_requests").select("completed_at").eq("brand_id", brandId).eq("status", "completed").order("completed_at", { ascending: false }).limit(1),
    client.from("detections").select("id", { count: "exact", head: true }).eq("brand_id", brandId).gte("created_at", new Date(Date.now() - 24 * 3600 * 1000).toISOString()),
    client.from("detections").select("id", { count: "exact", head: true }).eq("brand_id", brandId).eq("detected", true).gte("created_at", new Date(Date.now() - 24 * 3600 * 1000).toISOString()),
    client.from("creators").select("id", { count: "exact", head: true }).eq("brand_id", brandId),
    client.from("scan_requests").select("id", { count: "exact", head: true }).eq("brand_id", brandId).eq("status", "pending"),
    client.from("scan_requests").select("id", { count: "exact", head: true }).eq("brand_id", brandId).eq("status", "running").lt("requested_at", new Date(Date.now() - 30 * 60 * 1000).toISOString()),
    client.from("detections").select("verified, is_false_positive").eq("brand_id", brandId).eq("detected", true).eq("verified", true),
  ]);

  const verifiedRows = fpStats.data || [];
  const totalVerified = verifiedRows.length;
  const fpCount = verifiedRows.filter(r => r.is_false_positive).length;
  const fpPct = totalVerified ? (100 * fpCount) / totalVerified : 0;

  const dets = dets24h.count || 0;
  const hits = hits24h.count || 0;

  res.status(200).json({
    brand_slug: slug,
    last_detection_at: lastDet.data?.[0]?.created_at || null,
    last_scan_completed_at: lastScan.data?.[0]?.completed_at || null,
    detections_last_24h: dets,
    hits_last_24h: hits,
    hit_rate_24h_pct: dets ? Math.round((1000 * hits) / dets) / 10 : 0,
    creators_total: creatorsTotal.count || 0,
    creators_pending_detection: null, // expensive to compute live; surfaced via materialized view if needed
    scan_requests_pending: scansPending.count || 0,
    scan_requests_stuck_30m: scansStuck.count || 0,
    fp_rate_verified_pct: Math.round(fpPct * 10) / 10,
  });
}
