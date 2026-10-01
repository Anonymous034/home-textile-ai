import type { GenerateTask, InputParams, PlanDocument, PlanItem, ProductImage, RenderRequest } from "./models";

const BASE = (process.env.NEXT_PUBLIC_DETAIL_API_URL ?? process.env.NEXT_PUBLIC_STUDIO_API ?? "").replace(/\/+$/, "");
export class DetailApiError extends Error {
  constructor(message: string, public uncertain = false) { super(message); }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    const timeout = AbortSignal.timeout(options.method === "POST" ? 90000 : 20000);
    response = await fetch(`${BASE}/api/detail${path}`, { ...options, cache: "no-store", signal: options.signal ? AbortSignal.any([options.signal, timeout]) : timeout });
  } catch {
    throw new DetailApiError("暂时无法连接详情页服务，请稍后查询任务状态。", options.method === "POST");
  }
  if (!response.ok) {
    let detail: { message?: string; uncertain?: boolean } | undefined;
    try { const payload = await response.json(); if (typeof payload.detail === "object") detail = payload.detail; } catch { /* Non-JSON infrastructure errors are handled below. */ }
    if (typeof detail?.message === "string") throw new DetailApiError(detail.message, detail.uncertain === true);
    if (response.status === 404 || response.status === 503) throw new DetailApiError("详情页 AI 服务尚未就绪，请检查后端与策划模型配置。", response.status === 503 && options.method === "POST");
    if (response.status === 409) throw new DetailApiError("任务版本或请求标识冲突，请查询原任务后再操作。");
    if (response.status === 429) throw new DetailApiError("当前请求较多，请稍后再试。");
    throw new DetailApiError(`请求未成功（${response.status}），请检查输入或联系服务管理员。`, response.status >= 500 && options.method === "POST");
  }
  try { return await response.json() as T; }
  catch { throw new DetailApiError("服务返回了无法解析的数据，请查询原任务状态。", options.method === "POST"); }
}

function checkedTask(task: GenerateTask, id: string): GenerateTask {
  if (!task || task.id !== id || !["queued", "running", "completed", "partial", "failed"].includes(task.status) || !Array.isArray(task.items) || task.items.length === 0 || task.items.some((item) => !item || typeof item.planItemId !== "string" || !["queued", "rendering", "completed", "failed"].includes(item.status))) throw new DetailApiError("任务状态格式不正确，请查询原任务。", true);
  return task;
}

const post = <T>(path: string, body: unknown, key: string) => request<T>(path, {
  method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key }, body: JSON.stringify(body),
});

export const detailApi = {
  planStatus: (id: string, signal?: AbortSignal) => request<{ state: "running" | "completed" | "failed"; plan?: PlanDocument; message?: string; uncertain?: boolean }>(`/plans/${encodeURIComponent(id)}`, { signal }),
  async upload(images: ProductImage[]): Promise<ProductImage[]> {
    const result: ProductImage[] = [];
    for (const image of images) {
      if (image.assetId) { result.push(image); continue; }
      const data = new FormData(); data.append("file", image.file); data.append("clientId", image.id);
      const saved = await request<{ assetId: string }>("/assets", { method: "POST", body: data, headers: { "Idempotency-Key": image.id } });
      result.push({ ...image, assetId: saved.assetId });
    }
    return result;
  },
  plan: (input: InputParams, images: ProductImage[], key: string) => post<PlanDocument>("/plans", { input, assets: images.map((image) => ({ id: image.id, assetId: image.assetId, role: image.role })) }, key),
  revise: (plan: PlanDocument, item: PlanItem) => post<PlanItem>(`/plans/${plan.planId}/items/${item.id}/revise`, { input: plan.input, item }, crypto.randomUUID()),
  render: async (body: RenderRequest) => checkedTask(await post<GenerateTask>("/tasks", body, body.taskId), body.taskId),
  task: async (id: string, signal?: AbortSignal) => checkedTask(await request<GenerateTask>(`/tasks/${encodeURIComponent(id)}`, { signal }), id),
  redraw: async (taskId: string, item: PlanItem, newTaskId: string) => checkedTask(await post<GenerateTask>(`/tasks/${encodeURIComponent(taskId)}/items/${item.id}/redraw`, { taskId: newTaskId, item }, newTaskId), newTaskId),
};

/** Provider URLs must be same-service file endpoints, not arbitrary external URLs. */
export function resultUrl(path?: string): string | undefined {
  if (!path || !path.startsWith("/api/detail/") || path.includes("\\")) return undefined;
  const origin = BASE || "https://same-origin.invalid";
  const url = new URL(path, origin);
  return url.origin === new URL(origin).origin && url.pathname.startsWith("/api/detail/")
    ? BASE ? url.href : `${url.pathname}${url.search}${url.hash}`
    : undefined;
}
