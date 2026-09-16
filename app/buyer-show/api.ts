export type BuyerStyle = "更真实" | "更精致";
export type BuyerAsset = { id: string; assetId: string; role: "main" | "detail" | "scene" };
export interface BuyerInput { product_name: string; product_features: string; material: string; style: BuyerStyle; image_count: number; aspect_ratio: string; resolution: string; scene_preferences: string; selling_points: string; notes: string; assets: BuyerAsset[] }
export interface BuyerPlanItem { index: number; shot_type: string; scene_description: string; image_prompt: string; negative_prompt: string }
export interface BuyerPlan { project_title: string; aspect_ratio: string; resolution: string; image_plan: BuyerPlanItem[] }
export interface BuyerTaskItem { index: number; shotType: string; status: "queued" | "rendering" | "completed" | "failed"; attempt: number; previewUrl?: string; downloadUrl?: string; error?: { message: string } }
export interface BuyerTask { id: string; planId: string; status: "queued" | "running" | "completed" | "partial" | "failed"; items: BuyerTaskItem[]; exportUrl?: string }

const BASE = (process.env.NEXT_PUBLIC_DETAIL_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
export class BuyerApiError extends Error { constructor(message: string, public uncertain = false, public requestId = "") { super(message); } }

async function checked(response: Response) {
  if (response.ok) return response;
  let message = `请求失败（${response.status}）`, uncertain = false;
  try { const payload = await response.json(); if (typeof payload.detail?.message === "string") message = payload.detail.message; uncertain = payload.detail?.uncertain === true; } catch { /* retain safe status */ }
  throw new BuyerApiError(message, uncertain);
}

export async function uploadBuyerProduct(file: File): Promise<BuyerAsset> {
  const id = crypto.randomUUID(), data = new FormData(); data.append("file", file); data.append("clientId", id);
  const response = await checked(await fetch(`${BASE}/api/buyer-show/assets`, { method: "POST", headers: { "Idempotency-Key": id }, body: data }));
  const { assetId } = await response.json() as { assetId: string };
  return { id, assetId, role: "main" };
}

export async function createBuyerPlan(input: BuyerInput, planId: string): Promise<BuyerPlan> {
  try {
    const response = await checked(await fetch(`${BASE}/api/buyer-show/plans`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": planId }, body: JSON.stringify(input) }));
    return response.json() as Promise<BuyerPlan>;
  } catch (cause) {
    if (cause instanceof BuyerApiError) throw new BuyerApiError(cause.message, cause.uncertain, planId);
    throw new BuyerApiError("策划连接中断，请查询原请求；不要重复生成。", true, planId);
  }
}

export async function queryBuyerPlan(planId: string): Promise<BuyerPlan | null> {
  try {
    const response = await checked(await fetch(`${BASE}/api/buyer-show/plans/${encodeURIComponent(planId)}`, { cache: "no-store" }));
    const payload = await response.json() as { state: string; plan?: BuyerPlan; message?: string; uncertain?: boolean };
    if (payload.state === "completed" && payload.plan) return payload.plan;
    if (payload.state === "failed") throw new BuyerApiError(payload.message || "策划请求失败。", payload.uncertain === true, planId);
    return null;
  } catch (cause) {
    if (cause instanceof BuyerApiError) throw new BuyerApiError(cause.message, cause.uncertain, planId);
    throw new BuyerApiError("暂时无法查询原策划请求，请恢复连接后继续查询。", true, planId);
  }
}

export async function createBuyerTask(input: BuyerInput, planId: string, plan: BuyerPlan, taskId: string): Promise<BuyerTask> {
  try {
    const response = await checked(await fetch(`${BASE}/api/buyer-show/tasks`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": taskId }, body: JSON.stringify({ taskId, planId, input, plan }) }));
    return response.json() as Promise<BuyerTask>;
  } catch (cause) {
    if (cause instanceof BuyerApiError) throw new BuyerApiError(cause.message, cause.uncertain, taskId);
    throw new BuyerApiError("出图连接中断，请查询原任务；不要重复提交。", true, taskId);
  }
}

export async function queryBuyerTask(taskId: string): Promise<BuyerTask> {
  try { const response = await checked(await fetch(`${BASE}/api/buyer-show/tasks/${encodeURIComponent(taskId)}`, { cache: "no-store" })); return response.json() as Promise<BuyerTask>; }
  catch (cause) { if (cause instanceof BuyerApiError) throw new BuyerApiError(cause.message, cause.uncertain, taskId); throw new BuyerApiError("暂时无法查询原图片任务。", true, taskId); }
}

export function buyerResultUrl(path: string) { if (!path.startsWith("/api/buyer-show/")) throw new Error("结果地址无效"); return BASE + path; }
export function downloadBuyerPlan(plan: BuyerPlan) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(plan, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = "buyer-show-plan.json"; anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
