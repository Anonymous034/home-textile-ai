"use client";

import { ChangeEvent, CSSProperties, DragEvent, useEffect, useRef, useState } from "react";
import "./TemplateLab.css";

type UploadSlot = "hero" | "extraOne" | "extraTwo";
type UploadedImage = { name: string; url: string; file: File };
type LibraryCategory = { id: string; name: string; template_count: number };
type LibraryPreview = { id: string; url: string };
type LibraryTemplate = { id: string; name: string; image_count: number; category_id: string; category_name: string; previews: LibraryPreview[] };
type LibraryImage = { id: string; slot: number; thumbnail_url: string; image_url: string };
type TemplateDetail = LibraryTemplate & { images: LibraryImage[] };
type SelectedLibraryImage = { id: string; templateId: string; templateName: string; imageUrl: string; thumbnailUrl: string };
type StaticCatalog = { categories: LibraryCategory[]; templates: TemplateDetail[] };
type AiConnection = { connected: boolean; message?: string; error_code?: string | null; checked_at?: string | null };
type AiConnections = { replicate_image: AiConnection; template_plan: AiConnection };

const API = (process.env.NEXT_PUBLIC_STUDIO_API ?? "").replace(/\/+$/, "");
const fallbackTemplate = { id: "soft-bedroom", name: "柔光卧室", image: "/bento-gallery/template.png", tone: "奶油暖调" };
const assetUrl = (path: string) => path.startsWith("http") || path.startsWith("/template-library/") ? path : `${API}${path}`;

function Icon({ name }: { name: "back" | "upload" | "template" | "chevron" | "spark" | "image" | "close" | "check" }) {
  const paths = {
    back: <path d="m15 18-6-6 6-6" />,
    upload: <><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5"/><path d="M5 15v4h14v-4"/></>,
    template: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 4v16M8 10h13"/></>,
    chevron: <path d="m8 10 4 4 4-4" />,
    spark: <><path d="m12 3 1.35 4.15L17.5 8.5l-4.15 1.35L12 14l-1.35-4.15L6.5 8.5l4.15-1.35L12 3Z"/><path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z"/></>,
    image: <><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 15-5-5L5 20"/></>,
    close: <path d="m7 7 10 10M17 7 7 17" />,
    check: <path d="m5 12 4 4L19 6" />,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

export default function TemplateLab() {
  const fileRefs = useRef<Record<UploadSlot, HTMLInputElement | null>>({ hero: null, extraOne: null, extraTwo: null });
  const templateFileRef = useRef<HTMLInputElement>(null);
  const objectUrls = useRef<string[]>([]);
  const [images, setImages] = useState<Partial<Record<UploadSlot, UploadedImage>>>({});
  const [templateOpen, setTemplateOpen] = useState(false);
  const [categories, setCategories] = useState<LibraryCategory[]>([]);
  const [activeCategory, setActiveCategory] = useState("");
  const [libraryTemplates, setLibraryTemplates] = useState<LibraryTemplate[]>([]);
  const [detailTemplate, setDetailTemplate] = useState<TemplateDetail | null>(null);
  const [confirmedSelection, setConfirmedSelection] = useState<SelectedLibraryImage[]>([]);
  const [draftSelection, setDraftSelection] = useState<SelectedLibraryImage[]>([]);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [libraryError, setLibraryError] = useState("");
  const [staticCatalog, setStaticCatalog] = useState<StaticCatalog | null>(null);
  const [note, setNote] = useState("");
  const [ratio, setRatio] = useState("9:16");
  const [resolution, setResolution] = useState("1K");
  const [dragSlot, setDragSlot] = useState<UploadSlot | null>(null);
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [generated, setGenerated] = useState(false);
  const [templateUpload, setTemplateUpload] = useState<UploadedImage | null>(null);
  const [resultUrl, setResultUrl] = useState("");
  const [strategy, setStrategy] = useState<object | null>(null);
  const [generationError, setGenerationError] = useState("");
  const [aiConnections, setAiConnections] = useState<AiConnections | null>(null);

  const imageConnected = aiConnections?.replicate_image.connected ?? false;
  const planConnected = aiConnections?.template_plan.connected ?? false;
  const aiReady = imageConnected && planConnected;

  useEffect(() => {
    let active = true;
    let streamOpen = false;
    const readStatus = async () => {
      try {
        const response = await fetch(`${API}/api/ai/connections`, { cache: "no-store" });
        if (!response.ok) throw new Error("连接状态不可用");
        const state = await response.json() as AiConnections;
        if (active) setAiConnections(state);
      } catch {
        if (active) setAiConnections(null);
      }
    };
    const stream = new EventSource(`${API}/api/ai/connections/stream`);
    stream.onopen = () => { streamOpen = true; };
    stream.onmessage = (event) => {
      try { if (active) setAiConnections(JSON.parse(event.data) as AiConnections); }
      catch { streamOpen = false; }
    };
    stream.onerror = () => { streamOpen = false; void readStatus(); };
    void readStatus();
    const fallback = window.setInterval(() => { if (!streamOpen) void readStatus(); }, 5000);
    return () => { active = false; stream.close(); window.clearInterval(fallback); };
  }, []);

  const selectedTemplate = templateUpload
    ? { id: "uploaded-template", name: templateUpload.name, image: templateUpload.url, tone: "用户上传模板" }
    : confirmedSelection[0]
    ? { id: confirmedSelection[0].id, name: confirmedSelection[0].templateName, image: confirmedSelection[0].imageUrl, tone: `已选 ${confirmedSelection.length} 张参考图` }
    : fallbackTemplate;
  const selectedTemplateCount = new Set(confirmedSelection.map((item) => item.templateId)).size;

  useEffect(() => () => objectUrls.current.forEach((url) => URL.revokeObjectURL(url)), []);
  useEffect(() => {
    if (!templateOpen || categories.length) return;
    const abort = new AbortController();
    setLibraryLoading(true);
    fetch(`${API}/api/template-library/categories`, { cache: "no-store", signal: abort.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json(); })
      .then((payload: { items: LibraryCategory[] }) => {
        setCategories(payload.items);
        setActiveCategory((current) => current || payload.items[0]?.id || "");
        setLibraryError("");
      })
      .catch(async (error) => {
        if (error.name === "AbortError") return;
        try {
          const response = await fetch("/template-library/catalog.json", { cache: "no-store", signal: abort.signal });
          if (!response.ok) throw new Error();
          const catalog = await response.json() as StaticCatalog;
          setStaticCatalog(catalog);
          setCategories(catalog.categories);
          setActiveCategory((current) => current || catalog.categories[0]?.id || "");
          setLibraryError("");
        } catch { setLibraryError("模板资料库暂时无法连接，请确认本地文件完整。"); }
      })
      .finally(() => setLibraryLoading(false));
    return () => abort.abort();
  }, [templateOpen, categories.length]);

  useEffect(() => {
    if (!templateOpen || !activeCategory) return;
    if (staticCatalog) {
      setDetailTemplate(null);
      setLibraryTemplates(staticCatalog.templates.filter((item) => item.category_id === activeCategory));
      setLibraryLoading(false);
      setLibraryError("");
      return;
    }
    const abort = new AbortController();
    setLibraryLoading(true);
    setDetailTemplate(null);
    fetch(`${API}/api/template-library/templates?category=${encodeURIComponent(activeCategory)}`, { cache: "no-store", signal: abort.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json(); })
      .then((payload: { items: LibraryTemplate[] }) => { setLibraryTemplates(payload.items); setLibraryError(""); })
      .catch((error) => { if (error.name !== "AbortError") setLibraryError("这个分类加载失败，请稍后重试。"); })
      .finally(() => setLibraryLoading(false));
    return () => abort.abort();
  }, [templateOpen, activeCategory, staticCatalog]);

  useEffect(() => {
    if (!templateOpen) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setTemplateOpen(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [templateOpen]);

  useEffect(() => {
    if (!templateOpen) return;
    const modal = document.querySelector<HTMLElement>(".template-library-modal");
    if (!modal) return;
    const scrollPane = (event: globalThis.WheelEvent) => {
      const target = event.target as HTMLElement | null;
      const pane = target?.closest<HTMLElement>(".template-pack-grid, .template-image-grid, .template-category-list");
      if (!pane || pane.scrollHeight <= pane.clientHeight || event.deltaY === 0) return;
      event.preventDefault();
      pane.scrollTop += event.deltaY;
    };
    modal.addEventListener("wheel", scrollPane, { passive: false });
    return () => modal.removeEventListener("wheel", scrollPane);
  }, [templateOpen]);

  const addImage = (slot: UploadSlot, files: FileList | null) => {
    const file = files?.[0];
    if (!file || !file.type.startsWith("image/")) return;
    const url = URL.createObjectURL(file);
    objectUrls.current.push(url);
    setImages((current) => ({ ...current, [slot]: { name: file.name, url, file } }));
    setGenerated(false); setResultUrl(""); setStrategy(null); setGenerationError("");
  };
  const addTemplateImage = (files: FileList | null) => {
    const file = files?.[0];
    if (!file || !file.type.startsWith("image/") || file.size > 20 * 1024 * 1024) { setGenerationError("模板图必须是 20MB 以内的有效图片。"); return; }
    const url = URL.createObjectURL(file); objectUrls.current.push(url);
    setTemplateUpload({ name: file.name, url, file }); setConfirmedSelection([]); setResultUrl(""); setGenerated(false); setGenerationError("");
  };
  const chooseImage = (slot: UploadSlot, event: ChangeEvent<HTMLInputElement>) => { addImage(slot, event.target.files); event.target.value = ""; };
  const dropImage = (slot: UploadSlot, event: DragEvent<HTMLLabelElement>) => { event.preventDefault(); setDragSlot(null); addImage(slot, event.dataTransfer.files); };
  const openTemplatePicker = () => { setDraftSelection(confirmedSelection); setDetailTemplate(null); setTemplateOpen(true); };
  const openTemplateDetail = async (template: LibraryTemplate) => {
    const localTemplate = staticCatalog?.templates.find((item) => item.id === template.id);
    if (localTemplate) { setDetailTemplate(localTemplate); setLibraryError(""); return; }
    setLibraryLoading(true);
    try {
      const response = await fetch(`${API}/api/template-library/templates/${encodeURIComponent(template.id)}`, { cache: "no-store" });
      if (!response.ok) throw new Error();
      setDetailTemplate(await response.json() as TemplateDetail);
      setLibraryError("");
    } catch { setLibraryError("模板图片加载失败，请稍后重试。"); }
    finally { setLibraryLoading(false); }
  };
  const toggleLibraryImage = (template: TemplateDetail, image: LibraryImage) => {
    setDraftSelection((current) => current.some((item) => item.id === image.id)
      ? current.filter((item) => item.id !== image.id)
      : [...current, { id: image.id, templateId: template.id, templateName: template.name, imageUrl: assetUrl(image.image_url), thumbnailUrl: assetUrl(image.thumbnail_url) }]);
  };
  const confirmTemplates = () => { setConfirmedSelection(draftSelection); setTemplateUpload(null); setGenerated(false); setResultUrl(""); setTemplateOpen(false); };
  const generate = async () => {
    if (!images.hero || generating) return;
    setGenerating(true); setGenerated(false); setProgress(18); setGenerationError(""); setStrategy(null); setResultUrl("");
    try {
      const form = new FormData();
      ([images.hero, images.extraOne, images.extraTwo].filter(Boolean) as UploadedImage[]).forEach((item) => form.append("product_images", item.file, item.name));
      if (templateUpload) {
        form.append("template_image", templateUpload.file, templateUpload.name);
      } else if (confirmedSelection.length) {
        confirmedSelection.forEach((item) => form.append("template_image_ids", item.id));
      } else {
        const response = await fetch(selectedTemplate.image);
        if (!response.ok) throw new Error("无法读取所选模板图片。");
        const blob = await response.blob();
        form.append("template_image", new File([blob], "template.png", { type: blob.type || "image/png" }));
      }
      form.append("requirement", note.trim()); form.append("aspect_ratio", ratio); form.append("resolution", resolution);
      setProgress(40);
      const response = await fetch(`${API}/api/template-compose/generate`, { method: "POST", body: form, signal: AbortSignal.timeout(360000) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "模板融合失败。");
      setProgress(100); setStrategy(data.strategy); setResultUrl(`${API}${data.result_url}?v=${Date.now()}`); setGenerated(true);
    } catch (reason) {
      setGenerationError(reason instanceof Error ? reason.message : "模板融合失败，请稍后重试。");
    } finally { setGenerating(false); }
  };

  const slotCopy: Record<UploadSlot, { title: string; sub: string; required?: boolean }> = {
    hero: { title: "主视角", sub: "必填 · 产品正面图", required: true },
    extraOne: { title: "补充视角", sub: "选填 · 细节或侧面" },
    extraTwo: { title: "补充视角", sub: "选填 · 场景或材质" },
  };

  return (
    <main className="template-lab">
      <header className="template-hud"><a href="/dashboard?tool=template" className="template-back"><Icon name="back"/><span>返回</span></a><div className="template-brand"><img src="/brand-logo.jpg" alt="" /><div><strong>TEMPLATE COMPOSER</strong><small>AI 模板复用控制台</small></div></div><div className={`template-status${aiReady ? "" : " is-offline"}`} role="status"><i/><span>{aiReady ? "AI 已连接" : "AI 检查 / 重连中"}</span><b>图片 {imageConnected ? "已连接" : "未连接"} · 策划 {planConnected ? "已连接" : "未连接"}</b></div></header>
      <div className="template-layout">
        <section className="template-canvas" aria-label="模板合成画布">
          <div className="template-toolbar"><div><span>按住 Ctrl 多选</span><i/><span>双击查看详情</span><i/><span>拖拽框选</span></div><button type="button" onClick={() => fileRefs.current.hero?.click()}><Icon name="upload"/>导入到画布</button></div>
          <div className={`template-stage ${generating ? "is-generating" : ""} ${generated ? "has-result" : ""}`}><span className="template-grid-glow"/><div className="template-stage-corners"><i/><i/><i/><i/></div>{!images.hero ? <div className="template-empty"><div className="template-orbit"><Icon name="template"/><i/><i/></div><span>TEMPLATE COMPOSITION NODE / READY</span><p>自动识别主体轮廓与材质，将产品精准融入所选模板，保持光影、比例和视觉层级一致。</p><button type="button" onClick={() => fileRefs.current.hero?.click()}><Icon name="upload"/>开始导入产品</button></div> : <div className="template-result"><div className="result-meta"><span>{resultUrl ? "AI COMPOSITE RESULT" : "COMPOSITION PREVIEW"}</span><strong>{selectedTemplate.name}</strong><small>{selectedTemplate.tone} · {ratio} · {resolution}</small></div><div className="result-board" style={{ "--result-ratio": ratio.replace(":", " / ") } as CSSProperties}>{resultUrl ? <img className="template-final-result" src={resultUrl} alt="AI 模板融合结果"/> : <><img className="result-template" src={selectedTemplate.image} alt="所选模板预览"/><img className="result-product" src={images.hero.url} alt="产品主视角预览"/><span>AI COMPOSITE PREVIEW</span></>}</div><div className="result-nodes"><i/><i/><i/><i/></div></div>}{generating && <div className="template-render"><i/><strong>{progress}%</strong><span>正在分析产品与模板并生成融合结果</span></div>}{generated && <div className="template-complete"><Icon name="spark"/> AI 模板图片已生成</div>}</div>
          <footer className="template-footer"><span><i/> CANVAS READY</span><b>{selectedTemplate.name.toUpperCase()} · {ratio} · {resolution}</b></footer>
        </section>
        <aside className="template-panel">
          <div className="template-panel-title"><span><i><Icon name="template"/></i><strong>使用模板</strong></span></div>
          <section className="template-card product-card"><header><div><span>01</span><strong>产品图片</strong></div><em>PRODUCT INPUT</em></header><p>选择要重点展示的商品主图。</p><div className="template-upload-row">{(Object.keys(slotCopy) as UploadSlot[]).map((slot) => <label className={`${images[slot] ? "has-image" : ""} ${dragSlot === slot ? "is-dragging" : ""}`} key={slot} onDragEnter={() => setDragSlot(slot)} onDragLeave={() => setDragSlot(null)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => dropImage(slot, event)}><input ref={(node) => { fileRefs.current[slot] = node; }} type="file" accept="image/*" onChange={(event) => chooseImage(slot, event)}/>{images[slot] ? <img src={images[slot]?.url} alt={slotCopy[slot].title}/> : <Icon name="upload"/>}<strong>{slotCopy[slot].title}{slotCopy[slot].required && <b>*</b>}</strong><small>{images[slot]?.name || slotCopy[slot].sub}</small></label>)}</div></section>
          <section className="template-card template-picker-card"><header><div><span>02</span><strong>装饰模板图</strong></div><em>STYLE MATRIX</em></header><input ref={templateFileRef} className="template-direct-file" type="file" accept="image/jpeg,image/png,image/webp" tabIndex={-1} onChange={(event) => { addTemplateImage(event.target.files); event.target.value = ""; }}/><button className="selected-template" type="button" onClick={openTemplatePicker}><span><strong>{selectedTemplate.name}</strong><small>{templateUpload ? "用户上传 · 作为环境与构图骨架" : confirmedSelection.length ? `${selectedTemplateCount} 个模板 · ${confirmedSelection.length} 张图片` : selectedTemplate.tone}</small></span><em>选择模板库</em></button><button className="template-direct-upload" type="button" onClick={() => templateFileRef.current?.click()}><Icon name="upload"/>{templateUpload ? "更换上传模板" : "上传自己的模板图"}</button></section>
          <label className="template-note"><span>补充说明 <i>选填</i></span><textarea value={note} maxLength={180} onChange={(event) => setNote(event.target.value)} placeholder="例如：保持米白背景，突出面料纹理…"/><small>{note.length}/180</small></label>
          <section className="template-specs"><label><span>图片比例</span><select value={ratio} onChange={(event) => setRatio(event.target.value)}><option>9:16</option><option>3:4</option><option>1:1</option><option>4:3</option></select></label><label><span>分辨率</span><select value={resolution} onChange={(event) => setResolution(event.target.value)}><option>1K</option><option>2K</option><option>4K</option></select></label></section>
          <div className="template-credit"><span>预计消耗积分<small>单次模板合成</small></span><strong>8<i>分</i></strong></div><button className="template-generate" type="button" disabled={!images.hero || generating || !aiReady} onClick={generate}><span>{generating ? `AI 生成中 ${progress}%` : generated ? "重新生成" : "立即生成"}</span><em><Icon name="spark"/> GENERATE</em></button>{aiConnections && !aiReady && <p className="template-connection-note" role="status">{!imageConnected ? `图片服务：${aiConnections.replicate_image.message ?? "正在重连"} ` : ""}{!planConnected ? `策划服务：${aiConnections.template_plan.message ?? "正在重连"}` : ""}</p>}{generationError && <p className="template-ai-message" role="alert">{generationError}</p>}{strategy && <details className="template-strategy"><summary>查看本次 AI 构图策略</summary><pre>{JSON.stringify(strategy, null, 2)}</pre></details>}{resultUrl && <a className="template-result-download" href={resultUrl} target="_blank" rel="noreferrer">打开并下载生成结果</a>}
        </aside>
      </div>
      {templateOpen && <div className="template-modal" role="dialog" aria-modal="true" aria-label="选择模板" onClick={() => setTemplateOpen(false)}><div className="template-modal-card template-library-modal" onClick={(event) => event.stopPropagation()}><header><div><span>TEMPLATE LIBRARY / 03</span><h2>选择模板</h2><p>按分类浏览模板，进入模板后可勾选多张参考图。</p></div><button type="button" onClick={() => setTemplateOpen(false)} aria-label="关闭模板选择"><Icon name="close"/></button></header><div className="template-library-layout"><aside className="template-category-list" aria-label="模板分类"><strong>模板分类</strong>{categories.map((category) => <button key={category.id} type="button" className={activeCategory === category.id ? "is-active" : ""} onClick={() => setActiveCategory(category.id)}><span>{category.name}</span><small>{category.template_count}</small></button>)}</aside><section className="template-library-content"><div className="template-library-toolbar"><div>{detailTemplate ? <button type="button" onClick={() => setDetailTemplate(null)}><Icon name="back"/>返回模板</button> : <><strong>{categories.find((item) => item.id === activeCategory)?.name || "模板"}</strong><small>{libraryTemplates.length} 个模板</small></>}</div><span>已选 <b>{draftSelection.length}</b> 张</span></div>{libraryError && <div className="template-library-state is-error">{libraryError}</div>}{!libraryError && libraryLoading && <div className="template-library-state">正在读取模板资料库…</div>}{!libraryError && !libraryLoading && !detailTemplate && <div className="template-pack-grid">{libraryTemplates.map((item) => { const selected = draftSelection.filter((value) => value.templateId === item.id).length; return <button type="button" className="template-pack" key={item.id} onClick={() => openTemplateDetail(item)}><span className="template-pack-mosaic">{item.previews.map((preview) => <img key={preview.id} src={assetUrl(preview.url)} alt=""/>)}{selected > 0 && <b><Icon name="check"/>{selected}</b>}</span><span className="template-pack-copy"><strong>{item.name}</strong><small>{item.image_count} 张图片</small></span></button>; })}</div>}{!libraryError && !libraryLoading && detailTemplate && <div className="template-image-browser"><header><div><strong>{detailTemplate.name}</strong><small>{detailTemplate.category_name} · {detailTemplate.image_count} 张图片</small></div><span>点击图片勾选，可跨模板多选</span></header><div className="template-image-grid">{detailTemplate.images.map((item) => { const selected = draftSelection.some((value) => value.id === item.id); return <button type="button" key={item.id} className={selected ? "is-selected" : ""} onClick={() => toggleLibraryImage(detailTemplate, item)} aria-pressed={selected}><img src={assetUrl(item.thumbnail_url)} alt={`${detailTemplate.name} 第 ${item.slot + 1} 张`}/><i>{selected ? <Icon name="check"/> : item.slot + 1}</i></button>; })}</div></div>}</section></div><footer className="template-library-footer"><div>{draftSelection.length ? <><strong>已选择 {draftSelection.length} 张图片</strong><span>来自 {new Set(draftSelection.map((item) => item.templateId)).size} 个模板</span></> : <span>请选择至少一张模板图片</span>}</div><button type="button" className="template-library-cancel" onClick={() => setTemplateOpen(false)}>取消</button><button type="button" className="template-library-confirm" disabled={!draftSelection.length} onClick={confirmTemplates}><Icon name="check"/>确认使用</button></footer></div></div>}
    </main>
  );
}
