// POST /api/v1/brands/[slug]/scans — queue a scan

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { handleCors, requireAuth } from "../../../../lib/auth.js";
import { sb, resolveBrandId } from "../../../../lib/supabase.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (handleCors(req, res)) return;
  if (req.method !== "POST") {
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

  const body = (req.body || {}) as Record<string, unknown>;
  const scope = body.scope === "daily" || body.scope === "full" ? body.scope : "priority";
  const force = body.force === true;

  // Atomic credit check + scan insert. RPC raises P0001 on insufficient credits.
  const { data, error } = await sb().rpc("request_scan_with_quota", {
    p_brand_id: brandId,
    p_scope: scope,
    p_requested_by: "spot-api",
    p_force: force,
  });

  if (error) {
    const msg = error.message || "rpc failed";
    if (/insufficient credits|no credit_balances/i.test(msg)) {
      res.status(402).json({ error: msg, code: "insufficient_credits" });
      return;
    }
    res.status(500).json({ error: msg });
    return;
  }
  res.status(202).json({ scan_request_id: data.id, status: data.status });
}
