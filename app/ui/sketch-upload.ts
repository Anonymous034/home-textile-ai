export function validateSketchUpload(files: { type: string; size: number }[], existing: number, limit: number): string {
  if (files.length + existing > limit) return limit === 1 ? "此区域只能上传一张图片，请逐张选择。" : "参考图最多支持 12 张，请减少图片后重试。";
  if (files.some((file) => !["image/jpeg", "image/png", "image/webp"].includes(file.type))) return "仅支持 JPG、PNG、WEBP 图片。";
  if (files.some((file) => file.size === 0 || file.size > 20 * 1024 * 1024)) return "图片不能为空，且单张不能超过 20MB。";
  return "";
}
