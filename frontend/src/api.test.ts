import { expect, test, vi } from "vitest";
import { postReview } from "./api";
test("posts a review decision", async () => { globalThis.fetch = vi.fn().mockResolvedValue(new Response("{}", { status: 202 })); await postReview("run-1", { scope: "stage", target: "stage-1", action: "approve" }); expect(fetch).toHaveBeenCalledWith("/api/runs/run-1/review", expect.objectContaining({ method: "POST" })); });
