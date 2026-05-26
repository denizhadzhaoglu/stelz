// Bearer-token guard for the spot API.
//
// Two valid token types:
//   1. Staff service token (SPOT_API_TOKEN env var) — full access across all
//      brands. Used by the spot CLI, the MCP server, and internal scripts.
//   2. Supabase user JWT — read-only access scoped to the brands the user
//      belongs to via brand_users. Used by end-customer integrations.
//
// While the API is private (Meinte's pilot phase), only #1 is accepted.
// When we go public, switch the `acceptUserJwt` flag to true and add RLS
// enforcement on each query.

import type { VercelRequest, VercelResponse } from "@vercel/node";

export type AuthContext = {
  kind: "staff" | "user";
  user_id?: string;
};

const STAFF_TOKEN = process.env.SPOT_API_TOKEN;

/**
 * Validates the Authorization header. Returns AuthContext on success,
 * or writes a 401 response and returns null on failure.
 */
export function requireAuth(
  req: VercelRequest,
  res: VercelResponse,
): AuthContext | null {
  const header = req.headers.authorization || req.headers.Authorization;
  if (!header || typeof header !== "string") {
    res.status(401).json({ error: "missing Authorization header" });
    return null;
  }
  const match = header.match(/^Bearer\s+(.+)$/i);
  if (!match) {
    res.status(401).json({ error: "expected Bearer token" });
    return null;
  }
  const token = match[1].trim();

  if (!STAFF_TOKEN) {
    res.status(500).json({ error: "SPOT_API_TOKEN not configured" });
    return null;
  }
  if (token === STAFF_TOKEN) {
    return { kind: "staff" };
  }

  res.status(401).json({ error: "invalid token" });
  return null;
}

/**
 * Lightweight CORS preflight handler. Returns true when the request was
 * an OPTIONS preflight and the response is already written.
 */
export function handleCors(req: VercelRequest, res: VercelResponse): boolean {
  if (req.method === "OPTIONS") {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    res.setHeader(
      "Access-Control-Allow-Headers",
      "Authorization, Content-Type",
    );
    res.status(204).end();
    return true;
  }
  return false;
}
