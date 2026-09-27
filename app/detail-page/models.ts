export type Language = "zh-CN" | "en" | "es" | "fr" | "de" | "ja" | "ko";
export type AspectRatio = "3:4" | "16:9" | "1:1" | "9:16" | "4:3";
export type ImageRole = "main" | "detail" | "scene";

/** Browser object URLs are preview-only. Only assetId is sent to the renderer. */
export interface ProductImage {
  id: string;
  name: string;
  role: ImageRole;
  previewUrl: string;
  file: File;
  assetId?: string;
}

export interface InputParams {
  productName: string;
  fabric: string;
  craftsmanship: string;
  specifications: string;
  sellingPoints: string;
  notes: string;
  language: Language;
  imageCount: number;
  aspectRatio: AspectRatio;
  resolution: "1K" | "2K" | "4K";
}

export interface PlanItem {
  id: string;
  order: number;
  theme: string;
  visualDescription: string;
  stylePrompt: string;
  textOverlay: {
    headline: string;
    body: string;
    placement: "top" | "center" | "bottom" | "left" | "right";
  };
  sourceImageIds: string[];
}

export interface PlanDocument {
  schemaVersion: "1.0";
  planId: string;
  revision: number;
  source: "ai" | "template";
  input: InputParams;
  items: PlanItem[];
}

export type ImageStatus = "queued" | "rendering" | "completed" | "failed";
export interface RenderImage {
  planItemId: string;
  status: ImageStatus;
  attempt: number;
  previewUrl?: string;
  downloadUrl?: string;
  width?: number;
  height?: number;
  error?: { code: string; message: string; retryable: boolean };
}

export interface GenerateTask {
  id: string;
  parentTaskId?: string;
  planId: string;
  planRevision: number;
  status: "queued" | "running" | "completed" | "partial" | "failed";
  items: RenderImage[];
  createdAt: string;
  updatedAt: string;
  exportUrl?: string;
}

export interface RenderRequest {
  taskId: string;
  plan: PlanDocument;
  input: InputParams;
  assets: { id: string; assetId: string; role: ImageRole }[];
}

export type WorkflowPhase = "input" | "planning" | "review" | "submitting" | "rendering" | "finished";
export interface WorkflowState {
  phase: WorkflowPhase;
  plan: PlanDocument | null;
  task: GenerateTask | null;
  message: string;
}

export const initialInput: InputParams = {
  productName: "", fabric: "", craftsmanship: "", specifications: "",
  sellingPoints: "", notes: "", language: "zh-CN", imageCount: 6,
  aspectRatio: "3:4", resolution: "2K",
};

export const terminalTask = (task: GenerateTask) => ["completed", "partial", "failed"].includes(task.status);

export function reorderPlan(items: PlanItem[], fromId: string, toId: string): PlanItem[] {
  const from = items.findIndex((item) => item.id === fromId);
  const to = items.findIndex((item) => item.id === toId);
  if (from < 0 || to < 0 || from === to) return items;
  const next = [...items];
  next.splice(to, 0, next.splice(from, 1)[0]);
  return next.map((item, index) => ({ ...item, order: index + 1 }));
}

export function validateInput(input: InputParams, images: ProductImage[]): string {
  if (!input.productName.trim()) return "请填写产品名称。";
  if (!images.length) return "请至少上传一张产品图。";
  if (!images.some((image) => image.role === "main")) return "请将一张素材设为主图。";
  return "";
}

/** Local editable template; this function never claims to analyze images or call AI. */
export function templatePlan(input: InputParams, images: ProductImage[]): PlanDocument {
  const themes = ["品牌首屏海报", "核心卖点", "面料与触感", "工艺细节", "尺寸规格", "使用场景", "色彩搭配", "产品结构", "养护说明", "搭配建议", "细节汇总", "套件收尾"];
  return {
    schemaVersion: "1.0", planId: crypto.randomUUID(), revision: 1, source: "template", input: { ...input },
    items: Array.from({ length: input.imageCount }, (_, index) => ({
      id: crypto.randomUUID(), order: index + 1, theme: themes[index],
      visualDescription: `围绕「${themes[index]}」展示${input.productName}，保留产品结构、材质与颜色，为文案预留清晰空间。`,
      stylePrompt: "统一商业摄影风格、自然柔光与背景色调，不虚构产品参数。",
      textOverlay: { headline: index === 0 ? input.productName : themes[index], body: index === 1 ? input.sellingPoints : index === 2 ? input.fabric : index === 3 ? input.craftsmanship : index === 4 ? input.specifications : "", placement: "bottom" },
      sourceImageIds: [images[index % images.length].id],
    })),
  };
}

export function validatePlan(plan: PlanDocument, sourceIds: string[]): string {
  const id = /^[a-zA-Z0-9_-]{1,80}$/;
  if (!plan || plan.schemaVersion !== "1.0" || !id.test(plan.planId ?? "") || !Number.isInteger(plan.revision) || plan.revision < 1 || !["ai", "template"].includes(plan.source) || !plan.input || !Array.isArray(plan.items)) return "策划服务返回的 JSON 格式不正确。";
  if (!["zh-CN", "en", "es", "fr", "de", "ja", "ko"].includes(plan.input.language) || !["3:4", "16:9", "1:1", "9:16", "4:3"].includes(plan.input.aspectRatio) || !["1K", "2K", "4K"].includes(plan.input.resolution)) return "策划服务返回了不支持的输出参数。";
  if (plan.items.length < 1 || plan.items.length > 12 || plan.input.imageCount !== plan.items.length) return "方案必须包含 1–12 张图片，且与方案张数一致。";
  if (plan.items.some((item) => !item || typeof item.id !== "string")) return "策划方案包含无效卡片。";
  if (new Set(plan.items.map((item) => item.id)).size !== plan.items.length) return "方案卡片编号重复，请重新生成方案。";
  for (const [index, item] of plan.items.entries()) {
    if (!item || !id.test(item.id ?? "") || !Number.isInteger(item.order) || ![item.theme, item.visualDescription, item.stylePrompt, item.textOverlay?.headline, item.textOverlay?.body].every((value) => typeof value === "string") || !["top", "center", "bottom", "left", "right"].includes(item.textOverlay?.placement) || !Array.isArray(item.sourceImageIds)) return `第 ${index + 1} 张卡片数据格式不正确。`;
    if (item.order !== index + 1) return "方案顺序必须连续，请重新排序。";
    if (!item.theme.trim() || !item.visualDescription.trim() || !item.stylePrompt.trim()) return `请补全第 ${index + 1} 张的主题、画面描述和风格。`;
    if (item.theme.length > 120 || item.visualDescription.length > 2000 || item.stylePrompt.length > 1000 || item.textOverlay.headline.length > 200 || item.textOverlay.body.length > 1000) return `第 ${index + 1} 张卡片文字超出长度限制。`;
    if (!item.sourceImageIds.length || item.sourceImageIds.some((id) => !sourceIds.includes(id))) return `请检查第 ${index + 1} 张的参考素材。`;
  }
  return "";
}
