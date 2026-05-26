// POST /api/v1/detections/[id]/false-positive

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { handleCors, requireAuth } from "../../../../lib/auth.js";
import { sb } from "../../../../lib/supabase.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (handleCors(req, res)) return;
  if (req.method !== "POST") {
    res.status(405).json({ error: "method not allowed" });
    return;
  }
  const auth = requireAuth(req, res);
  if (!auth) return;

  const id = String(req.query.id || "");
  if (!id) {
    res.status(400).json({ error: "missing id" });
    return;
  }

  const { error, count } = await sb()
    .from("detections")
    .update(
      {
        verified: true,
        is_false_positive: true,
        verified_by: `spot-api:${auth.kind}`,
        verified_at: new Date().toISOString(),
      },
      { count: "exact" },
    )
    .eq("id", id);

  if (error) {
    res.status(500).json({ error: error.message });
    return;
  }
  if (!count) {
    res.status(404).json({ error: "detection not found" });
    return;
  }
  res.status(200).json({ marked: true, detection_id: id });
}
