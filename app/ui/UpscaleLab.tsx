"use client";

import { useEffect, useRef, useState, type DragEvent } from "react";
import "./TemplateLab.css";
import "./UpscaleLab.css";

const API = process.env.NEXT_PUBLIC_STUDIO_API ?? "http://127.0.0.1:8000";
type SourceImage = { id: string; url: string; name: string; fingerprint: string; file: File };
type EnhanceResult = { url?: string; status: "waiting" | "processing" | "completed" | "failed"; error?: string; outputSize?: number[] };
const MAX_IMAGES = 12;
const MAX_BYTES = 20 * 1024 * 1024;

function Icon({ name }: { name: "back" | "upload" | "expand" | "chevron" | "spark" | "close" }) {
  const paths = {
    back: <path d="m15 18-6-6 6-6" />,
    upload: <><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" /><path d="M5 15v4h14v-4" /></>,
    expand: <><path d="M9 3H3v6m12-6h6v6M3 15v6h6m12-6v6h-6M3 3l6 6m12-6-6 6M3 21l6-6m12 6-6-6" /></>,
    chevron: <path d="m8 10 4 4 4-4" />,
    spark: <><path d="m12 3 1.35 4.15L17.5 8.5l-4.15 1.35L12 14l-1.35-4.15L6.5 8.5l4.15-1.35L12 3Z" /><path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z" /></>,
    close: <path d="m7 7 10 10M17 7 7 17" />,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

export default function UpscaleLab({ initialFile, backHref = "/dashboard?tool=upscale", onBack }: { initialFile?: File; backHref?: string; onBack?: () => void } = {}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const imageStore = useRef<SourceImage[]>([]);
  const liveUrls = useRef(new Set<string>());
  const [images, setImages] = useState<SourceImage[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState("清晰增强");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [generating, setGenerating] = useState(false);
  const [results, setResults] = useState<Record<string, EnhanceResult>>({});
  const selected = images.find((item) => item.id === selectedId) ?? images[0];
  const selectedResult = selected ? results[selected.id] : undefined;

  useEffect(() => {
    const urls = liveUrls.current;
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  const addImages = (files: FileList | null) => {
    setDragging(false);
    if (!files?.length) return;
    setNotice("");
    const next = [...imageStore.current];
    const warnings = new Set<string>();
    let firstAdded: string | null = null;
    for (const file of Array.from(files)) {
      if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
        warnings.add("仅支持 JPG、PNG、WEBP 图片");
        continue;
      }
      if (file.size > MAX_BYTES) {
        warnings.add("已跳过超过 20MB 的图片");
        continue;
      }
      const fingerprint = `${file.name}:${file.size}:${file.lastModified}`;
      if (next.some((item) => item.fingerprint === fingerprint)) {
        warnings.add("重复图片已跳过");
        continue;
      }
      if (next.length >= MAX_IMAGES) {
        warnings.add("最多导入 12 张图片，多余图片未添加");
        continue;
      }
      const url = URL.createObjectURL(file);
      liveUrls.current.add(url);
      const id = crypto.randomUUID();
      firstAdded ??= id;
      next.push({ id, url, name: file.name, fingerprint, file });
    }
    imageStore.current = next;
    setImages(next);
    if (firstAdded) setSelectedId(firstAdded);
    setError(Array.from(warnings).join("；"));
  };

  useEffect(() => {
    if (initialFile && imageStore.current.length === 0) addImages([initialFile] as unknown as FileList);
  }, [initialFile]);

  const removeImage = (id: string) => {
    const removed = imageStore.current.find((item) => item.id === id);
    const next = imageStore.current.filter((item) => item.id !== id);
    imageStore.current = next;
    setImages(next);
    if (removed) {
      URL.revokeObjectURL(removed.url);
      liveUrls.current.delete(removed.url);
    }
    setNotice("");
    setResults((current) => { const nextResults = { ...current }; delete nextResults[id]; return nextResults; });
  };

  const handleImageError = (id: string) => {
    if (!imageStore.current.some((item) => item.id === id)) return;
    removeImage(id);
    setError("有图片无法读取，已从列表移除，请重新选择有效图片。");
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    addImages(event.dataTransfer.files);
  };

  const generate = async () => {
    if (!images.length || generating) return;
    setGenerating(true);
    setError("");
    setNotice(`正在按“${mode}”逐张处理 1 / ${images.length}…`);
    const nextResults: Record<string, EnhanceResult> = Object.fromEntries(images.map((item) => [item.id, { status: "waiting" }]));
    setResults(nextResults);
    let completed = 0;
    for (let index = 0; index < images.length; index += 1) {
      const item = images[index];
      nextResults[item.id] = { status: "processing" };
      setResults({ ...nextResults });
      setSelectedId(item.id);
      setNotice(`正在按“${mode}”逐张处理 ${index + 1} / ${images.length}…`);
      try {
        const form = new FormData();
        form.append("image", item.file, item.name);
        form.append("mode", mode === "清晰增强" ? "detail" : "upscale");
        const response = await fetch(`${API}/api/upscale/generate`, { method: "POST", body: form, signal: AbortSignal.timeout(360000) });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "AI 高清处理失败。");
        nextResults[item.id] = { status: "completed", url: `${API}${data.result_url}?v=${Date.now()}`, outputSize: data.output_size };
        completed += 1;
      } catch (reason) {
        nextResults[item.id] = { status: "failed", error: reason instanceof Error ? reason.message : "处理失败" };
      }
      setResults({ ...nextResults });
    }
    setGenerating(false);
    setNotice(completed === images.length ? `已完成 ${completed} 张图片的 AI 高清处理。` : `已完成 ${completed} 张，失败 ${images.length - completed} 张；可重新提交失败图片。`);
  };

  return (
    <main className="template-lab upscale-lab">
      <header className="template-hud">
        {onBack ? <button type="button" className="template-back" onClick={onBack}><Icon name="back" /><span>返回花型制作</span></button> : <a className="template-back" href={backHref}><Icon name="back" /><span>返回</span></a>}
        <div className="template-brand"><i>42</i><div><strong>IMAGE ENHANCE LAB</strong><small>AI 图像高清控制台</small></div></div>
        <div className="template-status"><i /><span>LOCAL WORKSPACE</span><b>本地预览</b></div>
      </header>

      <div className="template-layout">
        <section className="template-canvas" aria-label="高清图片画布">
          <div className="template-toolbar"><div><span>图片素材预览</span><i /><span>支持批量导入</span></div><button type="button" onClick={() => inputRef.current?.click()}><Icon name="upload" />导入到画布</button></div>
          <div className={`template-stage upscale-stage ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }} onDrop={onDrop}>
            <span className="template-grid-glow" aria-hidden="true" />
            <div className="template-stage-corners" aria-hidden="true"><i /><i /><i /><i /></div>
            {selected ? (
              <figure className="upscale-preview"><img src={selectedResult?.url || selected.url} alt={selectedResult?.url ? `AI 高清结果：${selected.name}` : `原图预览：${selected.name}`} onError={selectedResult?.url ? undefined : () => handleImageError(selected.id)} /><figcaption><span>{selectedResult?.status === "processing" ? "AI PROCESSING · 正在处理" : selectedResult?.url ? "AI ENHANCED · 高清结果" : "SOURCE IMAGE · 原图预览"}</span><strong>{selected.name}{selectedResult?.outputSize ? ` · ${selectedResult.outputSize.join(" × ")} px` : ""}</strong></figcaption></figure>
            ) : (
              <div className="template-empty upscale-empty"><div className="template-orbit"><Icon name="expand" /></div><span>IMAGE ENHANCE / CANVAS READY</span><p>添加需要处理的图片，最多支持 12 张。</p><button type="button" onClick={() => inputRef.current?.click()}><Icon name="upload" />添加图片</button></div>
            )}
          </div>
          <footer className="template-footer"><span><i />{generating ? "AI PROCESSING" : Object.values(results).some((item) => item.status === "completed") ? "RESULT READY" : images.length ? "SOURCE LOADED" : "CANVAS READY"}</span><b>{images.length} / 12 张 · {mode}</b></footer>
        </section>

        <aside className="template-panel upscale-panel" aria-label="高清处理设置">
          <div className="upscale-tool-menu template-panel-title">
            <h1><i><Icon name="expand" /></i>一键高清</h1>
          </div>

          <section className="template-card upscale-upload-card">
            <header><div><span>01</span><strong>图片</strong></div><em className="upscale-count" aria-live="polite">{images.length}/12 张</em></header>
            <input className="upscale-file-input" ref={inputRef} type="file" multiple accept="image/jpeg,image/png,image/webp" aria-label="导入图片文件" tabIndex={-1} onChange={(event) => { addImages(event.target.files); event.target.value = ""; }} />
            <div className={`upscale-dropzone ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
              <button type="button" onClick={() => inputRef.current?.click()}><span><Icon name="upload" /></span><strong>{images.length ? "继续添加图片" : "上传或拖入图片"}</strong><small>JPG / PNG / WEBP · 单张不超过 20MB</small></button>
            </div>
            {images.length > 0 && <ul className="upscale-thumbnails" aria-label="已导入图片">{images.map((item, index) => <li key={item.id} className={`${selected?.id === item.id ? "is-selected" : ""} is-${results[item.id]?.status || "idle"}`}><button className="upscale-thumbnail" type="button" onClick={() => setSelectedId(item.id)} aria-label={`预览图片 ${index + 1}：${item.name}`} aria-pressed={selected?.id === item.id}><img src={results[item.id]?.url || item.url} alt="" onError={results[item.id]?.url ? undefined : () => handleImageError(item.id)} /><span>{results[item.id]?.status === "processing" ? "处理中" : results[item.id]?.status === "completed" ? "完成" : results[item.id]?.status === "failed" ? "失败" : String(index + 1).padStart(2, "0")}</span></button><button className="upscale-remove" type="button" disabled={generating} onClick={() => removeImage(item.id)} aria-label={`移除图片 ${index + 1}：${item.name}`}><Icon name="close" /></button></li>)}</ul>}
            {error && <p className="upscale-message" role="alert">{error}</p>}
          </section>

          <section className="template-card upscale-method-card">
            <fieldset><legend><span>02</span>处理方式</legend><div className="upscale-methods">{[{ name: "清晰增强", code: "DETAIL", description: "清晰度与细节优化" }, { name: "高清放大", code: "UPSCALE", description: "放大画面，保持比例" }].map((item) => <label key={item.name} htmlFor={`upscale-mode-${item.code}`}><input id={`upscale-mode-${item.code}`} aria-label={item.name} type="radio" name="enhance-mode" checked={mode === item.name} value={item.name} disabled={generating} onChange={() => { setMode(item.name); setResults({}); setNotice(""); }} /><span><small>{item.code}</small><strong>{item.name}</strong><em>{item.description}</em></span></label>)}</div></fieldset>
              <p>清晰增强侧重修复模糊和压缩痕迹；高清放大侧重提升输出像素并保守重建细节。</p>
          </section>

          <div className="template-credit" aria-live="polite"><span>预计消耗积分<small>{images.length ? `${images.length} 张 × 5 分` : "5 分 / 张"} · 当前不会扣费</small></span><strong>{Math.max(1, images.length) * 5}<i>分</i></strong></div>
          <button className="template-generate" type="button" disabled={!images.length || generating} aria-describedby="upscale-service-note" onClick={generate}><span>{generating ? "AI 正在处理…" : "转高清"}</span><em><Icon name="spark" /> ENHANCE</em></button>
          <p id="upscale-service-note" className="upscale-service-note">已连接 Seedream · 批量任务将逐张提交并显示结果</p>
          {notice && <p className="upscale-message" role="status">{notice}</p>}
          {selectedResult?.url && <a className="upscale-download" href={selectedResult.url} target="_blank" rel="noreferrer">打开并下载当前高清结果</a>}
          {selectedResult?.status === "failed" && <p className="upscale-message" role="alert">{selectedResult.error}</p>}
        </aside>
      </div>
    </main>
  );
}
