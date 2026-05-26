// GET /api/v1/system/health
//
// Live system health snapshot. Runs the same invariants as the tests/
// harness but as a single endpoint so anything (CLI, MCP, status page,
// uptime monitor) can poll it.
//
// Returns:
//   - status: "ok" | "warn" | "fail"
//   - checks: array of { name, status, value, threshold, op }
//   - summary counts
//
// Auth: same SPOT_API_TOKEN as the rest of /api/v1.

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { handleCors, requireAuth } from "../../../lib/auth.js";
import { sb } from "../../../lib/supabase.js";

type Check = {
  name: string;
  threshold: number;
  op: "<=" | ">=";
  sql: string;
  severity: "fail" | "warn"; // fail = red, warn = yellow
};

const CHECKS: Check[] = [
  // Structural integrity — must always be zero
  { name: "creators_no_brand", threshold: 0, op: "<=", severity: "fail",
    sql: "SELECT COUNT(*) FROM creators WHERE brand_id IS NULL" },
  { name: "creators_no_handle", threshold: 0, op: "<=", severity: "fail",
    sql: "SELECT COUNT(*) FROM creators WHERE handle IS NULL OR handle=''" },
  { name: "creators_dup", threshold: 0, op: "<=", severity: "fail",
    sql: "SELECT COUNT(*) FROM (SELECT brand_id, platform, handle FROM creators GROUP BY 1,2,3 HAVING COUNT(*)>1) x" },

  { name: "content_no_brand", threshold: 0, op: "<=", severity: "fail",
    sql: "SELECT COUNT(*) FROM content_items WHERE brand_id IS NULL" },
  { name: "content_no_creator", threshold: 0, op: "<=", severity: "fail",
    sql: "SELECT COUNT(*) FROM content_items WHERE creator_id IS NULL" },
  { name: "content_brand_mismatch", threshold: 0, op: "<=", severity: "fail",
    sql: "SELECT COUNT(*) FROM content_items ci JOIN creators c ON c.id=ci.creator_id WHERE ci.brand_id != c.brand_id" },

  { name: "images_orphan", threshold: 0, op: "<=", severity: "fail",
    sql: "SELECT COUNT(*) FROM content_images img WHERE NOT EXISTS (SELECT 1 FROM content_items ci WHERE ci.id=img.content_item_id)" },
  { name: "images_brand_mismatch", threshold: 0, op: "<=", severity: "fail",
    sql: "SELECT COUNT(*) FROM content_images img JOIN content_items ci ON ci.id=img.content_item_id WHERE img.brand_id != ci.brand_id" },

  { name: "detections_orphan", threshold: 0, op: "<=", severity: "fail",
    sql: "SELECT COUNT(*) FROM detections d WHERE NOT EXISTS (SELECT 1 FROM content_images img WHERE img.id=d.content_image_id)" },
  { name: "detections_brand_mismatch", threshold: 0, op: "<=", severity: "fail",
    sql: "SELECT COUNT(*) FROM detections d JOIN content_images img ON img.id=d.content_image_id WHERE d.brand_id != img.brand_id" },

  // Pipeline health — warnings, not fail
  { name: "scans_stuck_running_30m", threshold: 0, op: "<=", severity: "warn",
    sql: "SELECT COUNT(*) FROM scan_requests WHERE status='running' AND requested_at < NOW() - INTERVAL '30 minutes'" },
  { name: "scans_stuck_pending_24h", threshold: 0, op: "<=", severity: "warn",
    sql: "SELECT COUNT(*) FROM scan_requests WHERE status='pending' AND requested_at < NOW() - INTERVAL '24 hours'" },
  { name: "pending_detection_images", threshold: 500, op: "<=", severity: "warn",
    sql: "SELECT COUNT(*) FROM content_images img WHERE NOT EXISTS (SELECT 1 FROM detections d WHERE d.content_image_id=img.id)" },

  // Freshness — warnings
  { name: "detections_last_1h", threshold: 1, op: ">=", severity: "warn",
    sql: "SELECT COUNT(*) FROM detections WHERE created_at > NOW() - INTERVAL '1 hour'" },
  { name: "hits_last_24h", threshold: 1, op: ">=", severity: "warn",
    sql: "SELECT COUNT(*) FROM detections WHERE detected=true AND created_at > NOW() - INTERVAL '24 hours'" },

  // Billing integrity
  { name: "brand_active_no_credit_row", threshold: 0, op: "<=", severity: "fail",
    sql: "SELECT COUNT(*) FROM brands b WHERE active=true AND NOT EXISTS (SELECT 1 FROM credit_balances cb WHERE cb.brand_id=b.id)" },
  { name: "credit_balance_negative", threshold: 0, op: "<=", severity: "fail",
    sql: "SELECT COUNT(*) FROM credit_balances WHERE balance < 0" },

  // Mojibake detection. Catches double-UTF-8-encoded text in user-facing
  // columns. Added 21 May after STELZ brand name showed as ST√ãLZ for >9d.
  { name: "brands_mojibake", threshold: 0, op: "<=", severity: "warn",
    sql: "SELECT COUNT(*) FROM brands WHERE name LIKE '%√ã%' OR name LIKE '%Ã©%' OR name LIKE '%Ã«%'" },
  { name: "creators_mojibake", threshold: 0, op: "<=", severity: "warn",
    sql: "SELECT COUNT(*) FROM creators WHERE full_name LIKE '%√ã%' OR full_name LIKE '%Ã©%' OR full_name LIKE '%Ã«%'" },
];

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (handleCors(req, res)) return;
  if (req.method !== "GET") {
    res.status(405).json({ error: "method not allowed" });
    return;
  }
  if (!requireAuth(req, res)) return;

  const client = sb();
  type Result = { name: string; status: "ok" | "warn" | "fail"; value: number | null; threshold: number; op: string; severity: string; error?: string };
  const results: Result[] = await Promise.all(
    CHECKS.map(async (c): Promise<Result> => {
      try {
        const { data, error } = await client.rpc("exec_sql_count", { q: c.sql });
        if (error) return { name: c.name, status: "warn", value: null, threshold: c.threshold, op: c.op, severity: c.severity, error: error.message };
        const v = typeof data === "number" ? data : parseInt(String(data ?? 0), 10);
        const ok = c.op === "<=" ? v <= c.threshold : v >= c.threshold;
        return { name: c.name, status: ok ? "ok" : c.severity, value: v, threshold: c.threshold, op: c.op, severity: c.severity };
      } catch (e) {
        return { name: c.name, status: "warn", value: null, threshold: c.threshold, op: c.op, severity: c.severity, error: (e as Error).message };
      }
    }),
  );

  const fails = results.filter(r => r.status === "fail").length;
  const warns = results.filter(r => r.status === "warn").length;
  const overall: "ok" | "warn" | "fail" = fails > 0 ? "fail" : warns > 0 ? "warn" : "ok";

  res.status(overall === "fail" ? 503 : 200).json({
    status: overall,
    summary: {
      checks_total: results.length,
      checks_ok: results.filter(r => r.status === "ok").length,
      checks_warn: warns,
      checks_fail: fails,
    },
    checks: results,
    timestamp: new Date().toISOString(),
  });
}
