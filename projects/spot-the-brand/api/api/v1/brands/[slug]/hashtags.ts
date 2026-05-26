// GET  /api/v1/brands/[slug]/hashtags  — list pool
// POST /api/v1/brands/[slug]/hashtags  — add hashtag

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { handleCors, requireAuth } from "../../../../lib/auth.js";
import { sb, resolveBrandId } from "../../../../lib/supabase.js";

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (handleCors(req, res)) return;
  if (!requireAuth(req, res)) return;

  const slug = String(req.query.slug || "");
  const brandId = await resolveBrandId(slug);
  if (!brandId) {
    res.status(404).json({ error: `brand ${slug} not found` });
    return;
  }

  const client = sb();

  if (req.method === "GET") {
    const { data, error } = await client
      .from("brand_hashtag_pools")
      .select("id, hashtag, group_label, platform, priority, active")
      .eq("brand_id", brandId)
      .order("priority", { ascending: false });
    if (error) {
      res.status(500).json({ error: error.message });
      return;
    }
    res.status(200).json(data || []);
    return;
  }

  if (req.method === "POST") {
    const body = (req.body || {}) as Record<string, unknown>;
    const hashtag = (body.hashtag ? String(body.hashtag) : "").replace(/^#/, "").trim().toLowerCase();
    if (!hashtag || !/^[a-z0-9_]{2,50}$/.test(hashtag)) {
      res.status(400).json({ error: "invalid hashtag (lowercase alphanumeric, 2-50 chars)" });
      return;
    }
    const platform = body.platform === "tiktok" ? "tiktok" : "instagram";
    const priority = Math.min(Math.max(parseInt(String(body.priority ?? "5")) || 5, 1), 10);
    const group_label = body.group_label ? String(body.group_label).slice(0, 100) : null;

    const { data, error } = await client
      .from("brand_hashtag_pools")
      .insert({
        brand_id: brandId,
        hashtag,
        platform,
        priority,
        group_label,
        active: true,
      })
      .select()
      .single();
    if (error) {
      res.status(500).json({ error: error.message });
      return;
    }
    res.status(201).json(data);
    return;
  }

  res.status(405).json({ error: "method not allowed" });
}
