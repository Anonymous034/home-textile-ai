"use client";

import { ChangeEvent, DragEvent, PointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./PatternLab.css";

type Tool = "extract" | "recolor" | "enhance" | "redraw";
type IconName = "upload" | "extract" | "palette" | "image" | "magic" | "zoom" | "rotate" | "download" | "trash" | "back";
type PatternJob = { id: string; status: "queued" | "generating" | "completed" | "failed"; requested: number; completed: number; stage: string; error: string | null; result_urls: string[] };
type ResultImage = { url: string; label: string; parentUrl: string | null };
type FlowPath = { url: string; d: string };
type MaskPoint = { x: number; y: number };
type MaskStroke = { points: MaskPoint[]; size: number };
const API = (process.env.NEXT_PUBLIC_STUDIO_API ?? "").replace(/\/+$/, "");

function drawMask(context: CanvasRenderingContext2D, strokes: MaskStroke[], width: number, height: number, preview: boolean) {
  context.lineCap = "round";
  context.lineJoin = "round";
  context.strokeStyle = preview ? "rgba(145, 89, 255, .68)" : "#fff";
  context.fillStyle = preview ? "rgba(145, 89, 255, .68)" : "#fff";
  for (const stroke of strokes) {
    const radius = Math.max(4, stroke.size / 200 * Math.min(width, height));
    context.lineWidth = radius * 2;
    context.beginPath();
    stroke.points.forEach((point, index) => index ? context.lineTo(point.x * width, point.y * height) : context.moveTo(point.x * width, point.y * height));
    if (stroke.points.length === 1) {
      context.arc(stroke.points[0].x * width, stroke.points[0].y * height, radius, 0, Math.PI * 2);
      context.fill();
    } else context.stroke();
  }
}

function Icon({ name }: { name: IconName }) {
  const paths = {
    upload: <><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5"/><path d="M5 15v4h14v-4"/></>,
    extract: <><rect x="4" y="3" width="8" height="18" rx="2"/><path d="m12 9 5-3 3 2v8l-5 3-3-2"/></>,
    palette: <><path d="M12 3a9 9 0 0 0 0 18h1.4a2 2 0 0 0 1.6-3.2 1.9 1.9 0 0 1 1.5-3h1.2A3.3 3.3 0 0 0 21 11.5 8.7 8.7 0 0 0 12 3Z"/><circle cx="8" cy="10" r=".8"/><circle cx="11" cy="7" r=".8"/><circle cx="15" cy="8" r=".8"/></>,
    image: <><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 15-5-5L5 20"/></>,
    magic: <><path d="m15 4 5 5L9 20l-5-5Z"/><path d="m14 5-3 3M5 4v3M3.5 5.5h3M19 16v4M17 18h4"/></>,
    zoom: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5M10.5 7v7M7 10.5h7"/></>,
    rotate: <><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5"/></>,
    download: <><path d="M12 3v12m0 0 4-4m-4 4-4-4"/><path d="M4 18v3h16v-3"/></>,
    trash: <><path d="M4 7h16M9 7V4h6v3m3 0-1 14H7L6 7"/><path d="M10 11v6M14 11v6"/></>,
    back: <path d="m15 18-6-6 6-6"/>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

export default function PatternLab() {
  const inputRef = useRef<HTMLInputElement>(null);
  const workspaceRef = useRef<HTMLElement>(null);
  const sourceImageRef = useRef<HTMLElement>(null);
  const resultImageRefs = useRef(new Map<string, HTMLDivElement>());
  const resultNodeRefs = useRef(new Map<string, HTMLElement>());
  const previousResultCountRef = useRef(0);
  const scheduleFlowRef = useRef<() => void>(() => {});
  const [settingsPortalNode, setSettingsPortalNode] = useState<HTMLDivElement | null>(null);
  const settingsDialogRef = useRef<HTMLElement>(null);
  const objectUrlRef = useRef("");
  const requestIdRef = useRef<string | null>(null);
  const extractRequestIdRef = useRef<string | null>(null);
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; originX: number; originY: number } | null>(null);
  const resultDragRef = useRef<{ url: string; pointerId: number; startX: number; startY: number; originX: number; originY: number; moved: boolean } | null>(null);
  const maskCanvasRef = useRef<HTMLCanvasElement>(null);
  const strokesRef = useRef<MaskStroke[]>([]);
  const activeStrokeRef = useRef<MaskStroke | null>(null);
  const [image, setImage] = useState<{ name: string; url: string; file: File } | null>(null);
  const [resultImages, setResultImages] = useState<ResultImage[]>([]);
  const [resultPositions, setResultPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [draggingResultUrl, setDraggingResultUrl] = useState<string | null>(null);
  const [flowPaths, setFlowPaths] = useState<FlowPath[]>([]);
  const [activeResultUrl, setActiveResultUrl] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [selected, setSelected] = useState(false);
  const [settingsPopup, setSettingsPopup] = useState(false);
  const [tool, setTool] = useState<Tool>("recolor");
  const [redrawArmed, setRedrawArmed] = useState(false);
  const [sourceSize, setSourceSize] = useState<{ width: number; height: number } | null>(null);
  const [maskRevision, setMaskRevision] = useState(0);
  const [brushSize, setBrushSize] = useState(7);
  const [redrawPrompt, setRedrawPrompt] = useState("");
  const [redrawProgress, setRedrawProgress] = useState(0);
  const [redrawRequested, setRedrawRequested] = useState(0);
  const [redrawError, setRedrawError] = useState("");
  const [redrawing, setRedrawing] = useState(false);
  const [upscaleProgress, setUpscaleProgress] = useState(0);
  const [upscaleRequested, setUpscaleRequested] = useState(0);
  const [upscaleError, setUpscaleError] = useState("");
  const [upscaling, setUpscaling] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [count, setCount] = useState("4");
  const [patternJob, setPatternJob] = useState<PatternJob | null>(null);
  const [patternError, setPatternError] = useState("");
  const [generating, setGenerating] = useState(false);
  const [extractJob, setExtractJob] = useState<PatternJob | null>(null);
  const [extractError, setExtractError] = useState("");
  const [extracting, setExtracting] = useState(false);
  const busy = generating || extracting || upscaling || redrawing;

  const addResults = (urls: string[], label: string) => {
    setResultImages((current) => {
      const known = new Set(current.map((result) => result.url));
      const added = urls.filter((url) => { if (known.has(url)) return false; known.add(url); return true; });
      return [...current, ...added.map((url) => ({ url, label, parentUrl: activeResultUrl }))];
    });
  };
  const activeFile = async () => {
    if (!image) throw new Error("请先选择图片。");
    if (!activeResultUrl) return image.file;
    const response = await fetch(activeResultUrl, { signal: AbortSignal.timeout(30000) });
    if (!response.ok) throw new Error("无法读取选中的生成图片，请重试。");
    const blob = await response.blob();
    if (!blob.type.startsWith("image/")) throw new Error("选中的生成结果不是有效图片。");
    const extension = blob.type === "image/jpeg" ? "jpg" : blob.type === "image/webp" ? "webp" : "png";
    const file = new File([blob], `生成结果.${extension}`, { type: blob.type });
    return file;
  };
  const selectImage = (url: string | null) => {
    if (busy) return;
    if (activeResultUrl === url) { setSelected(true); return; }
    setActiveResultUrl(url);
    setSelected(true);
    setSettingsPopup(false);
    setTool("recolor");
    setRedrawArmed(false);
    setSourceSize(null);
    setRotation(0);
    strokesRef.current = [];
    activeStrokeRef.current = null;
    setMaskRevision(0);
    setPatternJob(null);
    setExtractJob(null);
    setPatternError("");
    setExtractError("");
    requestIdRef.current = null;
    extractRequestIdRef.current = null;
  };

  const clearMask = () => { strokesRef.current = []; activeStrokeRef.current = null; setMaskRevision(0); setRedrawProgress(0); setRedrawError(""); };
  const paintMask = useCallback(() => {
    const canvas = maskCanvasRef.current;
    if (!canvas || !sourceSize) return;
    if (canvas.width !== sourceSize.width || canvas.height !== sourceSize.height) { canvas.width = sourceSize.width; canvas.height = sourceSize.height; }
    const context = canvas.getContext("2d");
    if (!context) return;
    context.clearRect(0, 0, canvas.width, canvas.height);
    drawMask(context, strokesRef.current, canvas.width, canvas.height, true);
  }, [sourceSize]);
  useEffect(() => { paintMask(); }, [paintMask, maskRevision, redrawArmed]);
  useEffect(() => {
    if (!selected || !activeResultUrl) return;
    const frame = requestAnimationFrame(() => {
      resultNodeRefs.current.get(activeResultUrl)?.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
    });
    return () => cancelAnimationFrame(frame);
  }, [selected, activeResultUrl]);
  useEffect(() => {
    const added = resultImages.length > previousResultCountRef.current;
    previousResultCountRef.current = resultImages.length;
    if (!busy || !added) return;
    const frame = requestAnimationFrame(() => {
      resultNodeRefs.current.get(resultImages[resultImages.length - 1].url)?.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
    });
    return () => cancelAnimationFrame(frame);
  }, [resultImages.length, busy]);
  useEffect(() => {
    const workspace = workspaceRef.current;
    if (!workspace) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      event.stopPropagation();
      setZoom((value) => Math.min(1.6, Math.max(.1, Number((value + (event.deltaY < 0 ? .1 : -.1)).toFixed(2)))));
    };
    workspace.addEventListener("wheel", onWheel, { passive: false });
    return () => workspace.removeEventListener("wheel", onWheel);
  }, [image]);
  useEffect(() => {
    const workspace = workspaceRef.current;
    const source = sourceImageRef.current;
    if (!workspace || !source || resultImages.length === 0) { setFlowPaths([]); return; }
    const updateLines = () => {
      const origin = workspace.getBoundingClientRect();
      const paths = resultImages.flatMap((result) => {
        const parent = result.parentUrl ? resultImageRefs.current.get(result.parentUrl) : source;
        const child = resultImageRefs.current.get(result.url);
        if (!parent || !child) return [];
        const from = parent.getBoundingClientRect();
        const to = child.getBoundingClientRect();
        const cx = (rect: DOMRect) => (rect.left + rect.right) / 2 - origin.left;
        const cy = (rect: DOMRect) => (rect.top + rect.bottom) / 2 - origin.top;
        let d: string;
        if (to.top >= from.bottom + 16) {
          const x1 = cx(from), y1 = from.bottom - origin.top, x2 = cx(to), y2 = to.top - origin.top - 6;
          const middle = (y1 + y2) / 2;
          d = `M ${x1} ${y1} V ${middle} H ${x2} V ${y2}`;
        } else {
          const rightward = cx(to) >= cx(from);
          const x1 = (rightward ? from.right : from.left) - origin.left;
          const x2 = (rightward ? to.left - 6 : to.right + 6) - origin.left;
          const middle = (x1 + x2) / 2;
          d = `M ${x1} ${cy(from)} H ${middle} V ${cy(to)} H ${x2}`;
        }
        return [{ url: result.url, d }];
      });
      setFlowPaths((current) => current.length === paths.length && current.every((path, index) => path.url === paths[index].url && path.d === paths[index].d) ? current : paths);
    };
    let frame = requestAnimationFrame(updateLines);
    const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(updateLines); };
    scheduleFlowRef.current = schedule;
    const observer = new ResizeObserver(schedule);
    observer.observe(workspace);
    observer.observe(source);
    resultImageRefs.current.forEach((element) => observer.observe(element));
    window.addEventListener("resize", schedule);
    return () => { scheduleFlowRef.current = () => {}; cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener("resize", schedule); };
  }, [image, resultImages, zoom, position, selected, activeResultUrl, tool, settingsPopup]);
  useEffect(() => { scheduleFlowRef.current(); }, [resultPositions]);
  useEffect(() => {
    if (!settingsPopup) return;
    settingsDialogRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") setSettingsPopup(false); };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [settingsPopup]);

  useEffect(() => () => { if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current); }, []);
  const applyFile = (file?: File) => {
    if (busy) return;
    if (!file || !file.type.startsWith("image/")) return;
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    const url = URL.createObjectURL(file); objectUrlRef.current = url; setImage({ name: file.name, url, file }); setResultImages([]); setResultPositions({}); setDraggingResultUrl(null); setActiveResultUrl(null); setSelected(false); setSettingsPopup(false); setTool("recolor"); setZoom(1); setRotation(0); setPosition({ x: 0, y: 0 }); setPatternJob(null); setPatternError(""); setExtractJob(null); setExtractError(""); setUpscaleError(""); setUpscaleProgress(0); setUpscaleRequested(0); clearMask(); setRedrawPrompt(""); setRedrawRequested(0); setRedrawArmed(false); setSourceSize(null); requestIdRef.current = null; extractRequestIdRef.current = null;
  };
  const chooseFile = (event: ChangeEvent<HTMLInputElement>) => { applyFile(event.target.files?.[0]); event.target.value = ""; };
  const drop = (event: DragEvent<HTMLElement>) => { event.preventDefault(); setDragging(false); applyFile(event.dataTransfer.files?.[0]); };
  const remove = () => {
    if (busy) return;
    if (activeResultUrl) {
      setResultImages((current) => {
        const parentUrl = current.find((result) => result.url === activeResultUrl)?.parentUrl ?? null;
        return current.filter((result) => result.url !== activeResultUrl).map((result) => result.parentUrl === activeResultUrl ? { ...result, parentUrl } : result);
      });
      setResultPositions((current) => { const next = { ...current }; delete next[activeResultUrl]; return next; });
      setActiveResultUrl(null);
      setSelected(false);
      setSettingsPopup(false);
      setPatternJob(null);
      setExtractJob(null);
      requestIdRef.current = null;
      extractRequestIdRef.current = null;
      return;
    }
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = "";
    setImage(null); setResultImages([]); setResultPositions({}); setDraggingResultUrl(null); setSelected(false); setSettingsPopup(false); setTool("recolor"); setPatternJob(null); setPatternError(""); setExtractJob(null); setExtractError(""); setUpscaleError(""); setUpscaleProgress(0); setUpscaleRequested(0); clearMask(); setRedrawPrompt(""); setRedrawRequested(0); setRedrawArmed(false); setSourceSize(null); requestIdRef.current = null; extractRequestIdRef.current = null;
  };
  const download = () => { if (!image) return; const link = document.createElement("a"); link.href = activeResultUrl || image.url; link.download = activeResultUrl ? "生成结果.png" : image.name; link.click(); };
  const startMove = (event: PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    event.preventDefault(); event.stopPropagation(); selectImage(null);
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, originX: position.x, originY: position.y };
  };
  const moveCanvas = (event: PointerEvent<HTMLElement>) => {
    const drag = dragRef.current; if (!drag || drag.pointerId !== event.pointerId) return;
    setPosition({ x: drag.originX + event.clientX - drag.startX, y: drag.originY + event.clientY - drag.startY });
  };
  const endMove = (event: PointerEvent<HTMLElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const startResultMove = (event: PointerEvent<HTMLDivElement>, url: string, editing: boolean) => {
    if (editing || busy || event.button !== 0 || !event.isPrimary) return;
    event.preventDefault();
    event.stopPropagation();
    const origin = resultPositions[url] ?? { x: 0, y: 0 };
    resultDragRef.current = { url, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, originX: origin.x, originY: origin.y, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const moveResult = (event: PointerEvent<HTMLDivElement>, url: string) => {
    const drag = resultDragRef.current;
    if (!drag || drag.url !== url || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    if (!drag.moved && Math.hypot(dx, dy) < 5) return;
    if (!drag.moved) { drag.moved = true; setDraggingResultUrl(url); }
    setResultPositions((current) => ({ ...current, [url]: { x: drag.originX + dx / zoom, y: drag.originY + dy / zoom } }));
  };
  const endResultMove = (event: PointerEvent<HTMLDivElement>, url: string, cancelled = false) => {
    const drag = resultDragRef.current;
    if (!drag || drag.url !== url || drag.pointerId !== event.pointerId) return;
    event.stopPropagation();
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    resultDragRef.current = null;
    setDraggingResultUrl(null);
    if (!drag.moved && !cancelled) selectImage(url);
  };
  const tools: { id: Tool; label: string; icon: IconName }[] = [
    { id: "extract", label: "设计提取", icon: "extract" }, { id: "recolor", label: "一花多色", icon: "palette" },
    { id: "enhance", label: "一键高清", icon: "image" }, { id: "redraw", label: "局部重绘", icon: "magic" },
  ];

  const maskPoint = (event: PointerEvent<HTMLCanvasElement>): MaskPoint => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return { x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)), y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)) };
  };
  const beginStroke = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!redrawArmed || busy || event.button !== 0 || !event.isPrimary) return;
    event.preventDefault(); event.stopPropagation();
    const stroke = { points: [maskPoint(event)], size: brushSize };
    strokesRef.current.push(stroke);
    activeStrokeRef.current = stroke;
    event.currentTarget.setPointerCapture(event.pointerId);
    setMaskRevision((value) => value + 1);
  };
  const continueStroke = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!activeStrokeRef.current) return;
    event.preventDefault(); event.stopPropagation();
    activeStrokeRef.current.points.push(maskPoint(event));
    paintMask();
  };
  const endStroke = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!activeStrokeRef.current) return;
    event.stopPropagation();
    activeStrokeRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    setMaskRevision((value) => value + 1);
  };
  const undoStroke = () => { strokesRef.current.pop(); setMaskRevision((value) => strokesRef.current.length ? value + 1 : 0); setRedrawProgress(0); setRedrawError(""); };
  const maskBlob = async () => {
    if (!sourceSize) throw new Error("图片尚未读取完成。");
    const canvas = document.createElement("canvas");
    canvas.width = sourceSize.width; canvas.height = sourceSize.height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("无法生成画笔选区。");
    context.fillStyle = "#000"; context.fillRect(0, 0, canvas.width, canvas.height);
    drawMask(context, strokesRef.current, canvas.width, canvas.height, false);
    return new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("无法导出画笔选区。")), "image/png"));
  };
  const generateUpscale = async () => {
    if (!image || busy) return;
    setSettingsPopup(false);
    setUpscaling(true); setUpscaleProgress(0); setUpscaleError("");
    const requested = Number(count);
    let completed = 0;
    setUpscaleRequested(requested);
    let input: File;
    try { input = await activeFile(); }
    catch (reason) { setUpscaleError(reason instanceof Error ? reason.message : "无法读取选中的图片。"); setUpscaling(false); return; }
    for (let index = 0; index < requested; index += 1) {
      try {
        const form = new FormData();
        form.append("image", input, input.name);
        form.append("mode", "detail");
        const response = await fetch(`${API}/api/upscale/generate`, { method: "POST", body: form, signal: AbortSignal.timeout(360000) });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "一键高清处理失败。");
        const url = `${API}${data.result_url}`;
        addResults([url], "一键高清");
        completed += 1;
        setUpscaleProgress(index + 1);
      } catch (reason) {
        setUpscaleError(reason instanceof Error ? reason.message : "无法连接 AI 高清服务。");
        break;
      }
    }
    setUpscaling(false);
    if (completed > 0) { setSelected(true); setSettingsPopup(true); }
  };
  const generateRedraw = async () => {
    if (!image || busy || !sourceSize || !strokesRef.current.length || !redrawPrompt.trim()) return;
    setSettingsPopup(false);
    setRedrawing(true); setRedrawProgress(0); setRedrawError("");
    const requested = Number(count);
    let completed = 0;
    setRedrawRequested(requested);
    try {
      const input = await activeFile();
      const mask = await maskBlob();
      for (let index = 0; index < requested; index += 1) {
        const form = new FormData();
        form.append("image", input, input.name);
        form.append("mask", mask, "mask.png");
        form.append("requirement", redrawPrompt.trim());
        const response = await fetch(`${API}/api/local-edit/generate`, { method: "POST", body: form, signal: AbortSignal.timeout(360000) });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "局部重绘失败。");
        const url = `${API}${data.result_url}`;
        addResults([url], "局部重绘");
        completed += 1;
        setRedrawProgress(index + 1);
      }
    } catch (reason) {
      setRedrawError(reason instanceof Error ? reason.message : "无法连接 AI 局部重绘服务。");
    } finally {
      setRedrawing(false);
      if (completed > 0) { setSelected(true); setSettingsPopup(true); }
    }
  };
  const confirmLabel = tool === "enhance" ? "开始高清" : "开始重绘";
  const extractDesign = async () => {
    if (!image || busy) return;
    setSettingsPopup(false);
    if (extractJob?.status === "completed") {
      document.getElementById("pattern-gallery")?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    setExtracting(true);
    setExtractError("");
    try {
      let current = extractJob;
      if (!current || (current.status !== "queued" && current.status !== "generating")) {
        if (current) extractRequestIdRef.current = null;
        extractRequestIdRef.current ??= crypto.randomUUID();
        const form = new FormData();
        const input = await activeFile();
        form.append("image", input, input.name);
        form.append("count", "1");
        form.append("strength", "适度");
        form.append("color_mode", "保持配色");
        form.append("action", "design_extract");
        form.append("request_id", extractRequestIdRef.current);
        const created = await fetch(`${API}/api/pattern/jobs`, { method: "POST", body: form, signal: AbortSignal.timeout(30000) });
        const payload = await created.json();
        if (!created.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "无法启动图案提取。");
        current = payload as PatternJob;
        setExtractJob(current);
        addResults(current.result_urls.map((url) => `${API}${url}`), "设计提取");
      }
      while (current.status === "queued" || current.status === "generating") {
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
        const response = await fetch(`${API}/api/pattern/jobs/${current.id}`, { cache: "no-store", signal: AbortSignal.timeout(10000) });
        const next = await response.json();
        if (!response.ok) throw new Error(typeof next.detail === "string" ? next.detail : "无法读取提取进度。");
        current = next as PatternJob;
        setExtractJob(current);
        addResults(current.result_urls.map((url) => `${API}${url}`), "设计提取");
      }
      if (current.status === "failed") setExtractError(current.error || "图案提取失败。");
      addResults(current.result_urls.map((url) => `${API}${url}`), "设计提取");
      if (current.status === "completed" && current.result_urls.length > 0) { setSelected(true); setSettingsPopup(true); }
    } catch (reason) {
      setExtractError(reason instanceof Error ? reason.message : "无法连接 AI 服务。");
    } finally {
      setExtracting(false);
    }
  };
  const confirmTool = async () => {
    if (tool === "extract") { await extractDesign(); return; }
    if (tool === "enhance") { await generateUpscale(); return; }
    if (tool === "redraw") { await generateRedraw(); return; }
    if (!image || busy) return;
    setSettingsPopup(false);
    setGenerating(true);
    setPatternError("");
    try {
      let current = patternJob;
      if (!current || (current.status !== "queued" && current.status !== "generating")) {
        if (current) requestIdRef.current = null;
        requestIdRef.current ??= crypto.randomUUID();
        setPatternJob(null);
        const form = new FormData();
        const input = await activeFile();
        form.append("image", input, input.name);
        form.append("count", "4");
        form.append("strength", "适度");
        form.append("color_mode", "智能配色");
        form.append("notes", "");
        form.append("action", tool);
        form.append("request_id", requestIdRef.current);
        const created = await fetch(`${API}/api/pattern/jobs`, { method: "POST", body: form, signal: AbortSignal.timeout(30000) });
        const payload = await created.json();
        if (!created.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "无法启动花型生成任务。");
        current = payload as PatternJob;
        setPatternJob(current);
        addResults(current.result_urls.map((url) => `${API}${url}`), "一花多色");
      }
      while (current.status === "queued" || current.status === "generating") {
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
        const response = await fetch(`${API}/api/pattern/jobs/${current.id}`, { cache: "no-store", signal: AbortSignal.timeout(10000) });
        const next = await response.json();
        if (!response.ok) {
          if (response.status === 404) setPatternJob({ ...current, status: "failed", error: "后端已重启，原任务进度不可读取。" });
          throw new Error(typeof next.detail === "string" ? next.detail : "无法读取生成进度。");
        }
        current = next as PatternJob;
        setPatternJob(current);
        addResults(current.result_urls.map((url) => `${API}${url}`), "一花多色");
      }
      if (current.status === "failed") setPatternError(current.error || "花型生成未完成。");
      addResults(current.result_urls.map((url) => `${API}${url}`), "一花多色");
      if (current.status === "completed" && current.result_urls.length > 0) { setSelected(true); setSettingsPopup(true); }
    } catch (reason) {
      setPatternError(reason instanceof Error ? reason.message : "无法连接 AI 服务。");
    } finally {
      setGenerating(false);
    }
  };

  const settingsPanel = <section className={`pattern-settings ${tool === "extract" || tool === "recolor" ? "pattern-settings--confirm" : ""}`} ref={settingsDialogRef} tabIndex={-1} role={settingsPopup ? "dialog" : undefined} aria-modal={settingsPopup ? true : undefined} aria-label={settingsPopup ? `${tools.find((item) => item.id === tool)?.label}设置` : undefined} onClick={(event) => event.stopPropagation()}>{tool === "extract" ? <button type="button" onClick={confirmTool} disabled={busy}>{extracting ? "提取中…" : extractJob?.status === "completed" ? "查看提取结果" : extractJob?.status === "queued" || extractJob?.status === "generating" ? "继续查看进度" : extractJob?.status === "failed" ? "重试设计提取" : "确认设计提取"}</button> : tool === "recolor" ? <button type="button" onClick={confirmTool} disabled={busy}>{generating ? "生成中…" : patternJob?.status === "queued" || patternJob?.status === "generating" ? "继续查看进度" : patternJob?.status === "failed" ? "重试一花多色" : "确认一花多色"}</button> : <><header><strong>{tool === "enhance" ? "一键高清设置" : "局部重绘设置"}</strong><span>{tool === "redraw" ? "涂抹区域后填写说明" : `将生成 ${count} 张`}</span><button type="button" onClick={confirmTool} disabled={busy || (tool === "redraw" && (!maskRevision || !redrawPrompt.trim() || !sourceSize))}>{upscaling ? `高清处理中 ${upscaleProgress}/${count}` : redrawing ? `重绘中 ${redrawProgress}/${count}` : confirmLabel}</button></header>
        {tool === "redraw" ? <><textarea value={redrawPrompt} onChange={(event) => setRedrawPrompt(event.target.value)} maxLength={300} placeholder="描述希望如何修改涂抹区域，例如将被套上的花纹改成蓝色植物纹" aria-label="局部重绘文字说明"/><p className="pattern-brush-hint">在上方图片上涂抹需要修改的区域，再输入文字说明。</p><div className="pattern-options pattern-options--single"><label><span>生成张数</span><select value={count} disabled={busy} onChange={(event) => setCount(event.target.value)}><option value="2">2张</option><option value="4">4张</option><option value="6">6张</option><option value="8">8张</option></select></label></div></> : <div className="pattern-options pattern-options--single"><label><span>生成张数</span><select value={count} disabled={busy} onChange={(event) => setCount(event.target.value)}><option value="2">2张</option><option value="4">4张</option><option value="6">6张</option><option value="8">8张</option></select></label></div>}</>}
      </section>;
  const toolBar = <nav className="pattern-tools" aria-label="图片处理工具" onClick={(event) => event.stopPropagation()}>
    {tools.map((item) => <button type="button" key={item.id} className={tool === item.id ? "is-active" : ""} disabled={busy} onClick={() => { setTool(item.id); setRedrawArmed(item.id === "redraw"); if (item.id === "redraw") setRotation(0); }}><Icon name={item.icon}/><span>{item.label}</span></button>)}
    <i className="pattern-tools__divider"/><button type="button" aria-label="放大所有图片" onClick={() => setZoom((value) => Math.min(1.6, value + .1))}><Icon name="zoom"/></button><button type="button" aria-label="旋转当前图片" disabled={redrawArmed || busy} onClick={() => setRotation((value) => value + 90)}><Icon name="rotate"/></button><button type="button" aria-label="下载当前图片" onClick={download}><Icon name="download"/></button><button type="button" aria-label="删除当前图片" onClick={remove}><Icon name="trash"/></button>
  </nav>;
  const brushControls = <div className="pattern-brush-controls"><label>画笔粗细 <input type="range" min="2" max="18" value={brushSize} disabled={busy} onClick={(event) => event.stopPropagation()} onChange={(event) => setBrushSize(Number(event.target.value))}/><span>{brushSize}%</span></label><button type="button" disabled={busy || !maskRevision} onClick={(event) => { event.stopPropagation(); undoStroke(); }}>撤销一笔</button><button type="button" disabled={busy || !maskRevision} onClick={(event) => { event.stopPropagation(); clearMask(); }}>清除选区</button></div>;
  const sourceRedraw = redrawArmed && !activeResultUrl;

  return <main className="pattern-maker">
    <header className="pattern-maker__top"><a href="/dashboard?tool=pattern"><Icon name="back"/>返回工作台</a><strong>花型制作</strong><span>AI PATTERN STUDIO</span></header>
    <div ref={setSettingsPortalNode}/>
    {image && selected && settingsPopup && settingsPortalNode && createPortal(
      <div className="pattern-settings-overlay" onClick={() => setSettingsPopup(false)}>
        <div className="pattern-settings-dialog" onClick={(event) => event.stopPropagation()}>
          <button type="button" className="pattern-settings-close" aria-label="关闭设置" onClick={() => setSettingsPopup(false)}>×</button>
          {settingsPanel}
        </div>
      </div>, settingsPortalNode
    )}
    <input ref={inputRef} className="pattern-file" type="file" accept="image/jpeg,image/png,image/webp" onChange={chooseFile}/>
    {!image ? <section className={`pattern-upload ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}>
      <button type="button" onClick={() => inputRef.current?.click()}><i><Icon name="upload"/></i><strong>点击或拖入花型图片</strong><span>支持 JPG、PNG、WebP，建议使用清晰原图</span><em>选择图片</em></button>
    </section> : <section ref={workspaceRef} className={`pattern-workspace ${selected ? "is-selected" : ""} ${resultImages.length ? "has-results" : ""}`} onClick={(event) => { if (event.target === event.currentTarget) setSelected(false); }} onDragOver={(event) => event.preventDefault()} onDrop={drop}>
      {flowPaths.length > 0 && <svg className="pattern-flow-lines" aria-hidden="true"><defs><marker id="pattern-flow-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 1 1 L 9 5 L 1 9 Z"/></marker></defs>{flowPaths.map((path) => <path key={path.url} className="pattern-flow-line" d={path.d} markerEnd="url(#pattern-flow-arrow)" pathLength={1}/>)}</svg>}
      <div className="pattern-canvas" style={{ transform: `translate3d(${position.x}px, ${position.y}px, 0)`, zoom }}>
      {selected && !activeResultUrl && toolBar}
      {selected && !activeResultUrl && redrawArmed && brushControls}
      <div className="pattern-image-stage"><figure ref={sourceImageRef} role={sourceRedraw ? undefined : "button"} tabIndex={sourceRedraw ? -1 : 0} aria-label={sourceRedraw ? "在图片上用画笔涂抹需要重绘的区域" : "点击选择原图；拖拽移动画布，Ctrl 加滚轮缩放所有图片"} onPointerDown={sourceRedraw ? undefined : startMove} onPointerMove={sourceRedraw ? undefined : moveCanvas} onPointerUp={sourceRedraw ? undefined : endMove} onPointerCancel={sourceRedraw ? undefined : endMove} onClick={(event) => { event.stopPropagation(); selectImage(null); }} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectImage(null); } }}>
        {sourceRedraw ? <div className="pattern-edit-surface" style={{ aspectRatio: sourceSize ? `${sourceSize.width} / ${sourceSize.height}` : "1 / 1", width: sourceSize && sourceSize.width < sourceSize.height ? "auto" : "100%", height: sourceSize && sourceSize.width < sourceSize.height ? "100%" : "auto" }}><img src={image.url} alt="待局部重绘的原图" draggable={false} onLoad={(event) => setSourceSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}/><canvas ref={maskCanvasRef} aria-label="画笔选区：在图片上涂抹需要重绘的区域" onPointerDown={beginStroke} onPointerMove={continueStroke} onPointerUp={endStroke} onPointerCancel={endStroke}/></div> : <img src={image.url} alt="当前花型图片" draggable={false} style={{ transform: `rotate(${!activeResultUrl ? rotation : 0}deg)` }}/>}
        <figcaption><b>1</b></figcaption></figure><button type="button" className="pattern-replace" disabled={busy} onClick={(event) => { event.stopPropagation(); inputRef.current?.click(); }}>更换图片</button></div>
      {selected && !activeResultUrl && !settingsPopup && settingsPanel}
      </div>
      {(extracting || extractError || upscaling || upscaleError || redrawing || redrawError || generating || patternError) && <section className="pattern-generation-status" style={{ zoom }} aria-live="polite">
        {extracting && <p>正在提取设计…</p>}{extractError && <p role="alert">{extractError}</p>}
        {upscaling && <p>高清处理中 {upscaleProgress} / {upscaleRequested} 张</p>}{upscaleError && <p role="alert">{upscaleError}</p>}
        {redrawing && <p>局部重绘中 {redrawProgress} / {redrawRequested} 张</p>}{redrawError && <p role="alert">{redrawError}</p>}
        {generating && <p>{patternJob?.stage || "花型生成中…"}</p>}{patternError && <p role="alert">{patternError}</p>}
      </section>}
      {resultImages.length > 0 && <section id="pattern-gallery" className="pattern-gallery" style={{ zoom }} aria-live="polite">
        <header><strong>生成结果</strong><span>{resultImages.length} 张 · 点击选择，拖动调整位置</span></header>
        <div className="pattern-gallery__grid">{resultImages.map((result, index) => {
          const active = selected && activeResultUrl === result.url;
          const editing = active && redrawArmed;
          const offset = resultPositions[result.url] ?? { x: 0, y: 0 };
          return <article ref={(element) => { if (element) resultNodeRefs.current.set(result.url, element); else resultNodeRefs.current.delete(result.url); }} className={`pattern-result-node ${active ? "is-active" : ""} ${draggingResultUrl === result.url ? "is-dragging" : ""}`} key={result.url} style={{ transform: active ? "translate3d(0, 0, 0)" : `translate3d(${offset.x}px, ${offset.y}px, 0)` }}>
            {active && toolBar}
            {editing && brushControls}
            <div ref={(element) => { if (element) resultImageRefs.current.set(result.url, element); else resultImageRefs.current.delete(result.url); }} className="pattern-extraction__card pattern-result-image" role={editing ? undefined : "button"} tabIndex={editing ? -1 : 0} aria-label={editing ? "在生成图片上涂抹需要重绘的区域" : `选择或拖动${result.label}结果 ${index + 1}`} onPointerDown={(event) => startResultMove(event, result.url, editing)} onPointerMove={(event) => moveResult(event, result.url)} onPointerUp={(event) => endResultMove(event, result.url)} onPointerCancel={(event) => endResultMove(event, result.url, true)} onLostPointerCapture={(event) => endResultMove(event, result.url, true)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectImage(result.url); } }}>
              {editing ? <div className="pattern-edit-surface"><img src={result.url} alt={`待局部重绘的${result.label}结果`} draggable={false} onLoad={(event) => setSourceSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}/><canvas ref={maskCanvasRef} aria-label="画笔选区：在生成图片上涂抹需要重绘的区域" onPointerDown={beginStroke} onPointerMove={continueStroke} onPointerUp={endStroke} onPointerCancel={endStroke}/></div> : <img src={result.url} alt={`${result.label}结果 ${index + 1}`} draggable={false} style={{ transform: `rotate(${active ? rotation : 0}deg)` }}/>}
              <span className="pattern-extraction__number">{index + 2}</span><strong className="pattern-extraction__label">{result.label}</strong>
            </div>
            <a className="pattern-result-download" href={result.url} download={`${result.label}-${index + 1}.png`} onClick={(event) => event.stopPropagation()}>下载图片</a>
            {active && !settingsPopup && settingsPanel}
          </article>;
        })}</div>
      </section>}
    </section>}
  </main>;
}
