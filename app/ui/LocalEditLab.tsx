"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties, type DragEvent, type PointerEvent } from "react";
import "./TemplateLab.css";
import "./LocalEditLab.css";

const API = process.env.NEXT_PUBLIC_STUDIO_API ?? "http://127.0.0.1:8000";
type SourceImage = { url: string; name: string; file: File };
type MaskPoint = { x: number; y: number };
type MaskStroke = { points: MaskPoint[]; size: number };

function Icon({ name }: { name: "back" | "upload" | "edit" | "chevron" | "spark" }) {
  const paths = {
    back: <path d="m15 18-6-6 6-6" />,
    upload: <><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" /><path d="M5 15v4h14v-4" /></>,
    edit: <><path d="M9 3H3v6m12-6h6v6M3 15v6h6m12-6v6h-6" /><path d="m8 16 1-4 6-6 3 3-6 6-4 1Z" /></>,
    chevron: <path d="m8 10 4 4 4-4" />,
    spark: <><path d="m12 3 1.35 4.15L17.5 8.5l-4.15 1.35L12 14l-1.35-4.15L6.5 8.5l4.15-1.35L12 3Z" /><path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z" /></>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

export default function LocalEditLab({ initialFile, backHref = "/dashboard?tool=local-edit", onBack }: { initialFile?: File; backHref?: string; onBack?: () => void } = {}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const strokesRef = useRef<MaskStroke[]>([]);
  const activeStrokeRef = useRef<MaskStroke | null>(null);
  const [source, setSource] = useState<SourceImage | null>(null);
  const [sourceSize, setSourceSize] = useState<{ width: number; height: number } | null>(null);
  const [maskRevision, setMaskRevision] = useState(0);
  const [brushSize, setBrushSize] = useState(7);
  const [drawing, setDrawing] = useState(false);
  const [selectionConfirmed, setSelectionConfirmed] = useState(false);
  const [ratio, setRatio] = useState("3:4");
  const [resolution, setResolution] = useState("1K");
  const [editScope, setEditScope] = useState<"selected_only" | "whole_image">("selected_only");
  const [prompt, setPrompt] = useState("");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [generating, setGenerating] = useState(false);
  const [resultUrl, setResultUrl] = useState("");
  const [promptPlan, setPromptPlan] = useState<object | null>(null);

  useEffect(() => {
    if (!source) return;
    return () => URL.revokeObjectURL(source.url);
  }, [source]);

  const hasMask = maskRevision > 0 && strokesRef.current.length > 0;

  const paintMask = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !sourceSize) return;
    if (canvas.width !== sourceSize.width || canvas.height !== sourceSize.height) {
      canvas.width = sourceSize.width;
      canvas.height = sourceSize.height;
    }
    const context = canvas.getContext("2d");
    if (!context) return;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.lineCap = "round";
    context.lineJoin = "round";
    context.strokeStyle = "rgba(0, 242, 254, .62)";
    context.fillStyle = "rgba(0, 242, 254, .62)";
    for (const stroke of strokesRef.current) {
      const width = Math.max(8, stroke.size / 100 * Math.min(canvas.width, canvas.height));
      context.lineWidth = width;
      if (stroke.points.length === 1) {
        context.beginPath();
        context.arc(stroke.points[0].x * canvas.width, stroke.points[0].y * canvas.height, width / 2, 0, Math.PI * 2);
        context.fill();
        continue;
      }
      context.beginPath();
      stroke.points.forEach((point, index) => {
        const x = point.x * canvas.width;
        const y = point.y * canvas.height;
        if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
      });
      context.stroke();
    }
  }, [sourceSize]);

  useEffect(() => { paintMask(); }, [paintMask, maskRevision, resultUrl]);

  const resetSelection = () => {
    activeStrokeRef.current = null;
    strokesRef.current = [];
    setMaskRevision(0);
    setDrawing(false);
    setSelectionConfirmed(false);
    setResultUrl("");
    setPromptPlan(null);
    setNotice("");
  };

  const addImage = (files: FileList | null) => {
    setDragging(false);
    const file = files?.[0];
    if (!file) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setError("请选择 JPG、PNG 或 WEBP 图片。");
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      setError("图片不能超过 20MB，请选择较小的图片。");
      return;
    }
    resetSelection();
    setSourceSize(null);
    setSource({ url: URL.createObjectURL(file), name: file.name, file });
    setError("");
    setPrompt("");
    setEditScope("selected_only");
  };

  useEffect(() => {
    if (initialFile && !source) addImage([initialFile] as unknown as FileList);
  }, [initialFile]);

  const removeImage = () => {
    resetSelection();
    setSource(null);
    setSourceSize(null);
    setPrompt("");
    setEditScope("selected_only");
  };

  const imageError = () => {
    removeImage();
    setError("无法读取这张图片，请重新选择有效图片。");
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    addImage(event.dataTransfer.files);
  };

  const pointerPoint = (event: PointerEvent<HTMLCanvasElement>): MaskPoint => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
    };
  };

  const beginStroke = (event: PointerEvent<HTMLCanvasElement>) => {
    if (selectionConfirmed || event.button !== 0 || !event.isPrimary) return;
    const stroke = { points: [pointerPoint(event)], size: brushSize };
    strokesRef.current.push(stroke);
    activeStrokeRef.current = stroke;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrawing(true);
    setNotice("");
    setMaskRevision((value) => value + 1);
  };

  const continueStroke = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!activeStrokeRef.current) return;
    activeStrokeRef.current.points.push(pointerPoint(event));
    paintMask();
  };

  const endStroke = (event: PointerEvent<HTMLCanvasElement>) => {
    activeStrokeRef.current = null;
    setDrawing(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    setMaskRevision((value) => value + 1);
  };

  const undoStroke = () => {
    if (selectionConfirmed) return;
    strokesRef.current.pop();
    setMaskRevision((value) => strokesRef.current.length ? value + 1 : 0);
    setNotice("");
  };

  const maskBlob = async () => {
    if (!sourceSize) throw new Error("图片尚未读取完成。");
    const canvas = document.createElement("canvas");
    canvas.width = sourceSize.width;
    canvas.height = sourceSize.height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("无法创建 Mask。");
    context.fillStyle = "#000";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.lineCap = "round";
    context.lineJoin = "round";
    context.strokeStyle = "#fff";
    context.fillStyle = "#fff";
    for (const stroke of strokesRef.current) {
      const width = Math.max(8, stroke.size / 100 * Math.min(canvas.width, canvas.height));
      context.lineWidth = width;
      context.beginPath();
      stroke.points.forEach((point, index) => index ? context.lineTo(point.x * canvas.width, point.y * canvas.height) : context.moveTo(point.x * canvas.width, point.y * canvas.height));
      if (stroke.points.length === 1) context.arc(stroke.points[0].x * canvas.width, stroke.points[0].y * canvas.height, width / 2, 0, Math.PI * 2);
      stroke.points.length === 1 ? context.fill() : context.stroke();
    }
    return new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Mask 导出失败。")), "image/png"));
  };

  const generate = async () => {
    if (!source || !selectionConfirmed || !prompt.trim() || generating) return;
    setGenerating(true);
    setResultUrl("");
    setPromptPlan(null);
    setNotice("正在转换提示词并提交局部重绘，可能需要几分钟…");
    try {
      const form = new FormData();
      form.append("image", source.file, source.name);
      form.append("mask", await maskBlob(), "mask.png");
      form.append("requirement", prompt.trim());
      form.append("edit_scope", editScope);
      const response = await fetch(`${API}/api/local-edit/generate`, { method: "POST", body: form, signal: AbortSignal.timeout(360000) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "局部重绘失败。");
      setPromptPlan(data.prompt_plan);
      setResultUrl(`${API}${data.result_url}?v=${Date.now()}`);
      setNotice(editScope === "selected_only" ? "局部重绘已完成，选区外保持原图不变。" : "整图编辑已完成。");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "局部重绘失败，请稍后重试。");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <main className="template-lab local-edit-lab">
      <header className="template-hud">
        {onBack ? <button type="button" className="template-back" onClick={onBack}><Icon name="back" /><span>返回花型制作</span></button> : <a className="template-back" href={backHref}><Icon name="back" /><span>返回</span></a>}
        <div className="template-brand"><img src="/brand-logo.jpg" alt="" /><div><strong>LOCAL EDIT LAB</strong><small>AI 图像局部精修控制台</small></div></div>
        <div className="template-status"><i /><span>LOCAL WORKSPACE</span><b>本地预览</b></div>
      </header>

      <div className="template-layout">
        <section className="template-canvas" aria-label="局部编辑画布">
          <div className="template-toolbar"><div><span>{source ? "用画笔涂抹需要调整的区域" : "图片素材预览"}</span><i /><span>确认前可撤销</span></div><button type="button" onClick={() => inputRef.current?.click()}><Icon name="upload" />导入到画布</button></div>
          <div className={`template-stage local-edit-stage ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }} onDrop={onDrop}>
            <span className="template-grid-glow" aria-hidden="true" />
            <div className="template-stage-corners" aria-hidden="true"><i /><i /><i /><i /></div>
            {source ? (
              <div className="local-edit-loaded">
                <div className="local-edit-tools"><span>{selectionConfirmed ? "局部区域已确认" : drawing ? "正在涂抹选区" : "画笔选区 · 原图尚未修改"}</span><div><button type="button" disabled={!hasMask || selectionConfirmed} onClick={undoStroke}>撤销一笔</button><button type="button" disabled={!hasMask || selectionConfirmed} onClick={resetSelection}>清除选区</button></div></div>
                <div className="local-edit-image-stage">
                  <div className="local-edit-image-boundary" style={{ "--source-ratio": sourceSize ? sourceSize.width / sourceSize.height : 1 } as CSSProperties}>
                    <img src={resultUrl || source.url} alt={resultUrl ? "AI 局部重绘结果" : `待编辑原图：${source.name}`} draggable={false} onLoad={(event) => { if (!resultUrl) setSourceSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight }); }} onError={resultUrl ? undefined : imageError} />
                    {!resultUrl && <canvas ref={canvasRef} className={`local-edit-mask-layer ${selectionConfirmed ? "is-confirmed" : ""}`} aria-label="画笔选区：按住并拖动画笔，涂抹需要调整的局部区域" onPointerDown={beginStroke} onPointerMove={continueStroke} onPointerUp={endStroke} onPointerCancel={endStroke} />}
                    {selectionConfirmed && <span className="local-edit-confirmed-badge">选区已确认</span>}
                  </div>
                </div>
                <p className="local-edit-selection-info" role="status">{selectionConfirmed ? "已锁定画笔蒙版；如需调整，请点击“重新修改”" : hasMask ? `已绘制 ${strokesRef.current.length} 笔 · 检查无误后确认选区` : "按住鼠标或手指，在图片上涂抹需要修改的区域"}</p>
              </div>
            ) : (
              <div className="template-empty local-edit-empty"><div className="template-orbit"><Icon name="edit" /></div><span>LOCAL EDIT / CANVAS READY</span><p>上传图片后，用画笔圈涂需要调整的局部区域。</p><button type="button" onClick={() => inputRef.current?.click()}><Icon name="upload" />添加编辑图片</button></div>
            )}
          </div>
          <footer className="template-footer"><span><i />{selectionConfirmed ? "REGION CONFIRMED" : hasMask ? "MASK DRAWN" : source ? "SOURCE LOADED" : "CANVAS READY"}</span><b>{ratio} · {resolution}</b></footer>
        </section>

        <aside className="template-panel local-edit-panel" aria-label="局部编辑设置">
          <div className="local-edit-tool-menu template-panel-title"><h1><i><Icon name="edit" /></i>局部编辑</h1></div>

          <section className="template-card local-edit-upload-card">
            <header><div><span>01</span><strong>编辑图片</strong></div><em>IMAGE INPUT</em></header>
            <p>上传一张需要局部精修的图片。</p>
            <input ref={inputRef} className="local-edit-file-input" type="file" accept="image/jpeg,image/png,image/webp" aria-label="选择编辑图片文件" tabIndex={-1} onChange={(event) => { addImage(event.target.files); event.target.value = ""; }} />
            <div className={`local-edit-dropzone ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
              <button type="button" onClick={() => inputRef.current?.click()}>{source ? <img src={source.url} alt="编辑图片缩略图" onError={imageError} /> : <span><Icon name="upload" /></span>}<strong>{source ? "点击更换图片" : "上传或拖入图片"}</strong><small>JPG / PNG / WEBP · 不超过 20MB</small></button>
            </div>
            {source && <div className="local-edit-file-meta"><span title={source.name}>{source.name}</span><button type="button" onClick={removeImage}>移除</button></div>}
            {error && <p className="local-edit-message" role="alert">{error}</p>}
          </section>

          {source && <section className="template-card local-edit-brush-card"><header><div><span>02</span><strong>画笔选区</strong></div><em>MASK</em></header><label><span>画笔粗细 <b>{brushSize}%</b></span><input type="range" min="2" max="18" value={brushSize} disabled={selectionConfirmed} onChange={(event) => setBrushSize(Number(event.target.value))} /></label><div className="local-edit-confirm-actions">{selectionConfirmed ? <button type="button" onClick={() => { setSelectionConfirmed(false); setResultUrl(""); setPromptPlan(null); setNotice(""); }}>重新修改</button> : <button className="is-primary" type="button" disabled={!hasMask} onClick={() => { setSelectionConfirmed(true); setNotice("选区已确认。请填写编辑说明后开始编辑。"); }}>确认选区</button>}</div></section>}
          <section className="template-specs"><label className="local-edit-scope"><span>生成范围</span><select value={editScope} onChange={(event) => { setEditScope(event.target.value as "selected_only" | "whole_image"); setNotice(""); }}><option value="selected_only">只选区（默认）</option><option value="whole_image">参考选区调整整图</option></select></label><label><span>图片比例</span><select value={ratio} onChange={(event) => { setRatio(event.target.value); setNotice(""); }}>{["3:4", "1:1", "4:3", "9:16", "16:9"].map((item) => <option key={item}>{item}</option>)}</select></label><label><span>分辨率</span><select value={resolution} onChange={(event) => { setResolution(event.target.value); setNotice(""); }}>{["1K", "2K", "4K"].map((item) => <option key={item}>{item}</option>)}</select></label></section>
          {source && <label className="template-note local-edit-prompt"><span>编辑说明 <i>描述希望如何修改选区</i></span><textarea value={prompt} maxLength={300} onChange={(event) => { setPrompt(event.target.value); setNotice(""); }} placeholder="例如：将选中的抱枕改为浅灰色亚麻材质" /><small aria-hidden="true">{prompt.length}/300</small></label>}
          <div className="template-credit"><span>预计消耗积分<small>单次局部编辑 · 当前不会扣费</small></span><strong>8<i>分</i></strong></div>
          {source && <button className="template-generate" type="button" disabled={!selectionConfirmed || !prompt.trim() || generating} aria-describedby="local-edit-service-note" onClick={generate}><span>{generating ? "正在局部重绘…" : resultUrl ? "重新生成" : "开始编辑"}</span><em><Icon name="spark" /> EDIT</em></button>}
          <p id="local-edit-service-note" className="local-edit-service-note">默认只修改选区，选区外保留原图；系统会先生成严格的英文提示词 JSON，再连同原图与 Mask 提交 AI</p>
          {notice && <p className="local-edit-message" role="status">{notice}</p>}
          {promptPlan && <details className="local-edit-payload"><summary>查看本次 API 参数</summary><pre>{JSON.stringify(promptPlan, null, 2)}</pre></details>}
          {resultUrl && <a className="local-edit-download" href={resultUrl} target="_blank" rel="noreferrer">打开并下载生成结果</a>}
        </aside>
      </div>
    </main>
  );
}
