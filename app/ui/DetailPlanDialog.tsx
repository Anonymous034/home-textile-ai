"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { detailApi, DetailApiError, resultUrl } from "../detail-page/api";
import { reorderPlan, terminalTask, validatePlan } from "../detail-page/models";
import type { GenerateTask, InputParams, PlanDocument, PlanItem, ProductImage } from "../detail-page/models";
import "./DetailPlanDialog.css";

export interface DetailSnapshot { input: InputParams; images: ProductImage[] }
type Phase = "idle" | "planning" | "review" | "submitting" | "rendering" | "finished" | "error" | "unknown";
const placements = { top: "顶部", center: "居中", bottom: "底部", left: "左侧", right: "右侧" };
const statuses = { queued: "排队中", rendering: "生成中", completed: "已完成", failed: "失败" };

/** Mounted with an immutable input snapshot; only explicit confirmation submits images. */
export default function DetailPlanDialog({ open, snapshot, onClose, onResult }: {
  open: boolean; snapshot: DetailSnapshot; onClose: () => void;
  onResult: (task: GenerateTask, plan: PlanDocument) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const lock = useRef(false);
  const started = useRef(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [plan, setPlan] = useState<PlanDocument | null>(null);
  const [task, setTask] = useState<GenerateTask | null>(null);
  const [assets, setAssets] = useState(snapshot.images);
  const [message, setMessage] = useState("");
  const [planPollId, setPlanPollId] = useState("");
  const [taskPollId, setTaskPollId] = useState("");
  const [recovery, setRecovery] = useState<{ kind: "plan" | "task"; id: string } | null>(null);
  const [dragged, setDragged] = useState("");
  const busy = ["idle", "planning", "submitting", "rendering"].includes(phase);
  const rendering = phase === "submitting" || phase === "rendering" || phase === "finished";
  const settled = task?.items.filter((item) => ["completed", "failed"].includes(item.status)).length ?? 0;
  const completed = task?.items.filter((item) => item.status === "completed").length ?? 0;
  const progress = task?.items.length ? Math.round(100 * settled / task.items.length) : 0;

  const acceptPlan = useCallback((next: PlanDocument) => {
    const problem = validatePlan(next, snapshot.images.map((image) => image.id));
    if (problem) throw new Error(problem);
    if (next.source !== "ai") throw new Error("策划服务没有返回 AI 方案，未进入图片生成。请检查模型配置。");
    if (JSON.stringify(next.input) !== JSON.stringify(snapshot.input)) {
      // Compare values without depending on JSON object key order.
      if (Object.entries(snapshot.input).some(([key, value]) => next.input[key as keyof InputParams] !== value)) throw new Error("AI 方案与当前产品参数不一致，请重新策划。");
    }
    setPlan(next); setPhase("review"); setMessage("");
  }, [snapshot]);

  const createPlan = useCallback(async () => {
    if (lock.current) return;
    lock.current = true;
    setPhase("planning"); setMessage("");
    const key = crypto.randomUUID();
    let submitted = false;
    try {
      const uploaded = await detailApi.upload(snapshot.images);
      setAssets(uploaded); submitted = true;
      acceptPlan(await detailApi.plan(snapshot.input, uploaded, key));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "方案生成失败。");
      if (submitted && error instanceof DetailApiError && error.uncertain) setPlanPollId(key);
      else setPhase("error");
    } finally { lock.current = false; }
  }, [snapshot, acceptPlan]);

  useEffect(() => {
    if (open && !dialog.current?.open) dialog.current?.showModal();
    if (!open && dialog.current?.open) dialog.current.close();
    if (open && !started.current) { started.current = true; void createPlan(); }
  }, [open, createPlan]);

  useEffect(() => {
    if (!busy) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [busy]);

  // Polling never repeats a billable POST, even after network errors.
  useEffect(() => {
    if (!planPollId && !taskPollId) return;
    let stopped = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function poll() {
      try {
        if (planPollId) {
          const result = await detailApi.planStatus(planPollId, controller.signal);
          if (stopped) return;
          failures = 0;
          if (result.state === "completed" && result.plan) { acceptPlan(result.plan); setPlanPollId(""); return; }
          if (result.state === "failed") { setMessage(result.message || "策划失败，请检查配置后重试。"); setPhase("error"); setPlanPollId(""); return; }
          setMessage("策划请求已收到，正在等待 AI 返回文字方案；不会重复提交。");
        } else {
          const next = await detailApi.task(taskPollId, controller.signal);
          if (stopped) return;
          failures = 0;
          setTask(next); setMessage("");
          if (terminalTask(next)) {
            setTaskPollId(""); setPhase("finished");
            if (plan) onResult(next, plan);
            return;
          }
        }
      } catch (error) {
        if (stopped) return;
        setMessage(`${error instanceof Error ? error.message : "状态查询失败。"} 正在按原编号查询，不会重复生成。`);
        if (++failures >= 5) {
          setRecovery({ kind: planPollId ? "plan" : "task", id: planPollId || taskPollId });
          setPlanPollId(""); setTaskPollId(""); setPhase("unknown");
          setMessage("连续查询失败，已暂停自动查询。原请求可能仍在处理，请恢复连接后查询原编号；不要重新创建任务，以免重复计费。");
          return;
        }
      }
      if (!stopped) timer = setTimeout(poll, 3000);
    }
    void poll();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); };
  }, [planPollId, taskPollId, acceptPlan, plan, onResult]);

  function editItems(items: PlanItem[]) {
    if (busy) return;
    setMessage("");
    setPlan((current) => current && ({ ...current, revision: current.revision + 1,
      input: { ...current.input, imageCount: items.length }, items: items.map((item, index) => ({ ...item, order: index + 1 })) }));
  }
  function editItem(id: string, patch: Partial<PlanItem>) {
    if (plan) editItems(plan.items.map((item) => item.id === id ? { ...item, ...patch } : item));
  }
  function move(item: PlanItem, offset: number) {
    if (!plan) return;
    const target = plan.items[plan.items.indexOf(item) + offset];
    if (target) editItems(reorderPlan(plan.items, item.id, target.id));
  }
  async function confirm() {
    if (!plan || busy || lock.current) return;
    const problem = validatePlan(plan, assets.map((image) => image.id));
    if (problem) { setMessage(problem); return; }
    lock.current = true; setPhase("submitting"); setMessage("");
    const taskId = crypto.randomUUID();
    try {
      const next = await detailApi.render({ taskId, plan, input: plan.input,
        assets: assets.map((image) => ({ id: image.id, assetId: image.assetId!, role: image.role })) });
      setTask(next);
      setPhase(terminalTask(next) ? "finished" : "rendering");
      if (terminalTask(next)) onResult(next, plan);
      else setTaskPollId(taskId);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "提交失败。");
      if (error instanceof DetailApiError && error.uncertain) { setPhase("rendering"); setTaskPollId(taskId); }
      else setPhase("review");
    } finally { lock.current = false; }
  }

  return <dialog className="detail-plan-dialog" ref={dialog} aria-labelledby="detail-plan-title" onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <header className="dp-heading"><div><small>DETAIL PAGE / {rendering ? "RENDER" : "PLAN REVIEW"}</small><h2 id="detail-plan-title">{phase === "unknown" ? "请求状态待确认" : rendering ? "生成整套详情图" : "确认详情页文字方案"}</h2></div><button type="button" aria-label="关闭方案弹窗" disabled={busy} onClick={onClose}>×</button></header>
    <nav className="dp-steps" aria-label="生成步骤"><span aria-current={!rendering ? "step" : undefined}>01 · AI 策划与手动修改</span><i>→</i><span aria-current={rendering ? "step" : undefined}>02 · 确认后生成图片</span></nav>
    <div className="dp-body">
      {message && <p className="dp-message" role="alert">{message}</p>}
      {phase === "unknown" && recovery && <div className="dp-loading"><h3>暂时无法确认请求状态</h3><p>原请求编号：{recovery.id}</p><button type="button" onClick={() => { setMessage(""); if (recovery.kind === "plan") { setPhase("planning"); setPlanPollId(recovery.id); } else { setPhase("rendering"); setTaskPollId(recovery.id); } }}>恢复查询（不重新生成）</button><p>请保留此编号，可关闭弹窗；同一参数再次点击“生成图片”可回到这里。</p></div>}
      {(phase === "idle" || phase === "planning") && <div className="dp-loading" role="status"><span>✧</span><h3>AI 正在编排详情页方案</h3><p>根据产品图整理每张图的字样、展示内容与先后顺序。</p><small>此阶段只生成文字方案，不生成图片。请保留当前页面。</small></div>}
      {phase === "error" && <div className="dp-loading"><h3>暂时无法取得 AI 方案</h3><p>未启动图片生成。修复服务配置或连接后可重新尝试；上一次调用是否计费请以供应商记录为准。</p><button type="button" onClick={() => void createPlan()}>重新尝试策划</button></div>}
      {phase === "review" && plan && <><p className="dp-intro">以下内容均可直接打字修改。拖动手柄或使用上下箭头调整顺序，确认后按当前方案逐张出图。</p><div className="dp-cards">{plan.items.map((item, index) => <article className="dp-card" key={item.id} onDragOver={(event) => { if (dragged) event.preventDefault(); }} onDrop={(event) => { event.preventDefault(); if (dragged) editItems(reorderPlan(plan.items, dragged, item.id)); setDragged(""); }}>
        <header><button type="button" draggable aria-label={`拖动第 ${index + 1} 张排序`} onDragStart={(event) => { setDragged(item.id); event.dataTransfer.setData("text/plain", item.id); event.dataTransfer.effectAllowed = "move"; }} onDragEnd={() => setDragged("")}>⠿</button><strong>#{String(index + 1).padStart(2, "0")}</strong><input aria-label={`第 ${index + 1} 张主题`} value={item.theme} maxLength={120} onChange={(event) => editItem(item.id, { theme: event.target.value })} /><button type="button" aria-label={`上移第 ${index + 1} 张`} disabled={index === 0} onClick={() => move(item, -1)}>↑</button><button type="button" aria-label={`下移第 ${index + 1} 张`} disabled={index === plan.items.length - 1} onClick={() => move(item, 1)}>↓</button><button type="button" aria-label={`删除第 ${index + 1} 张`} disabled={plan.items.length === 1} onClick={() => editItems(plan.items.filter((other) => other.id !== item.id))}>×</button></header>
        <div className="dp-fields"><div><label>图片展示内容<textarea value={item.visualDescription} maxLength={2000} onChange={(event) => editItem(item.id, { visualDescription: event.target.value })} /></label><label>视觉风格<input value={item.stylePrompt} maxLength={1000} onChange={(event) => editItem(item.id, { stylePrompt: event.target.value })} /></label></div><div><label>图片上的字样 · 标题<input value={item.textOverlay.headline} maxLength={200} onChange={(event) => editItem(item.id, { textOverlay: { ...item.textOverlay, headline: event.target.value } })} /></label><label>图片上的字样 · 正文<textarea value={item.textOverlay.body} maxLength={1000} onChange={(event) => editItem(item.id, { textOverlay: { ...item.textOverlay, body: event.target.value } })} /></label><label>文案位置<select value={item.textOverlay.placement} onChange={(event) => editItem(item.id, { textOverlay: { ...item.textOverlay, placement: event.target.value as PlanItem["textOverlay"]["placement"] } })}>{Object.entries(placements).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div></div>
        <footer>参考产品图：{item.sourceImageIds.map((id) => snapshot.images.findIndex((image) => image.id === id) + 1).join("、")}</footer>
      </article>)}</div><button className="dp-add" type="button" disabled={plan.items.length >= 12} onClick={() => editItems([...plan.items, { id: crypto.randomUUID(), order: plan.items.length + 1, theme: "新增画面", visualDescription: "", stylePrompt: plan.items[0].stylePrompt, textOverlay: { headline: "", body: "", placement: "bottom" }, sourceImageIds: [assets[0].id] }])}>＋ 添加一张（最多 12 张）</button></>}
      {rendering && <><div className="dp-progress-copy" role="status"><h3>{phase === "finished" ? task?.status === "completed" ? "整套详情图已生成" : "生成已结束，请检查失败项" : "正在生成，请保留当前页面"}</h3><p>成功 {completed} / {task?.items.length ?? plan?.items.length} 张 · 已处理 {progress}%</p></div><progress aria-label="图片处理进度" value={progress} max={100} /><div className="dp-results">{(task?.items ?? []).map((result, index) => <article key={result.planItemId}><h3>#{index + 1} · {plan?.items.find((item) => item.id === result.planItemId)?.theme}</h3>{resultUrl(result.previewUrl) ? <a href={resultUrl(result.previewUrl)} target="_blank" rel="noreferrer"><img src={resultUrl(result.previewUrl)} alt={`第 ${index + 1} 张生成结果`} /></a> : <div className="dp-result-placeholder">{statuses[result.status]}</div>}<p>{result.error?.message || statuses[result.status]}</p>{resultUrl(result.downloadUrl) && <a href={resultUrl(result.downloadUrl)} download>下载图片 ↓</a>}</article>)}</div>{phase === "finished" && <p className="dp-intro">请核对图片字样、产品细节和尺寸信息；AI 生成文字可能存在偏差。</p>}</>}
    </div>
    <footer className="dp-footer"><span>{plan ? `${plan.items.length} 张 · ${plan.input.aspectRatio} · ${plan.input.resolution}` : "先审阅文字方案，再开始出图"}</span><div>{phase === "review" && <><button type="button" onClick={onClose}>暂存，稍后确认</button><button className="dp-primary" type="button" onClick={() => void confirm()}>确认方案，生成 {plan?.items.length} 张图片 →</button></>}{phase === "finished" && <>{resultUrl(task?.exportUrl) && <a className="dp-primary" href={resultUrl(task?.exportUrl)} download>导出整套 ZIP ↓</a>}<button type="button" onClick={onClose}>返回画布</button></>}{busy && <span>处理中，请勿刷新或重复提交</span>}</div></footer>
  </dialog>;
}
