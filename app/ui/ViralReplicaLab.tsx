"use client";

import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import "./ViralReplicaLab.css";

const API = process.env.NEXT_PUBLIC_STUDIO_API ?? "http://127.0.0.1:8000";
const ACCEPT = "image/jpeg,image/png,image/webp";
type Slot = "main" | "extraOne" | "extraTwo" | "reference";
type Upload = { file: File; url: string; width: number; height: number };
type Target = { target_width: number; target_height: number; overridden: boolean; signature: string };
type ReplicaJob = {
  id: string; status: string; stage: string; error: string | null; uncertain: boolean;
  phase: string; attempt_count: number; retryable: boolean;
  target_width: number; target_height: number; custom_notes: string; remove_text: boolean;
  preview_url: string | null; download_url: string | null;
  result_metadata?: { sha256?: string; bytes?: number; returned_size?: number[]; target_size?: number[] } | null;
  source_urls: { main: string; reference: string };
};
const active = (job: ReplicaJob | null) => !!job && ["queued", "connecting", "submitting", "receiving", "generating", "downloading", "validating"].includes(job.status);

async function responseData(response: Response) {
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    const error = new Error(typeof detail === "string" ? detail : detail?.message ?? "请求未成功，请检查素材和本地服务。");
    Object.assign(error, { jobId: detail?.job_id });
    throw error;
  }
  return data;
}

export default function ViralReplicaLab() {
  const mainInputRef = useRef<HTMLInputElement>(null);
  const urls = useRef(new Set<string>());
  const slotUrls = useRef<Partial<Record<Slot, string>>>({});
  const hydratedJob = useRef("");
  const uploadVersions = useRef<Record<Slot, number>>({ main: 0, extraOne: 0, extraTwo: 0, reference: 0 });
  const alive = useRef(true);
  const submitLock = useRef(false);
  const pending = useRef<{ url: string; key: string; body: FormData | string } | null>(null);
  const [uploads, setUploads] = useState<Partial<Record<Slot, Upload>>>({});
  const [removeText, setRemoveText] = useState(true);
  const [notes, setNotes] = useState("");
  const [target, setTarget] = useState<Target | null>(null);
  const [prepareError, setPrepareError] = useState("");
  const [error, setError] = useState("");
  const [connection, setConnection] = useState("");
  const [configured, setConfigured] = useState(false);
  const [providerMessage, setProviderMessage] = useState("正在连接本地后端…");
  const [jobId, setJobId] = useState("");
  const [job, setJob] = useState<ReplicaJob | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [uncertainSubmit, setUncertainSubmit] = useState(false);
  const [view, setView] = useState<"result" | "main" | "reference">("main");
  const [retryConfirmed, setRetryConfirmed] = useState(false);
  const [decoding, setDecoding] = useState(0);
  const locked = submitting || active(job) || (!!jobId && !job);
  const reference = uploads.reference;
  const signature = reference ? JSON.stringify([reference.url, reference.width, reference.height, notes]) : "";
  const prepared = target?.signature === signature ? target : null;

  useEffect(() => {
    alive.current = true;
    const abort = new AbortController();
    const saved = new URLSearchParams(window.location.search).get("job");
    const restore = window.setTimeout(() => { if (saved && /^rep_[a-f0-9]{32}$/.test(saved)) { setJobId(saved); setView("result"); } }, 0);
    fetch(API + "/api/replicate/capabilities", { signal: abort.signal })
      .then(responseData).then(async (data) => {
        if (!data.configured) { setConfigured(false); setProviderMessage(data.message); return; }
        const connectivityResponse = await fetch(API + "/api/replicate/connectivity?refresh=true", { signal: abort.signal, cache: "no-store" });
        const connectionState = await responseData(connectivityResponse);
        setConfigured(Boolean(connectionState.connected));
        setProviderMessage(connectionState.connected ? "AI 服务连接正常 · Base64 图片直返已启用" : connectionState.message || "AI 服务暂不可达，请检查网络后刷新页面。");
      })
      .catch((reason) => { if (reason.name !== "AbortError") setProviderMessage("无法连接本地后端，请检查服务是否启动。"); });
    const currentUrls = urls.current;
    return () => { alive.current = false; abort.abort(); window.clearTimeout(restore); currentUrls.forEach(URL.revokeObjectURL); currentUrls.clear(); };
  }, []);

  useEffect(() => {
    if (!reference) return;
    const abort = new AbortController();
    const timer = window.setTimeout(() => {
      fetch(API + "/api/replicate/prepare", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reference_width: reference.width, reference_height: reference.height, custom_notes: notes }), signal: abort.signal })
        .then(responseData).then((data) => { if (!abort.signal.aborted) { setTarget({ ...data, signature }); setPrepareError(""); } })
        .catch((reason) => { if (reason.name !== "AbortError") { setTarget(null); setPrepareError(reason.message); } });
    }, 250);
    return () => { abort.abort(); window.clearTimeout(timer); };
  }, [reference, notes, signature]);

  useEffect(() => {
    if (!jobId) return;
    const abort = new AbortController();
    let timer: number | undefined;
    const poll = async () => {
      let keepPolling = true;
      try {
        const response = await fetch(API + "/api/replicate/jobs/" + jobId, { signal: abort.signal, cache: "no-store" });
        if (response.status === 404) {
          setConnection("后端暂未找到该任务；可能仍在上传或提交已中断。不会自动发起新的生成。");
        } else {
          const data: ReplicaJob = await responseData(response);
          if (abort.signal.aborted) return;
          setJob(data); setConnection(""); setUncertainSubmit(false);
          if (hydratedJob.current !== data.id) { hydratedJob.current = data.id; setNotes(data.custom_notes); setRemoveText(data.remove_text); }
          keepPolling = active(data);
        }
      } catch (reason) {
        if ((reason as Error).name !== "AbortError") setConnection("任务状态连接中断，正在重新查询；不会重新提交生成。");
      }
      if (!abort.signal.aborted && keepPolling) timer = window.setTimeout(poll, 2000);
    };
    void poll();
    return () => { abort.abort(); window.clearTimeout(timer); };
  }, [jobId]);

  const track = (id: string) => {
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("job", id); else url.searchParams.delete("job");
    window.history.replaceState(null, "", url);
    setJobId(id);
  };
  const clearJob = () => {
    if ((locked || job?.uncertain) && !window.confirm("当前任务状态可能不确定。新建前请核查供应商记录，避免重复计费。确定离开此任务？")) return;
    track(""); setJob(null); setError(""); setConnection(""); setRetryConfirmed(false); setUncertainSubmit(false); pending.current = null;
  };

  const setFile = async (slot: Slot, files: FileList | null) => {
    if (locked || !files?.length) return;
    if (files.length !== 1) { setError(slot === "reference" ? "参考图仅允许一张，请重新选择。" : "每个产品视角只能选择一张图片。"); return; }
    const file = files[0];
    if (!ACCEPT.split(",").includes(file.type)) { setError("仅支持 JPG、PNG、WEBP 图片。"); return; }
    if (file.size > 20 * 1024 * 1024) { setError("单张图片不能超过 20MB。"); return; }
    const version = ++uploadVersions.current[slot];
    setDecoding((count) => count + 1);
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
      const { width, height } = bitmap;
      bitmap.close();
      if (Math.min(width, height) < 64 || Math.max(width, height) > 16384 || width * height > 36_000_000) throw new Error("宽高须为 64–16384 像素，总像素不超过 3600 万。");
      if (!alive.current || version !== uploadVersions.current[slot]) return;
      const url = URL.createObjectURL(file);
      urls.current.add(url);
      const previous = slotUrls.current[slot];
      if (previous) { URL.revokeObjectURL(previous); urls.current.delete(previous); }
      slotUrls.current[slot] = url;
      setUploads((current) => ({ ...current, [slot]: { file, url, width, height } }));
      if (jobId) { track(""); setJob(null); }
      setError("");
    } catch (reason) {
      if (alive.current && version === uploadVersions.current[slot]) setError((reason as Error).message || "无法读取图片。");
    } finally { if (alive.current) setDecoding((count) => count - 1); }
  };
  const removeFile = (slot: Slot) => {
    if (locked) return;
    uploadVersions.current[slot]++;
    const previous = uploads[slot];
    if (previous) { URL.revokeObjectURL(previous.url); urls.current.delete(previous.url); }
    delete slotUrls.current[slot];
    setUploads((current) => { const next = { ...current }; delete next[slot]; return next; });
    if (jobId) { track(""); setJob(null); }
    setError("");
  };
  const choose = (slot: Slot, event: ChangeEvent<HTMLInputElement>) => { void setFile(slot, event.target.files); event.target.value = ""; };
  const drop = (slot: Slot, event: DragEvent<HTMLLabelElement>) => { event.preventDefault(); void setFile(slot, event.dataTransfer.files); };

  const sendPending = async () => {
    if (submitLock.current || !pending.current) return;
    submitLock.current = true; setSubmitting(true); setError(""); setUncertainSubmit(false);
    const submission = pending.current;
    setJob(null); track("rep_" + submission.key.replaceAll("-", ""));
    let receivedResponse = false;
    try {
      const response = await fetch(submission.url, { method: "POST", headers: { "Idempotency-Key": submission.key, ...(typeof submission.body === "string" ? { "Content-Type": "application/json" } : {}) }, body: submission.body, signal: AbortSignal.timeout(60000) });
      receivedResponse = response.status >= 400 && response.status < 500;
      const data: ReplicaJob = await responseData(response);
      if (!alive.current) return;
      setJob(data); track(data.id); setView("result"); setRetryConfirmed(false);
      pending.current = null;
    } catch (reason) {
      if (!alive.current) return;
      const message = reason as Error & { jobId?: string };
      if (message.jobId) { track(message.jobId); pending.current = null; }
      else if (receivedResponse) { track(""); setJob(null); pending.current = null; }
      else setUncertainSubmit(true);
      setError(receivedResponse ? message.message : "提交结果不确定，已保留原请求标识。请查询状态或安全重发同一请求，不要新建重复生成。");
    } finally { submitLock.current = false; setSubmitting(false); }
  };
  const startGeneration = () => {
    if (!uploads.main || !reference || !prepared || locked || !configured || decoding) return;
    const body = new FormData();
    body.append("main_image", uploads.main.file); body.append("reference_image", reference.file);
    for (const slot of ["extraOne", "extraTwo"] as const) if (uploads[slot]) body.append("extra_images", uploads[slot]!.file);
    body.append("remove_text", String(removeText)); body.append("custom_notes", notes);
    body.append("confirmed_width", String(prepared.target_width)); body.append("confirmed_height", String(prepared.target_height));
    pending.current = { url: API + "/api/replicate/jobs", key: crypto.randomUUID(), body };
    void sendPending();
  };
  const retry = (confirmPossibleCharge: boolean) => {
    if (!job || locked || (job.uncertain && !retryConfirmed)) return;
    pending.current = { url: API + "/api/replicate/jobs/" + job.id + "/retry", key: crypto.randomUUID(), body: JSON.stringify({ confirm_possible_charge: confirmPossibleCharge }) };
    void sendPending();
  };

  const shownImage = job
    ? view === "result" && job.preview_url ? API + job.preview_url : API + job.source_urls[view === "reference" ? "reference" : "main"]
    : view === "reference" ? reference?.url : uploads.main?.url;
  const displaySize = job ? job.target_width + " × " + job.target_height + " px" : prepared ? prepared.target_width + " × " + prepared.target_height + " px" : "跟随参考图";
  const working = submitting || active(job);

  return (
    <main className="replica-lab">
      <header className="replica-topbar">
        <a className="replica-brand" href="/dashboard?tool=replicate"><img src="/brand-logo.jpg" alt="" /><span>返回</span></a>
        <div className="replica-mode">◇ 爆款复刻</div>
        <div className="replica-status"><span>单张参考 · 真实生成</span><b>{configured ? "CONFIG LOADED" : "LOCAL WORKSPACE"}</b></div>
        <button className="replica-import" type="button" disabled={locked} onClick={() => mainInputRef.current?.click()}>⇧ 导入产品图</button>
      </header>
      <div className="replica-columns">
        <section className={"replica-canvas-shell " + (working ? "is-generating" : "")} aria-label="爆款复刻画布">
          <div className="replica-preview-tabs" aria-label="查看素材与结果">{([["main", "产品原图"], ["reference", "参考图"], ["result", "生成结果"]] as const).map(([key, label]) => <button key={key} type="button" aria-pressed={view === key} disabled={key === "result" && !job?.preview_url} onClick={() => setView(key)}>{label}</button>)}</div>
          <div className="replica-canvas">
            {shownImage ? <img className="replica-canvas__image" src={shownImage} alt={view === "reference" ? "参考图" : view === "result" && job?.preview_url ? "AI 复刻结果，待人工确认" : "产品原图，未被修改"} /> : <div className="replica-empty-hint">上传主产品图与一张参考图，开始场景复刻</div>}
            {working && <div className="neural-progress" role="status"><span>{submitting ? "正在上传并提交任务…" : job?.stage}</span><small>请保留此页面链接，刷新后可继续查询</small></div>}
            <span className="hud-corner hud-corner--tl" /><span className="hud-corner hud-corner--tr" /><span className="hud-corner hud-corner--bl" /><span className="hud-corner hud-corner--br" />
          </div>
          <div className="replica-canvas__label"><span><i />{job?.status === "completed" ? "生成结果 · 待人工确认" : "爆款复刻画布"}</span><b>{displaySize}</b></div>
          {job?.download_url && <a className="replica-download" href={API + job.download_url}>下载生成图片 ↓</a>}
        </section>
        <aside className="replica-panel replica-dock">
          <div className="replica-panel__heading"><span>01</span><div><strong>REPLICA CONSOLE</strong><small>素材、尺寸与生成控制</small></div><em>INPUT / OUTPUT</em></div>
          <section className="replica-module"><header><strong>产品图片</strong><span>主视角必填 · 补充视角选填</span></header><div className="product-upload-grid">
            {(["main", "extraOne", "extraTwo"] as const).map((slot, index) => <div className={"replica-upload-wrap " + (index === 0 ? "is-main" : "")} key={slot}>
              <label className={"replica-upload " + (index === 0 ? "is-main " : "") + (uploads[slot] ? "has-image" : "")} onDragOver={(event) => event.preventDefault()} onDrop={(event) => drop(slot, event)}>
                <input ref={slot === "main" ? mainInputRef : undefined} type="file" accept={ACCEPT} disabled={locked} aria-label={index === 0 ? "上传主产品图" : "上传补充视角 " + index} onChange={(event) => choose(slot, event)} />
                {uploads[slot] ? <img src={uploads[slot]!.url} alt={index === 0 ? "产品主视角" : "产品补充视角 " + index} /> : <><b>⇧</b><strong>{index === 0 ? "主视角" : "补充视角 " + index}</strong><small>JPG / PNG / WEBP</small></>}
              </label>
              {uploads[slot] && <div className="replica-file-actions"><span title={uploads[slot]!.file.name}>{uploads[slot]!.file.name}</span><button type="button" disabled={locked} onClick={() => removeFile(slot)}>移除</button></div>}
            </div>)}
          </div></section>
          <section className="replica-module replica-reference"><header><strong>参考图</strong><span>仅允许一张 · 必填</span></header>
            <label className="reference-drop" onDragOver={(event) => event.preventDefault()} onDrop={(event) => drop("reference", event)}><input type="file" accept={ACCEPT} disabled={locked} aria-label="上传一张参考图" onChange={(event) => choose("reference", event)} />{reference ? <img className="replica-reference-image" src={reference.url} alt="当前唯一参考图" /> : <b>＋</b>}<strong>{reference ? "点击替换参考图" : "上传或拖入一张参考图"}</strong><small>单张不超过 20MB</small></label>
            {reference && <div className="replica-file-actions"><span>{reference.width} × {reference.height} px</span><button type="button" disabled={locked} onClick={() => removeFile("reference")}>移除</button></div>}
          </section>
          <section className="replica-module replica-switch-row"><div><strong>去除参考图文字</strong><small>默认保留主产品 Logo · 补充说明可覆盖</small></div><button aria-label="去除参考图文字" disabled={locked} className={removeText ? "is-on" : ""} type="button" role="switch" aria-checked={removeText} onClick={() => setRemoveText(!removeText)}><i /><span>{removeText ? "ON" : "OFF"}</span></button></section>
          <section className="replica-module"><header><label htmlFor="replica-notes"><strong>补充说明</strong></label><span>优先于默认渲染规则</span></header><textarea id="replica-notes" disabled={locked} value={notes} maxLength={800} onChange={(event) => setNotes(event.target.value)} placeholder="描述希望修改的内容。如需改变输出尺寸，请写：1200×1600 px" /><div className="text-count">{notes.length}/800</div></section>
          <section className="replica-module replica-size"><header><strong>输出尺寸</strong><span>{prepared?.overridden ? "补充说明覆盖" : "跟随参考图"}</span></header><b>{prepared ? prepared.target_width + " × " + prepared.target_height + " px" : reference ? "等待尺寸确认…" : "请先上传参考图"}</b><p>按参考图方向读取尺寸；必要时等比例生成后缩放，不裁剪、不拉伸。</p>{reference && prepareError && <p role="alert" className="replica-error">{prepareError}</p>}</section>
          <p className="replica-provider-note">{providerMessage}</p>
          <p className="replica-provider-note">以参考图角度为先，尽量保留产品细节；生成后需人工检查 Logo、纹理及光影。供应商可能按套餐或额度计费。</p>
          {error && <p className="replica-error" role="alert">{error}</p>}
          {connection && <p className="replica-provider-note" role="status">{connection}</p>}
          {job && <section className="replica-module replica-job" aria-live="polite"><strong>{job.stage}</strong><small>{job.phase} · 尝试 {job.attempt_count} 次 · 任务 {job.id}</small>{job.error && <p className="replica-error">{job.error}</p>}{["failed", "interrupted"].includes(job.status) && (job.retryable && !job.uncertain ? <button type="button" className="replica-generate" disabled={locked || !configured} onClick={() => retry(false)}>安全重试 · 请求尚未提交</button> : <><label className="replica-retry-confirm"><input type="checkbox" checked={retryConfirmed} onChange={(event) => setRetryConfirmed(event.target.checked)} />我已核查记录，确认重试可能再次计费</label><button type="button" className="replica-generate" disabled={!retryConfirmed || locked || !configured} onClick={() => retry(true)}>重试此任务</button></>)}</section>}
          {uncertainSubmit && <button type="button" className="replica-generate" disabled={submitting} onClick={() => void sendPending()}>安全重发同一次提交</button>}
          {!jobId && <button className="replica-generate" type="button" disabled={!uploads.main || !reference || !prepared || locked || !configured || decoding > 0} onClick={startGeneration}><span>{decoding ? "正在读取图片…" : submitting ? "正在提交…" : "确认尺寸并生成 1 张"}</span><em>GENERATE</em></button>}
          {jobId && !working && <button className="replica-reset" type="button" onClick={clearJob}>新建复刻任务</button>}
        </aside>
      </div>
    </main>
  );
}
