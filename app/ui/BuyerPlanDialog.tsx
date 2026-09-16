"use client";

import { useEffect, useRef, useState } from "react";
import { BuyerApiError, buyerResultUrl, createBuyerPlan, createBuyerTask, downloadBuyerPlan, queryBuyerPlan, queryBuyerTask, uploadBuyerProduct, type BuyerInput, type BuyerPlan, type BuyerTask } from "../buyer-show/api";

export interface BuyerPlanDraft {
  file: File; productName: string; productFeatures: string; material: string; sellingPoints: string; notes: string;
  style: "更真实" | "更精致"; count: number; ratio: string; resolution: string;
}

export default function BuyerPlanDialog({ draft, onClose, onProgress, onComplete }: { draft: BuyerPlanDraft; onClose: () => void; onProgress: (task: BuyerTask) => void; onComplete: (task: BuyerTask) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [phase, setPhase] = useState<"planning" | "review" | "submitting" | "rendering" | "finished" | "error">("planning");
  const [plan, setPlan] = useState<BuyerPlan | null>(null);
  const [input, setInput] = useState<BuyerInput | null>(null);
  const [planId, setPlanId] = useState("");
  const [task, setTask] = useState<BuyerTask | null>(null);
  const [taskId, setTaskId] = useState("");
  const [message, setMessage] = useState("正在分析产品信息并编排套图…");

  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => {
    let stopped = false;
    void (async () => {
      try {
        const asset = await uploadBuyerProduct(draft.file);
        const nextInput: BuyerInput = { product_name: draft.productName.trim(), product_features: draft.productFeatures.trim(), material: draft.material.trim(), style: draft.style,
          image_count: draft.count, aspect_ratio: draft.ratio, resolution: draft.resolution, scene_preferences: draft.notes.trim(), selling_points: draft.sellingPoints.trim(), notes: draft.notes.trim(), assets: [asset] };
        const id = crypto.randomUUID(); setInput(nextInput); setPlanId(id);
        const result = await createBuyerPlan(nextInput, id);
        if (!stopped) { setPlan(result); setPhase("review"); setMessage("AI 方案已生成。可以手动修改；确认之前不会生成图片。"); }
      } catch (cause) {
        const error = cause as BuyerApiError;
        if (error instanceof BuyerApiError && error.uncertain && error.requestId) {
          setMessage("策划连接中断，正在只读查询原请求，不会重复提交…");
          for (let attempt = 0; attempt < 20 && !stopped; attempt += 1) {
            await new Promise((resolve) => window.setTimeout(resolve, 3000));
            try {
              const recovered = await queryBuyerPlan(error.requestId);
              if (recovered && !stopped) { setPlan(recovered); setPhase("review"); setMessage("已恢复原策划结果。可以修改，确认前不会生成图片。"); return; }
            } catch { /* keep querying the original id only */ }
          }
        }
        if (!stopped) { setMessage(error instanceof Error ? error.message : "方案生成失败。"); setPhase("error"); }
      }
    })();
    return () => { stopped = true; };
  }, [draft]);

  useEffect(() => {
    if (phase !== "rendering" || !taskId) return;
    let stopped = false;
    const poll = async () => {
      try {
        const result = await queryBuyerTask(taskId);
        if (stopped) return;
        setTask(result);
        onProgress(result);
        if (["completed", "partial", "failed"].includes(result.status)) {
          setPhase(result.status === "failed" ? "error" : "finished");
          setMessage(result.status === "completed" ? "整套生活场景图已生成完成。" : result.status === "partial" ? "部分图片已完成，失败项不会自动重试。" : "图片生成失败，未自动重复提交。");
          onComplete(result); return;
        }
        window.setTimeout(poll, 1800);
      } catch (cause) { if (!stopped) { setMessage(cause instanceof Error ? cause.message : "任务查询失败。"); window.setTimeout(poll, 3000); } }
    };
    const timer = window.setTimeout(poll, 900);
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [phase, taskId, onProgress, onComplete]);

  const updateItem = (position: number, field: "scene_description" | "image_prompt" | "negative_prompt", value: string) =>
    setPlan((current) => current ? { ...current, image_plan: current.image_plan.map((item, index) => index === position ? { ...item, [field]: value } : item) } : current);

  const confirm = async () => {
    if (!input || !plan || phase !== "review") return;
    if (!plan.project_title.trim() || plan.image_plan.some((item) => !item.scene_description.trim() || !item.image_prompt.trim() || !item.negative_prompt.trim())) { setMessage("标题、图片描述和提示词都不能为空。"); return; }
    const id = crypto.randomUUID(); setTaskId(id); setPhase("submitting"); setMessage("正在提交已确认方案…");
    try {
      const result = await createBuyerTask(input, planId, plan, id);
      setTask(result); onProgress(result); setPhase("rendering"); setMessage("整套图片正在并行生成。每完成一张就会展示一张；连接中断时只查询原任务，不会重复出图。");
    } catch (cause) {
      const error = cause as BuyerApiError; setMessage(error instanceof Error ? error.message : "出图任务提交失败。");
      setPhase(error instanceof BuyerApiError && error.uncertain ? "rendering" : "error");
    }
  };

  const completed = task?.items.filter((item) => item.status === "completed").length ?? 0;
  const busy = ["planning", "submitting", "rendering"].includes(phase);
  return <dialog ref={dialog} className="buyer-plan-dialog" onCancel={(event) => { if (busy) event.preventDefault(); else onClose(); }}>
    <header><div><span>AI LIFESTYLE PLAN</span><h2>生活场景套图方案</h2></div><button type="button" disabled={busy} onClick={onClose} aria-label="关闭">×</button></header>
    <div className="buyer-plan-status" role="status"><i className={busy ? "is-live" : ""} /><span>{message}</span>{task && <b>{completed} / {task.items.length}</b>}</div>
    {plan && <div className="buyer-plan-body">
      <label className="buyer-plan-title"><span>项目标题</span><input value={plan.project_title} maxLength={240} onChange={(event) => setPlan({ ...plan, project_title: event.target.value })} disabled={phase !== "review"} /></label>
      <div className="buyer-plan-list">{plan.image_plan.map((item, position) => <article key={item.index} className="buyer-plan-item">
        <header><b>#{String(item.index).padStart(2, "0")}</b><strong>{item.shot_type}</strong><em>{plan.aspect_ratio} · {plan.resolution}</em></header>
        <label><span>图片展示内容与顺序</span><textarea value={item.scene_description} maxLength={2000} disabled={phase !== "review"} onChange={(event) => updateItem(position, "scene_description", event.target.value)} /></label>
        <label><span>英文渲染 Prompt</span><textarea value={item.image_prompt} maxLength={9000} disabled={phase !== "review"} onChange={(event) => updateItem(position, "image_prompt", event.target.value)} /></label>
        <label><span>Negative Prompt</span><textarea value={item.negative_prompt} maxLength={2500} disabled={phase !== "review"} onChange={(event) => updateItem(position, "negative_prompt", event.target.value)} /></label>
        {task?.items[position]?.previewUrl && <a className="buyer-plan-preview" href={buyerResultUrl(task.items[position].downloadUrl!)}><img src={buyerResultUrl(task.items[position].previewUrl!)} alt={`生成结果 ${item.index}`} /><span>下载第 {item.index} 张</span></a>}
        {task?.items[position]?.error && <p className="buyer-plan-error">{task.items[position].error?.message}</p>}
      </article>)}</div>
    </div>}
    <footer>{plan && <button type="button" className="buyer-plan-ghost" onClick={() => downloadBuyerPlan(plan)}>下载方案 JSON</button>}<span />
      {!busy && <button type="button" className="buyer-plan-ghost" onClick={onClose}>{phase === "finished" ? "完成" : "稍后处理"}</button>}
      {phase === "review" && <button type="button" className="buyer-plan-confirm" onClick={() => void confirm()}>确认方案并生成 {plan?.image_plan.length} 张图片</button>}
      {phase === "finished" && task?.exportUrl && <a className="buyer-plan-confirm" href={buyerResultUrl(task.exportUrl)}>导出整套图片</a>}
    </footer>
  </dialog>;
}
