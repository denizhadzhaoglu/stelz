// Shared 501 helper for endpoints scheduled for a later sprint.
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { handleCors, requireAuth } from "./auth.js";

export function stub(name: string) {
  return async (req: VercelRequest, res: VercelResponse) => {
    if (handleCors(req, res)) return;
    if (!requireAuth(req, res)) return;
    res.status(501).json({
      error: "not implemented",
      operation: name,
      note: "scheduled for v0.2; see openapi.yaml",
    });
  };
}
