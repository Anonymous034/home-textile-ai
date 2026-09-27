"use client";

import { useEffect, useRef, useState } from "react";
import type { GenerateTask, InputParams, PlanDocument, PlanItem, ProductImage, WorkflowPhase } from "../detail-page/models";
import { initialInput, reorderPlan, templatePlan, terminalTask, validateInput, validatePlan } from "../detail-page/models";
import { detailApi, DetailApiError, resultUrl } from "../detail-page/api";
import "./DetailSuiteWorkflow.css";

const languages = { "zh-CN": "中文", en: "English", es: "西班牙语", fr: "法语", de: "德语", ja: "日语", ko: "韩语" };
const placements = { top: "顶部", center: "居中", bottom: "底部", left: "左侧", right: "右侧" };
const imageStates = { queued: "排队中", rendering: "正在生成", completed: "已完成", failed: "生成失败" };

function downloadJson(plan: PlanDocument) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(plan, null, 2)], { type: "application/json" }));
  const a = document.createElement("a"); a.href = url; a.download = "detail-plan.json"; a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function DetailSuiteWorkflow() {
  const [input, setInput] = useState<InputParams>(initialInput);
  const [images, setImages] = useState<ProductImage[]>([]);
  const [plan, setPlan] = useState<PlanDocument | null>(null);
  const [task, setTask] = useState<GenerateTask | null>(null);
  const [phase, setPhase] = useState<WorkflowPhase>("input");
  const [step, setStep] = useState(0);
  const [message, setMessage] = useState("");
  const [connection, setConnection] = useState("");
  const [pollId, setPollId] = useState("");
  const [pollEpoch, setPollEpoch] = useState(0);
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const urls = useRef(new Set<string>());
  const fileInput = useRef<HTMLInputElement>(null);
  const actionLock = useRef(false);
  const uploadLock = useRef(false);
  const [planInputs, setPlanInputs] = useState("");
  const busy = ["planning", "submitting", "rendering"].includes(phase) || uploading;
  const signature = JSON.stringify({ input, images: images.map(({ id, role }) => ({ id, role })) });
  const stale = !!plan && signature !== planInputs;
  const canPlan = !validateInput(input, images) && !busy;
  const settled = task?.items.filter((item) => ["completed", "failed"].includes(item.status)).length ?? 0;
  const completed = task?.items.filter((item) => item.status === "completed").length ?? 0;
  const progress = task?.items.length ? Math.round(settled / task.items.length * 100) : 0;
  const taskMatchesPlan = !!task && !!plan && task.planId === plan.planId && task.planRevision === plan.revision;

  useEffect(() => {
    const allUrls = urls.current;
    return () => allUrls.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  // A failed GET never re-submits the billable render POST.
  useEffect(() => {
    if (!pollId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function poll() {
      try {
        const next = await detailApi.task(pollId, controller.signal);
        if (stopped) return;
        setTask(next); setConnection("");
        if (terminalTask(next)) { setPhase("finished"); setPollId(""); return; }
        setPhase("rendering");
      } catch {
        if (stopped) return;
        setConnection("任务状态暂不可用，正在重新查询。请勿重复提交。");
      }
      if (!stopped) timer = setTimeout(poll, 3000);
    }
    void poll();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); };
  }, [pollId, pollEpoch]);

  function changeInput<K extends keyof InputParams>(key: K, value: InputParams[K]) {
    setInput((current) => ({ ...current, [key]: value })); setMessage("");
  }

  async function addImages(files: FileList | null) {
    if (!files || busy || uploadLock.current) return;
    uploadLock.current = true; setUploading(true);
    const accepted: ProductImage[] = [];
    let rejected = 0;
    for (const file of Array.from(files).slice(0, 12 - images.length)) {
      try {
        if (!["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > 20 * 1024 * 1024) throw new Error();
        const decoded = await createImageBitmap(file); decoded.close();
        const url = URL.createObjectURL(file); urls.current.add(url);
        accepted.push({ id: crypto.randomUUID(), file, previewUrl: url, name: file.name, role: images.length + accepted.length === 0 ? "main" : "detail" });
      } catch { rejected++; }
    }
    setImages((current) => [...current, ...accepted]);
    setMessage(rejected ? rejected + " 张图片无法读取或超过 20MB，其他素材已添加。" : files.length > 12 - images.length ? "最多保留 12 张产品素材。" : "");
    setUploading(false); uploadLock.current = false;
  }

  function removeImage(image: ProductImage) {
    URL.revokeObjectURL(image.previewUrl); urls.current.delete(image.previewUrl);
    setImages((current) => current.filter((item) => item.id !== image.id));
  }
  function editItems(items: PlanItem[]) {
    setPlan((current) => current && ({ ...current, revision: current.revision + 1, input: { ...current.input, imageCount: items.length }, items: items.map((item, index) => ({ ...item, order: index + 1 })) }));
    setMessage("");
  }
  function editItem(id: string, patch: Partial<PlanItem>) {
    if (plan) editItems(plan.items.map((item) => item.id === id ? { ...item, ...patch } : item));
  }
  function move(id: string, offset: number) {
    if (!plan) return;
    const index = plan.items.findIndex((item) => item.id === id);
    const target = plan.items[index + offset];
    if (target) editItems(reorderPlan(plan.items, id, target.id));
  }

  async function createPlan(example = false) {
    if (!canPlan || actionLock.current) return;
    actionLock.current = true; setPhase("planning"); setMessage("");
    try {
      let next: PlanDocument;
      if (example) next = templatePlan(input, images);
      else {
        const uploaded = await detailApi.upload(images); setImages(uploaded);
        next = await detailApi.plan(input, uploaded, crypto.randomUUID());
      }
      const error = validatePlan(next, images.map((image) => image.id));
      if (error) throw new Error(error);
      setPlanInputs(signature);
      setPlan(next); setTask(null); setStep(1); setPhase("review");
    } catch (error) { setMessage(error instanceof Error ? error.message : "策划方案生成失败。"); setPhase(plan ? "review" : "input"); }
    finally { actionLock.current = false; }
  }

  async function reviseItem(item: PlanItem) {
    if (!plan || busy || actionLock.current) return;
    actionLock.current = true; setPhase("planning"); setMessage("");
    try {
      const next = await detailApi.revise(plan, item);
      if (next.id !== item.id) throw new Error("服务返回了不匹配的卡片编号。");
      const error = validatePlan({ ...plan, items: plan.items.map((original) => original.id === item.id ? next : original) }, images.map((image) => image.id));
      if (error) throw new Error(error);
      editItem(item.id, next);
    } catch (error) { setMessage(error instanceof Error ? error.message : "单张策划调整失败。"); }
    finally { actionLock.current = false; setPhase("review"); }
  }

  async function render(item?: PlanItem) {
    if (!plan || busy || actionLock.current || stale) return;
    const error = validatePlan(plan, images.map((image) => image.id));
    if (error) { setMessage(error); return; }
    actionLock.current = true; setPhase("submitting"); setMessage("");
    const id = crypto.randomUUID();
    let submitted = false;
    try {
      let next: GenerateTask;
      if (item && task) { submitted = true; next = await detailApi.redraw(task.id, item, id); }
      else {
        const uploaded = await detailApi.upload(images); setImages(uploaded);
        submitted = true;
        next = await detailApi.render({ taskId: id, plan, input: { ...input, imageCount: plan.items.length }, assets: uploaded.map((image) => ({ id: image.id, assetId: image.assetId!, role: image.role })) });
      }
      setTask(next); setStep(2); setPhase(terminalTask(next) ? "finished" : "rendering");
      if (!terminalTask(next)) setPollId(next.id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "图片生成提交失败。");
      if (submitted && error instanceof DetailApiError && error.uncertain) {
        setConnection("提交结果尚未确认，正在按原任务编号查询。"); setTask(null); setPollId(id); setStep(2); setPhase("rendering");
      } else setPhase("review");
    } finally { actionLock.current = false; }
  }

  return <main className="detail-suite">
    <header className="ds-header"><a href="/dashboard?tool=detail-page">‹ <span>返回工作台</span></a><div className="ds-brand"><b>42</b><div><strong>DETAIL PAGE LAB</strong><small>商品详情页套件</small></div></div><span className="ds-header-tag">策划 → 审阅 → 出图</span></header>
    <div className="ds-layout">
      <aside className="ds-params" aria-label="参数配置区">
        <div className="ds-section-title"><span>INPUT / 01</span><h1>产品与生成参数</h1></div>
        <fieldset disabled={busy} className="ds-fields">
          <section className="ds-panel"><h2>产品素材 <small>{images.length}/12</small></h2><label className="ds-upload" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); void addImages(event.dataTransfer.files); }}><input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={(event) => { void addImages(event.target.files); event.target.value = ""; }} /><span>↑</span><strong>{uploading ? "正在读取素材…" : "上传或拖入产品图"}</strong><small>JPG / PNG / WEBP · 单张 ≤ 20MB</small></label>
            {images.length > 0 && <ul className="ds-assets">{images.map((image) => <li key={image.id}><img src={image.previewUrl} alt={image.name} /><div><span title={image.name}>{image.name}</span><select aria-label={image.name + " 素材类型"} value={image.role} onChange={(event) => setImages((current) => current.map((asset) => asset.id === image.id ? { ...asset, role: event.target.value as ProductImage["role"] } : asset))}><option value="main">主图</option><option value="detail">细节图</option><option value="scene">场景图</option></select></div><button type="button" aria-label={"移除 " + image.name} onClick={() => removeImage(image)}>×</button></li>)}</ul>}
          </section>
          <section className="ds-panel ds-form"><h2>产品信息</h2><label>产品名称 <em>必填</em><input value={input.productName} maxLength={120} onChange={(event) => changeInput("productName", event.target.value)} placeholder="例如：全棉色织四件套" required /></label>
            {([["fabric", "面料", "例如：100% 全棉"], ["craftsmanship", "工艺", "例如：色织、水洗工艺"], ["specifications", "尺寸规格", "例如：床单 245 × 250 cm"]] as const).map(([key, label, placeholder]) => <label key={key}>{label}<input value={input[key]} maxLength={500} onChange={(event) => changeInput(key, event.target.value)} placeholder={placeholder} /></label>)}
            <label>核心卖点<textarea value={input.sellingPoints} maxLength={1000} onChange={(event) => changeInput("sellingPoints", event.target.value)} placeholder="填写希望重点表达的卖点" /></label><label>补充说明<textarea value={input.notes} maxLength={1000} onChange={(event) => changeInput("notes", event.target.value)} placeholder="品牌风格、展示禁忌或其他要求" /></label>
          </section>
          <section className="ds-panel"><h2>生成设置</h2><div className="ds-form ds-grid-2"><label>目标语言<select value={input.language} onChange={(event) => changeInput("language", event.target.value as InputParams["language"])}>{Object.entries(languages).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>图片数量<select value={input.imageCount} onChange={(event) => changeInput("imageCount", Number(event.target.value))}>{[5, 6, 7, 8, 9, 10].map((value) => <option key={value} value={value}>{value} 张</option>)}</select></label><label>图片比例<select value={input.aspectRatio} onChange={(event) => changeInput("aspectRatio", event.target.value as InputParams["aspectRatio"])}>{["3:4", "16:9", "1:1"].map((value) => <option key={value}>{value}</option>)}</select></label><label>输出分辨率<select value={input.resolution} onChange={(event) => changeInput("resolution", event.target.value as InputParams["resolution"])}><option>2K</option><option>4K</option></select></label></div></section>
        </fieldset>
        <div className="ds-param-actions"><button className="ds-primary" disabled={!canPlan} onClick={() => void createPlan()}>{phase === "planning" ? "正在策划…" : plan ? "重新生成策划方案" : "生成策划方案"}<span>✧</span></button><button className="ds-example" disabled={!canPlan} onClick={() => void createPlan(true)}>使用本地示例方案</button><p>示例方案用于体验编辑流程，不包含 AI 分析。</p></div>
      </aside>
      <section className="ds-workflow" aria-label="工作流与预览区">
        <nav className="ds-steps" aria-label="生成步骤">{["参数输入", "审阅策划方案", "生成整套图片"].map((label, index) => <button key={label} aria-current={step === index ? "step" : undefined} disabled={(index === 1 && !plan) || (index === 2 && !task && !pollId) || (busy && index !== step)} onClick={() => setStep(index)}><b>{String(index + 1).padStart(2, "0")}</b><span>{label}</span></button>)}</nav>
        <div className="ds-workspace">
          {message && <p className="ds-alert" role="alert">{message}</p>}{connection && <p className="ds-alert" role="status">{connection} <button onClick={() => setPollEpoch((value) => value + 1)}>立即查询</button></p>}
          {stale && <p className="ds-alert">产品参数或素材已修改，请重新生成策划方案后再出图。</p>}
          {step === 0 && <div className="ds-input-view"><div className="ds-eyebrow">PRODUCT STORY / START</div><h2>先策划，再生成一整套详情页。</h2><p>填入产品信息，审阅每一张图的主题、画面与文案，再统一生成。</p><div className="ds-story-sequence">{["品牌首屏", "核心卖点", "材质工艺", "尺寸规格", "使用场景"].map((theme, index) => <div key={theme}><span>0{index + 1}</span><strong>{theme}</strong><i /></div>)}</div>{images.length > 0 ? <div className="ds-source-preview"><img src={images[0].previewUrl} alt="主素材预览，非生成结果" /><div><small>产品素材预览</small><h3>{input.productName || "填写产品名称"}</h3><p>{input.sellingPoints || "卖点与产品参数将成为策划依据。"}</p><span>{images.length} 张素材 · {input.imageCount} 张输出 · {input.aspectRatio} · {input.resolution}</span></div></div> : <button className="ds-empty-upload" onClick={() => fileInput.current?.click()} disabled={busy}><span>＋</span>添加产品素材</button>}</div>}
          {step === 1 && plan && <><div className="ds-workspace-heading"><div><span className="ds-eyebrow">PLAN / REVIEW</span><h2>审阅你的视觉脚本 <small>{plan.items.length} 张</small></h2><p>{plan.source === "template" ? "本地示例 · 请根据产品事实与目标语言调整文案" : "AI 策划 · 请核对产品信息与画面文案"}</p></div><button className="ds-quiet" onClick={() => downloadJson(plan)}>导出 JSON ↓</button></div>
            <div className="ds-plan-list">{plan.items.map((item, index) => <article className="ds-plan-card" key={item.id} onDragOver={(event) => { if (!busy && draggedId) event.preventDefault(); }} onDrop={(event) => { event.preventDefault(); if (!busy && draggedId) editItems(reorderPlan(plan.items, draggedId, item.id)); setDraggedId(null); }}><header><button className="ds-drag-handle" draggable={!busy} disabled={busy} aria-label={"拖动第 " + (index + 1) + " 张排序；也可使用上下移按钮"} onDragStart={(event) => { setDraggedId(item.id); event.dataTransfer.setData("text/plain", item.id); event.dataTransfer.effectAllowed = "move"; }} onDragEnd={() => setDraggedId(null)}>⠿</button><span className="ds-card-number">{String(index + 1).padStart(2, "0")}</span><input aria-label={"第 " + (index + 1) + " 张展示主题"} maxLength={120} value={item.theme} disabled={busy} onChange={(event) => editItem(item.id, { theme: event.target.value })} /><button aria-label={"上移第 " + (index + 1) + " 张"} disabled={busy || index === 0} onClick={() => move(item.id, -1)}>↑</button><button aria-label={"下移第 " + (index + 1) + " 张"} disabled={busy || index === plan.items.length - 1} onClick={() => move(item.id, 1)}>↓</button><button aria-label={"删除第 " + (index + 1) + " 张"} disabled={busy || plan.items.length === 1} onClick={() => editItems(plan.items.filter((other) => other.id !== item.id))}>×</button></header>
              <fieldset disabled={busy} className="ds-card-fields"><div className="ds-form"><label>画面描述 <small>VISUAL DESCRIPTION</small><textarea id={"visual-" + item.id} value={item.visualDescription} maxLength={2000} onChange={(event) => editItem(item.id, { visualDescription: event.target.value })} /></label><label>视觉风格<input value={item.stylePrompt} maxLength={1000} onChange={(event) => editItem(item.id, { stylePrompt: event.target.value })} /></label></div><div className="ds-form"><label>画面文案 <small>TEXT OVERLAY</small><input aria-label={"第 " + (index + 1) + " 张文案标题"} value={item.textOverlay.headline} maxLength={200} placeholder="标题" onChange={(event) => editItem(item.id, { textOverlay: { ...item.textOverlay, headline: event.target.value } })} /><textarea aria-label={"第 " + (index + 1) + " 张文案正文"} value={item.textOverlay.body} maxLength={1000} placeholder="正文，可留空" onChange={(event) => editItem(item.id, { textOverlay: { ...item.textOverlay, body: event.target.value } })} /></label><label>文案挂载点<select value={item.textOverlay.placement} onChange={(event) => editItem(item.id, { textOverlay: { ...item.textOverlay, placement: event.target.value as PlanItem["textOverlay"]["placement"] } })}>{Object.entries(placements).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div></fieldset>
              <div className="ds-card-sources"><span>参考素材</span>{images.map((image, sourceIndex) => <label key={image.id}><input type="checkbox" checked={item.sourceImageIds.includes(image.id)} disabled={busy} onChange={(event) => editItem(item.id, { sourceImageIds: event.target.checked ? [...item.sourceImageIds, image.id] : item.sourceImageIds.filter((id) => id !== image.id) })} />图 {sourceIndex + 1}</label>)}</div><footer><span>Card #{index + 1}</span><button disabled={busy || stale} onClick={() => void reviseItem(item)}>✧ AI 重新策划</button><button disabled={busy} onClick={() => document.getElementById("visual-" + item.id)?.focus()}>单张调整 ↗</button></footer>
            </article>)}</div>
            <button className="ds-add-card" disabled={busy || stale || plan.items.length >= 10} onClick={() => { const example = templatePlan({ ...input, imageCount: 1 }, images).items[0]; editItems([...plan.items, { ...example, theme: "新增画面", visualDescription: "", textOverlay: { headline: "", body: "", placement: "bottom" } }]); }}>＋ 添加图片卡片 <small>最多 10 张</small></button>
          </>}
          {step === 2 && <><div className="ds-workspace-heading"><div><span className="ds-eyebrow">RENDER / OUTPUT</span><h2>{task && terminalTask(task) ? task.status === "completed" ? "整套图片已完成" : "生成结束，请检查结果" : "正在生成整套图片"}</h2><p>已完成 {completed} / {task?.items.length ?? plan?.items.length ?? 0} 张{task && !taskMatchesPlan ? " · 此处为上一版方案结果" : ""}</p></div>{resultUrl(task?.exportUrl) && <a className="ds-quiet" href={resultUrl(task?.exportUrl)} download>导出整套 ZIP ↓</a>}</div><div className="ds-progress" role="progressbar" aria-label="任务处理进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><i style={{ width: progress + "%" }} /></div><p className="ds-progress-caption">{progress}% 已处理 · 进度依据已成功或失败的图片数量</p>
            <div className="ds-results">{(task?.items ?? []).map((result, index) => { const item = plan?.items.find((entry) => entry.id === result.planItemId); return <article key={result.planItemId}><div className="ds-result-image" style={{ aspectRatio: (plan?.input.aspectRatio ?? input.aspectRatio).replace(":", "/") }}>{result.status === "completed" && resultUrl(result.previewUrl) ? <img src={resultUrl(result.previewUrl)} alt={"生成结果 " + (index + 1) + "：" + (item?.theme || "详情页图片")} /> : <span>{imageStates[result.status]}</span>}</div><h3>{String(index + 1).padStart(2, "0")} / {item?.theme || "详情页图片"}</h3><p>{result.error?.message || imageStates[result.status]}</p><div>{resultUrl(result.downloadUrl) && <a href={resultUrl(result.downloadUrl)} download>下载原图</a>}<button disabled={busy || !item || !taskMatchesPlan || stale} onClick={() => item && void render(item)}>单图重绘</button></div></article>; })}</div>{!task && <p className="ds-progress-caption">正在等待服务确认任务编号：{pollId || "提交中"}</p>}</>}
        </div>
        <footer className="ds-workflow-footer"><span>{plan ? plan.items.length + " 张图片 · 方案 v" + plan.revision : "填写左侧参数，开始策划"}</span>{step === 1 && <button className="ds-primary" disabled={busy || stale || !plan || !!validatePlan(plan, images.map((image) => image.id))} onClick={() => void render()}>确认方案，生成整套图片 →</button>}{step === 2 && !busy && <button className="ds-quiet" onClick={() => setStep(1)}>返回编辑方案</button>}</footer>
      </section>
    </div>
  </main>;
}
