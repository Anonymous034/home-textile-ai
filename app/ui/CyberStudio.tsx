"use client";

import { ChangeEvent, PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import "./CyberStudio.css";

const modes = [
  { id: "model", number: "01", icon: "♙", label: "换模特", note: "保留产品，重新生成展示人物" },
  { id: "scene", number: "02", icon: "⌂", label: "换场景", note: "保留产品，替换家纺空间背景" },
  { id: "layout", number: "03", icon: "▦", label: "换构图", note: "保留素材，重新安排画面位置" },
];

type PresetKind = "model" | "scene" | "composition";
type Capabilities = { provider: string; supported_resolutions: string[]; message: string };
type StudioConnection = { connected: boolean; error_code?: string | null; message: string };

type Preset = {
  id: string;
  name: string;
  preview_url?: string | null;
  updated_at?: string | null;
  gender?: string | null;
  style_tag?: string | null;
  scene_type?: string | null;
  description?: string | null;
};

const API = (process.env.NEXT_PUBLIC_STUDIO_API ?? "").replace(/\/+$/, "");
const presetImageUrl = (preset: Preset, quality: "thumb" | "hd") => {
  const version = preset.updated_at ? `&v=${encodeURIComponent(preset.updated_at)}` : "";
  return `${API}${preset.preview_url}?quality=${quality}${version}`;
};
const presetConfig: Record<string, { kind: PresetKind; title: string; endpoint: string }> = {
  model: { kind: "model", title: "选择模特", endpoint: "models" },
  scene: { kind: "scene", title: "选择场景", endpoint: "scenes" },
  layout: { kind: "composition", title: "选择构图", endpoint: "compositions" },
};

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const outputSize = (aspect: string, resolution: string) => {
  const [a, b] = aspect.split(":").map(Number);
  const edge = { "1K": 1024, "2K": 2048, "4K": 4096 }[resolution] ?? 2048;
  if (a >= b) return [edge, Math.max(64, Math.round(edge * b / a / 64) * 64)];
  return [Math.max(64, Math.round(edge * a / b / 64) * 64), edge];
};

export default function CyberStudio() {
  const rootRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<HTMLDivElement>(null);
  const generateRef = useRef<HTMLButtonElement>(null);
  const mainImageRef = useRef<string | null>(null);
  const extraImageRef = useRef<string | null>(null);
  const dragRef = useRef({ active: false, x: 0, y: 0, baseX: 0, baseY: 0 });
  const viewRef = useRef({ x: 0, y: 0, zoom: 100 });
  const [zoom, setZoom] = useState(100);
  const [mode, setMode] = useState("model");
  const [collapsed, setCollapsed] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [complete, setComplete] = useState(false);
  const [mainImage, setMainImage] = useState<string | null>(null);
  const [extraImage, setExtraImage] = useState<string | null>(null);
  const [mainFile, setMainFile] = useState<File | null>(null);
  const [extraFile, setExtraFile] = useState<File | null>(null);
  const [resultImage, setResultImage] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [jobStage, setJobStage] = useState("等待生成任务");
  const [generateError, setGenerateError] = useState("");
  const [aspectRatio, setAspectRatio] = useState("3:4");
  const [resolution, setResolution] = useState("2K");
  const [pendingResolution, setPendingResolution] = useState<string | null>(null);
  const [presetPanel, setPresetPanel] = useState<PresetKind | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetLoading, setPresetLoading] = useState(false);
  const [presetError, setPresetError] = useState("");
  const [pendingPreset, setPendingPreset] = useState<{ kind: PresetKind; preset: Preset } | null>(null);
  const [selectedPresets, setSelectedPresets] = useState<Partial<Record<PresetKind, Preset>>>({});
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [studioConnection, setStudioConnection] = useState<StudioConnection | null>(null);
  const [backendOnline, setBackendOnline] = useState(false);

  const resolutionSupported = capabilities?.supported_resolutions.includes(resolution) ?? resolution === "2K";
  const [outputWidth, outputHeight] = outputSize(aspectRatio, resolution);
  const [pendingOutputWidth, pendingOutputHeight] = outputSize(aspectRatio, pendingResolution ?? resolution);

  const confirmResolution = () => {
    if (!pendingResolution) return;
    setResolution(pendingResolution);
    setPendingResolution(null);
    setComplete(false);
    setResultImage(null);
    setGenerateError("");
  };

  useEffect(() => {
    fetch(`${API}/api/provider-capabilities`, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("服务不可用");
        const value = await response.json() as Capabilities;
        setCapabilities(value);
        setBackendOnline(true);
        if (!value.supported_resolutions.includes(resolution) && value.supported_resolutions.includes("2K")) setResolution("2K");
      })
      .catch(() => {
        setBackendOnline(false);
        setGenerateError("本地生成服务未启动。请双击项目里的“启动本地网站.cmd”，然后刷新页面。");
      });
  }, []);

  const openPresetDatabase = async (modeId: string) => {
    const config = presetConfig[modeId];
    setMode(modeId);
    setPresetPanel(config.kind);
    setPendingPreset(null);
    setPresetLoading(true);
    setPresetError("");
    setPresets([]);
    try {
      const response = await fetch(`${API}/api/presets/${config.endpoint}`, { cache: "no-store" });
      if (!response.ok) throw new Error("预设资料库暂时无法读取");
      const payload = await response.json();
      setPresets(payload.items ?? []);
    } catch (error) {
      setPresetError(error instanceof Error ? error.message : "预设资料库暂时无法读取");
    } finally {
      setPresetLoading(false);
    }
  };

  const applyView = (animate = true) => {
    const target = viewportRef.current;
    if (!target) return;
    const view = viewRef.current;
    gsap.to(target, {
      x: view.x,
      y: view.y,
      scale: view.zoom / 100,
      duration: animate ? 0.45 : 0,
      ease: "power3.out",
      overwrite: "auto",
    });
  };

  const changeZoom = (amount: number) => {
    const next = clamp(viewRef.current.zoom + amount, 50, 160);
    viewRef.current.zoom = next;
    setZoom(next);
    applyView();
  };

  const resetView = () => {
    viewRef.current = { x: 0, y: 0, zoom: 100 };
    setZoom(100);
    applyView();
  };

  useEffect(() => {
    const root = rootRef.current;
    const canvas = canvasRef.current;
    if (!root || !canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    let frame = 0;
    let width = 0;
    let height = 0;
    let time = 0;
    const pointer = { x: -1000, y: -1000, tx: -1000, ty: -1000 };
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const resize = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = root.clientWidth;
      height = root.clientHeight;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    };

    const draw = () => {
      pointer.x += (pointer.tx - pointer.x) * 0.075;
      pointer.y += (pointer.ty - pointer.y) * 0.075;
      time += reduceMotion ? 0 : 0.012;
      context.clearRect(0, 0, width, height);

      const spacing = width < 700 ? 32 : 42;
      const glow = context.createRadialGradient(pointer.x, pointer.y, 0, pointer.x, pointer.y, 280);
      glow.addColorStop(0, "rgba(0,242,254,.12)");
      glow.addColorStop(0.45, "rgba(79,172,254,.055)");
      glow.addColorStop(1, "rgba(79,172,254,0)");
      context.fillStyle = glow;
      context.fillRect(0, 0, width, height);

      for (let y = 0; y <= height + spacing; y += spacing) {
        for (let x = 0; x <= width + spacing; x += spacing) {
          const dx = pointer.x - x;
          const dy = pointer.y - y;
          const distance = Math.hypot(dx, dy);
          const force = Math.max(0, 1 - distance / 250);
          const wave = Math.sin(time + x * 0.009 + y * 0.006) * 1.2;
          const px = x + (distance ? dx / distance : 0) * force * 12;
          const py = y + (distance ? dy / distance : 0) * force * 12 + wave;
          context.beginPath();
          context.arc(px, py, 0.75 + force * 1.4, 0, Math.PI * 2);
          context.fillStyle = force > 0.05
            ? `rgba(0,242,254,${0.16 + force * 0.6})`
            : "rgba(154,169,205,.13)";
          context.fill();
        }
      }
      frame = requestAnimationFrame(draw);
    };

    const onPointer = (event: PointerEvent) => {
      const rect = root.getBoundingClientRect();
      pointer.tx = event.clientX - rect.left;
      pointer.ty = event.clientY - rect.top;
      root.style.setProperty("--pointer-x", `${pointer.tx}px`);
      root.style.setProperty("--pointer-y", `${pointer.ty}px`);
    };

    resize();
    window.addEventListener("resize", resize);
    root.addEventListener("pointermove", onPointer);
    frame = requestAnimationFrame(draw);
    const gsapContext = gsap.context(() => {
      gsap.from(".cyber-hud", { y: -30, autoAlpha: 0, duration: 0.8, ease: "power3.out" });
      gsap.from(".cyber-dock", {
        x: 60,
        autoAlpha: 0,
        duration: 0.9,
        ease: "power3.out",
        clearProps: "transform,opacity,visibility",
      });
      gsap.from(".cyber-node", { scale: 0.82, autoAlpha: 0, duration: 0.9, ease: "back.out(1.35)" });
    }, root);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      root.removeEventListener("pointermove", onPointer);
      gsapContext.revert();
    };
  }, []);

  useEffect(() => () => {
    if (mainImageRef.current) URL.revokeObjectURL(mainImageRef.current);
    if (extraImageRef.current) URL.revokeObjectURL(extraImageRef.current);
  }, []);

  useEffect(() => {
    let active = true;
    const checkConnection = async () => {
      try {
        const response = await fetch(`${API}/api/ai/connections`, { cache: "no-store" });
        if (!response.ok) throw new Error("连接状态暂时无法读取");
        const value = await response.json() as { studio_image: StudioConnection };
        if (active) setStudioConnection(value.studio_image);
      } catch {
        if (active) setStudioConnection({ connected: false, message: "本地后端暂时无法连接。" });
      }
    };
    void checkConnection();
    const timer = window.setInterval(() => { void checkConnection(); }, 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const chooseImage = (event: ChangeEvent<HTMLInputElement>, type: "main" | "extra") => {
    const file = event.target.files?.[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    if (type === "main") {
      if (mainImageRef.current) URL.revokeObjectURL(mainImageRef.current);
      mainImageRef.current = url;
      setMainImage(url);
      setMainFile(file);
    } else {
      if (extraImageRef.current) URL.revokeObjectURL(extraImageRef.current);
      extraImageRef.current = url;
      setExtraImage(url);
      setExtraFile(file);
    }
    setComplete(false);
    setResultImage(null);
    setGenerateError("");
  };

  const tilt = (event: ReactPointerEvent<HTMLElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width - 0.5;
    const y = (event.clientY - rect.top) / rect.height - 0.5;
    event.currentTarget.style.setProperty("--tilt-x", `${-y * 7}deg`);
    event.currentTarget.style.setProperty("--tilt-y", `${x * 8}deg`);
  };

  const clearTilt = (event: ReactPointerEvent<HTMLElement>) => {
    event.currentTarget.style.setProperty("--tilt-x", "0deg");
    event.currentTarget.style.setProperty("--tilt-y", "0deg");
  };

  const beginDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest("button, a, input, label")) return;
    dragRef.current = {
      active: true,
      x: event.clientX,
      y: event.clientY,
      baseX: viewRef.current.x,
      baseY: viewRef.current.y,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const moveDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragRef.current.active) return;
    viewRef.current.x = dragRef.current.baseX + event.clientX - dragRef.current.x;
    viewRef.current.y = dragRef.current.baseY + event.clientY - dragRef.current.y;
    applyView(false);
  };

  const playLaser = () => {
    const button = generateRef.current;
    const stream = streamRef.current;
    const result = resultRef.current;
    if (!button || !stream || !result) return;
    const from = button.getBoundingClientRect();
    const to = result.getBoundingClientRect();
    const x1 = from.left + from.width / 2;
    const y1 = from.top + from.height / 2;
    const x2 = to.left + to.width / 2;
    const y2 = to.top + to.height / 2;
    const length = Math.hypot(x2 - x1, y2 - y1);
    const angle = Math.atan2(y2 - y1, x2 - x1) * 180 / Math.PI;
    gsap.set(stream, { x: x1, y: y1, width: length, rotation: angle, scaleX: 0, autoAlpha: 1 });
    gsap.timeline().to(button, { scale: 0.97, duration: 0.1, yoyo: true, repeat: 1 })
      .to(stream, { scaleX: 1, duration: 0.75, ease: "power2.inOut" }, 0.1)
      .to(stream, { autoAlpha: 0, duration: 0.35 }, 0.8);
  };

  const revealResult = (url: string) => {
    setResultImage(url);
    setComplete(true);
    const result = resultRef.current;
    if (!result) return;
    gsap.timeline()
      .fromTo(result, { "--scan": "0%" }, { "--scan": "100%", duration: 1.65, ease: "power2.inOut" })
      .fromTo(result.querySelector(".cyber-node__result-glow"), { scale: 0.7, autoAlpha: 0 }, { scale: 1, autoAlpha: 1, duration: 0.7 }, 1.15);
  };

  const readError = async (response: Response) => {
    try {
      const payload = await response.json();
      return payload.detail || payload.message || "生成请求失败";
    } catch {
      return "生成请求失败";
    }
  };

  const generate = async () => {
    if (generating) return;
    if (!mainFile) {
      setGenerateError("请先上传产品主视角");
      return;
    }
    if (!resolutionSupported) {
      setGenerateError(`当前生成服务不支持 ${resolution}`);
      return;
    }
    const model = selectedPresets.model;
    const scene = selectedPresets.scene;
    const composition = selectedPresets.composition;
    if (!model || !scene || !composition) {
      setGenerateError("请依次选择模特、场景和构图预设");
      return;
    }
    setGenerating(true);
    setComplete(false);
    setResultImage(null);
    setGenerateError("");
    setProgress(3);
    setJobStage("正在上传并校验素材");
    playLaser();
    try {
      const form = new FormData();
      const endpoint = `${API}/api/studio/jobs`;
      form.append("main_image", mainFile);
      if (extraFile) form.append("extra_image", extraFile);
      form.append("model_preset_id", model.id);
      form.append("scene_preset_id", scene.id);
      form.append("composition_id", composition.id);
      form.append("aspect_ratio", aspectRatio);
      form.append("resolution", resolution);
      const created = await fetch(endpoint, { method: "POST", body: form });
      if (!created.ok) throw new Error(await readError(created));
      let job = await created.json();
      for (let attempt = 0; attempt < 480; attempt += 1) {
        setProgress(Number(job.progress || 0));
        setJobStage(job.stage || "生成中");
        if (["completed", "completed_mock"].includes(job.status)) {
          const output = job.outputs?.[0];
          if (!output?.preview_url) throw new Error("任务完成，但没有返回图片");
          setProgress(100);
          setJobStage("生成完成");
          revealResult(`${API}${output.preview_url}`);
          return;
        }
        if (["failed", "cancelled", "quality_failed"].includes(job.status)) {
          throw new Error(job.error || job.stage || "生成任务失败");
        }
        await new Promise((resolve) => window.setTimeout(resolve, 800));
        const status = await fetch(`${API}/api/jobs/${job.id}`, { cache: "no-store" });
        if (!status.ok) throw new Error(await readError(status));
        job = await status.json();
      }
      throw new Error("生成等待时间过长，请稍后重试");
    } catch (error) {
      setGenerateError(error instanceof Error ? error.message : "生成失败，请稍后重试");
      setJobStage("生成失败");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <main className="cyber-studio" ref={rootRef}>
      <canvas className="cyber-grid" ref={canvasRef} aria-hidden="true" />
      <div className="cyber-studio__aurora" aria-hidden="true" />
      <div className="laser-stream" ref={streamRef} aria-hidden="true" />

      <header className="cyber-hud">
        <a className="cyber-hud__back" href="/dashboard?tool=studio" aria-label="返回工作台">← <span>AI 虚拟影棚</span></a>
        <div className="cyber-hud__tools">
          <button type="button" onClick={() => changeZoom(-10)} aria-label="缩小画布">−</button>
          <output>{zoom}%</output>
          <button type="button" onClick={() => changeZoom(10)} aria-label="放大画布">＋</button>
          <i />
          <button type="button" aria-label="撤销">↶</button>
          <button type="button" aria-label="重做">↷</button>
          <button type="button" onClick={resetView} aria-label="复位视图">⌾</button>
        </div>
        <span className="cyber-hud__tip">拖动画布 · 滚轮缩放 · 无声模式</span>
      </header>

      <section
        className="cyber-canvas"
        aria-label="AI 图片生成画布"
        onPointerDown={beginDrag}
        onPointerMove={moveDrag}
        onPointerUp={() => { dragRef.current.active = false; }}
        onPointerCancel={() => { dragRef.current.active = false; }}
        onWheel={(event) => {
          event.preventDefault();
          changeZoom(event.deltaY > 0 ? -5 : 5);
        }}
      >
        <div className="cyber-viewport" ref={viewportRef}>
          <div className={`cyber-node ${generating ? "is-scanning" : ""} ${complete ? "is-complete" : ""}`} ref={resultRef}>
            <span className="corner corner--tl" /><span className="corner corner--tr" />
            <span className="corner corner--bl" /><span className="corner corner--br" />
            <div className="cyber-node__result-glow" aria-hidden="true" />
            {resultImage || mainImage ? (
              <img className="cyber-node__image" src={resultImage || mainImage || ""} alt={resultImage ? "AI生成的模特家纺场景图" : "已上传的产品主视角"} />
            ) : (
              <div className="cyber-node__empty">
                <span>AI</span>
                <strong>等待主视角素材</strong>
                <small>在右侧上传产品图，启动全息影棚</small>
              </div>
            )}
            <div className="cyber-node__hologram" aria-hidden="true"><i /></div>
            {generating && (
              <div className="cyber-node__progress" role="status" aria-live="polite">
                <span><b>生成中...</b><em>{progress}%</em></span>
                <i><b style={{ width: `${Math.max(4, progress)}%` }} /></i>
                <small>{jobStage}</small>
              </div>
            )}
            <div className="cyber-node__status">
              <span>{complete ? "RENDER COMPLETE" : generating ? "NEURAL RENDERING" : "STUDIO NODE 01"}</span>
              <b>{complete ? "100%" : generating ? "PROCESSING" : "READY"}</b>
            </div>
          </div>
          <div className="cyber-node-label"><i /> 画布核心节点 <span>{outputWidth} × {outputHeight}</span></div>
        </div>
      </section>

      <aside className={`cyber-dock ${collapsed ? "is-collapsed" : ""}`}>
        <button className="cyber-dock__toggle" type="button" onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? "展开设置面板" : "折叠设置面板"}>
          {collapsed ? "<" : ">"}
        </button>
        <div className="cyber-dock__content">
          <div className="cyber-dock__title">
            <div className="cyber-dock__brand"><img src="/brand-logo.jpg" alt="" /><span>VISUAL LAB</span><h1>AI 虚拟影棚</h1></div>
            <em className={backendOnline ? "is-online" : ""}>{backendOnline ? "AGENT PLAN" : "OFFLINE"}</em>
          </div>

          <section className="dock-module">
            <header><span>01</span><h2>素材上传</h2><small>INPUT</small></header>
            <div className="upload-grid">
              <label className={`upload-tile magnetic-card ${mainImage ? "has-image" : ""}`} onPointerMove={tilt} onPointerLeave={clearTilt}>
                <input type="file" accept="image/*" onChange={(event) => chooseImage(event, "main")} />
                {mainImage ? <img src={mainImage} alt="主视角预览" /> : <><b>＋</b><strong>主视角</strong><small>必传 · 拖入图片</small></>}
              </label>
              <label className={`upload-tile magnetic-card ${extraImage ? "has-image" : ""}`} onPointerMove={tilt} onPointerLeave={clearTilt}>
                <input type="file" accept="image/*" onChange={(event) => chooseImage(event, "extra")} />
                {extraImage ? <img src={extraImage} alt="补充图预览" /> : <><b>＋</b><strong>补充图</strong><small>选填 · 辅助参考</small></>}
              </label>
            </div>
          </section>

          <section className="dock-module">
            <header><span>02</span><h2>模式与方案</h2><small>MODE</small></header>
            <div className="mode-grid">
              {modes.map((item) => {
                const selected = Boolean(selectedPresets[presetConfig[item.id].kind]);
                return (
                  <button
                    className={`mode-tile magnetic-card ${selected ? "is-active" : ""}`}
                    type="button"
                    key={item.id}
                    onClick={() => openPresetDatabase(item.id)}
                    onPointerMove={tilt}
                    onPointerLeave={clearTilt}
                    aria-pressed={selected}
                  >
                    <em>{item.number}</em>
                    <span>{item.icon}</span>
                    <span className="mode-tile__copy"><strong>{item.label}</strong><small>{item.note}</small></span>
                    <b>{selected ? "已选择" : "选择"}</b>
                  </button>
                );
              })}
            </div>
            {presetPanel && (
              <div className={`preset-database ${presetPanel === "composition" ? "is-composition-grid" : ""}`} role="dialog" aria-modal="true" aria-label={presetConfig[mode].title}>
                <header className="preset-database__header">
                  <div><small>LOCAL DATABASE</small><strong>{presetConfig[mode].title}</strong></div>
                  <button type="button" onClick={() => { setPendingPreset(null); setPresetPanel(null); }} aria-label="关闭预设资料库">×</button>
                </header>
                <div className="preset-database__content">
                  {presetLoading && <p className="preset-database__message">正在读取资料库…</p>}
                  {!presetLoading && presetError && <p className="preset-database__message is-error">{presetError}</p>}
                  {!presetLoading && !presetError && presets.length === 0 && (
                    <div className="preset-database__empty"><span>◇</span><strong>资料库暂无内容</strong><small>请先由管理员导入正式预设素材</small></div>
                  )}
                  {!presetLoading && presets.map((preset) => (
                    <button
                      className={`preset-card ${presetPanel === "composition" ? "is-composition-card" : ""} ${selectedPresets[presetPanel]?.id === preset.id ? "is-selected" : ""}`}
                      type="button"
                      key={preset.id}
                      aria-label={`${selectedPresets[presetPanel]?.id === preset.id ? "已选择，" : ""}放大预览${preset.name}`}
                      onClick={() => setPendingPreset({ kind: presetPanel, preset })}
                    >
                      <span className="preset-card__preview">
                        {preset.preview_url ? <img src={presetImageUrl(preset, "thumb")} alt={preset.name} /> : <i>AI</i>}
                      </span>
                      {presetPanel === "composition" ? <em className="preset-card__number">{preset.name.replace("床品构图 ", "")}</em> : <><span className="preset-card__copy"><strong>{preset.name}</strong><small>{preset.style_tag || preset.scene_type || preset.description || "正式预设"}</small></span><b>{selectedPresets[presetPanel]?.id === preset.id ? "已选择" : "选择"}</b></>}
                    </button>
                  ))}
                </div>
                {pendingPreset?.kind === presetPanel && (
                  <div className="preset-confirm" role="alertdialog" aria-modal="true" aria-labelledby="preset-confirm-title">
                    <div className="preset-confirm__image">
                      {pendingPreset.preset.preview_url ? <img src={presetImageUrl(pendingPreset.preset, "hd")} alt={`${pendingPreset.preset.name}高清大图预览`} /> : <i>AI</i>}
                    </div>
                    <div className="preset-confirm__copy">
                      <small>PRESET CONFIRMATION</small>
                      <strong id="preset-confirm-title">{pendingPreset.preset.name}</strong>
                      <p>请查看放大图片，确认是否使用这张{pendingPreset.kind === "model" ? "模特" : pendingPreset.kind === "scene" ? "场景" : "构图"}预设。</p>
                      <div className="preset-confirm__actions">
                        <button type="button" onClick={() => setPendingPreset(null)}>返回重选</button>
                        <button
                          type="button"
                          className="is-primary"
                          onClick={() => {
                            setSelectedPresets((current) => ({ ...current, [pendingPreset.kind]: pendingPreset.preset }));
                            setPendingPreset(null);
                            setPresetPanel(null);
                          }}
                          autoFocus
                        >确认选择</button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="dock-module dock-module--parameters">
            <header><span>03</span><h2>参数与生成</h2><small>OUTPUT</small></header>
            <div className="parameter-grid">
              <label><span>图片比例</span><select value={aspectRatio} onChange={(event) => setAspectRatio(event.target.value)}><option>3:4</option><option>1:1</option><option>4:3</option><option>16:9</option></select></label>
              <label><span>分辨率</span><select value={pendingResolution ?? resolution} onChange={(event) => setPendingResolution(event.target.value)}><option disabled={capabilities ? !capabilities.supported_resolutions.includes("1K") : true}>1K</option><option>2K</option><option disabled={capabilities ? !capabilities.supported_resolutions.includes("4K") : true}>4K</option></select></label>
            </div>
            {pendingResolution && (
              <div className="resolution-confirm" role="alertdialog" aria-modal="true" aria-labelledby="resolution-confirm-title">
                <span>分辨率二次确认</span>
                <strong id="resolution-confirm-title">确认将图片调整为 {pendingResolution}？</strong>
                <p>最终输出为 {pendingOutputWidth} × {pendingOutputHeight} px。确认后，下一次生成会按该尺寸重新生成并放大校准。</p>
                <div>
                  <button type="button" onClick={() => setPendingResolution(null)}>取消</button>
                  <button type="button" className="is-primary" onClick={confirmResolution} autoFocus>确认使用 {pendingResolution}</button>
                </div>
              </div>
            )}
            {capabilities && <p className="provider-capability"><b>{capabilities.provider}</b><span>{capabilities.message}</span></p>}
            {studioConnection && <p className="provider-capability" role="status"><b>{studioConnection.connected ? "AI 网络已连接" : "AI 正在重连"}</b><span>{studioConnection.message}</span></p>}
            {generating && (
              <div className="generate-progress" aria-hidden="true">
                <i><b style={{ width: `${Math.max(4, progress)}%` }} /></i>
                <span>{jobStage}</span>
              </div>
            )}
            {generateError && <p className="generate-error" role="alert">{generateError}</p>}
            {resultImage && <a className="result-download" href={resultImage} target="_blank" rel="noreferrer">打开并下载 {resolution} 成片 ↗</a>}
            <button className={`generate-button ${generating ? "is-charging" : ""}`} type="button" ref={generateRef} onClick={generate} disabled={generating || !backendOnline || !resolutionSupported}>
              <i aria-hidden="true" /><span>{generating ? "生成中..." : complete ? "再次生成" : "立即生成"}</span><em>{generating ? `${progress}%` : `SEEDREAM 5 LITE · ${resolution}`}</em>
            </button>
          </section>
        </div>
      </aside>

      <div className="cyber-statusbar" aria-hidden="true">
        <span><i className="is-cyan" /> AGENT PLAN</span><span><i /> SEEDREAM 5.0 LITE</span><span>{resolution} IMAGE</span>
      </div>
    </main>
  );
}
