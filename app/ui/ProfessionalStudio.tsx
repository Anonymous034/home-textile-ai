"use client";

import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { gsap } from "gsap";
import "./ProfessionalStudio.css";

const API = (process.env.NEXT_PUBLIC_STUDIO_API ?? "").replace(/\/+$/, "");
const aspectValues = ["1:1", "3:4", "4:3", "9:16", "16:9"] as const;
const resolutionEdges = { "1K": 1024, "2K": 2048, "4K": 4096 } as const;

type AssetKind = "model" | "furniture" | "scene";
type AssetState = { id: string; url: string; name: string; width: number; height: number };
type Capabilities = {
  provider: string;
  ready_for_commercial_generation: boolean;
  supported_resolutions: string[];
  message: string;
};
type Output = { id: string; quality_status: string; quality_scores: Record<string, number | null> };
type Job = {
  id: string;
  status: string;
  progress: number;
  stage: string;
  resolution: string;
  output_width: number;
  output_height: number;
  is_mock: boolean;
  outputs: Output[];
};

const assetLabels: Record<AssetKind, { title: string; note: string; tag: string }> = {
  model: { title: "模特图片", note: "保持人脸、体型、发型与服装", tag: "IDENTITY" },
  furniture: { title: "家具主视角", note: "保护结构、面料、花型与缝线", tag: "PRODUCT" },
  scene: { title: "场景图片", note: "提取透视、深度、地面与光线", tag: "SCENE" },
};

function outputSize(aspect: string, resolution: keyof typeof resolutionEdges) {
  const [a, b] = aspect.split(":").map(Number);
  const edge = resolutionEdges[resolution];
  let width = a >= b ? edge : Math.round(edge * a / b);
  let height = a >= b ? Math.round(edge * b / a) : edge;
  width = Math.max(64, Math.floor(width / 64) * 64);
  height = Math.max(64, Math.floor(height / 64) * 64);
  return { width, height };
}

export default function ProfessionalStudio() {
  const rootRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [assets, setAssets] = useState<Partial<Record<AssetKind, AssetState>>>({});
  const [uploading, setUploading] = useState<AssetKind | null>(null);
  const [aspect, setAspect] = useState<(typeof aspectValues)[number]>("3:4");
  const [resolution, setResolution] = useState<keyof typeof resolutionEdges>("2K");
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [backendOnline, setBackendOnline] = useState(false);
  const size = useMemo(() => outputSize(aspect, resolution), [aspect, resolution]);
  const allAssetsReady = Boolean(assets.model && assets.furniture && assets.scene);
  const resolutionSupported = capabilities?.supported_resolutions.includes(resolution) ?? false;
  const running = Boolean(job && !["completed_mock", "failed", "cancelled", "quality_failed"].includes(job.status));

  useEffect(() => {
    fetch(`${API}/api/provider-capabilities`)
      .then(async (response) => {
        if (!response.ok) throw new Error("服务异常");
        const value = await response.json() as Capabilities;
        setCapabilities(value);
        setBackendOnline(true);
      })
      .catch(() => {
        setBackendOnline(false);
        setError("后端服务暂不可连接。界面可以查看，但无法上传和创建任务。");
      });
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    const root = rootRef.current;
    if (!canvas || !root) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let frame = 0;
    let width = 0;
    let height = 0;
    let clock = 0;
    const pointer = { x: -600, y: -600, tx: -600, ty: -600 };
    const resize = () => {
      const ratio = Math.min(devicePixelRatio || 1, 2);
      width = root.clientWidth;
      height = root.clientHeight;
      canvas.width = width * ratio;
      canvas.height = height * ratio;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    };
    const draw = () => {
      pointer.x += (pointer.tx - pointer.x) * 0.075;
      pointer.y += (pointer.ty - pointer.y) * 0.075;
      clock += 0.012;
      ctx.clearRect(0, 0, width, height);
      for (let y = 0; y < height + 40; y += 38) {
        for (let x = 0; x < width + 40; x += 38) {
          const dx = pointer.x - x;
          const dy = pointer.y - y;
          const distance = Math.hypot(dx, dy);
          const force = Math.max(0, 1 - distance / 240);
          ctx.beginPath();
          ctx.arc(x + (dx / (distance || 1)) * force * 10, y + (dy / (distance || 1)) * force * 10 + Math.sin(clock + x * 0.01) * 0.8, 0.7 + force, 0, Math.PI * 2);
          ctx.fillStyle = force ? `rgba(0,242,254,${0.13 + force * 0.55})` : "rgba(130,160,190,.11)";
          ctx.fill();
        }
      }
      frame = requestAnimationFrame(draw);
    };
    const move = (event: PointerEvent) => {
      const rect = root.getBoundingClientRect();
      pointer.tx = event.clientX - rect.left;
      pointer.ty = event.clientY - rect.top;
    };
    resize();
    root.addEventListener("pointermove", move);
    window.addEventListener("resize", resize);
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      root.removeEventListener("pointermove", move);
      window.removeEventListener("resize", resize);
    };
  }, []);

  useEffect(() => {
    if (!job || !running) return;
    const socketUrl = new URL(`${API}/ws/jobs/${job.id}`, window.location.href);
    socketUrl.protocol = socketUrl.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(socketUrl);
    let polling = 0;
    const update = (value: Job) => setJob(value);
    socket.onmessage = (event) => update(JSON.parse(event.data) as Job);
    socket.onerror = () => {
      polling = window.setInterval(() => {
        fetch(`${API}/api/jobs/${job.id}`).then((response) => response.json()).then(update).catch(() => undefined);
      }, 1500);
    };
    return () => {
      socket.close();
      window.clearInterval(polling);
    };
  }, [job?.id, running]);

  useEffect(() => {
    if (!job || job.status !== "completed_mock" || !resultRef.current) return;
    const context = gsap.context(() => {
      gsap.fromTo(".studio-result-card", { y: 20, autoAlpha: 0 }, { y: 0, autoAlpha: 1, duration: 0.55, stagger: 0.08, ease: "power3.out" });
      gsap.fromTo(".studio-scanline", { yPercent: -100 }, { yPercent: 900, duration: 1.5, ease: "power2.inOut" });
    }, resultRef);
    return () => context.revert();
  }, [job?.status]);

  const upload = async (event: ChangeEvent<HTMLInputElement>, kind: AssetKind) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setError("");
    setUploading(kind);
    const preview = URL.createObjectURL(file);
    try {
      const body = new FormData();
      body.append("kind", kind);
      body.append("file", file);
      const response = await fetch(`${API}/api/assets`, { method: "POST", body });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail || "上传失败");
      setAssets((current) => {
        const previous = current[kind];
        if (previous?.url.startsWith("blob:")) URL.revokeObjectURL(previous.url);
        return { ...current, [kind]: { id: value.id, url: preview, name: file.name, width: value.width, height: value.height } };
      });
      setJob(null);
    } catch (uploadError) {
      URL.revokeObjectURL(preview);
      setError(uploadError instanceof Error ? uploadError.message : "上传失败");
    } finally {
      setUploading(null);
      event.target.value = "";
    }
  };

  const generate = async () => {
    if (!allAssetsReady || !resolutionSupported || running) return;
    setError("");
    if (buttonRef.current) gsap.fromTo(buttonRef.current, { scale: 0.96 }, { scale: 1, duration: 0.45, ease: "back.out(2)" });
    try {
      const response = await fetch(`${API}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_asset_id: assets.model!.id,
          furniture_asset_id: assets.furniture!.id,
          scene_asset_id: assets.scene!.id,
          composition_id: "demo-awaiting-real-template",
          aspect_ratio: aspect,
          resolution,
          output_count: 4,
        }),
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail || "任务创建失败");
      setJob(value as Job);
    } catch (generationError) {
      setError(generationError instanceof Error ? generationError.message : "任务创建失败");
    }
  };

  const retry = async () => {
    if (!job) return;
    const response = await fetch(`${API}/api/jobs/${job.id}/retry`, { method: "POST" });
    setJob(await response.json() as Job);
  };

  return (
    <main className="professional-studio" ref={rootRef}>
      <canvas className="professional-grid" ref={canvasRef} aria-hidden="true" />
      <header className="professional-hud">
        <a href="/dashboard?tool=studio">← 返回工作台</a>
        <div><strong>AI 商拍合影实验室</strong><span>IDENTITY · PRODUCT · SCENE</span></div>
        <b className={backendOnline ? "is-online" : ""}>{backendOnline ? "SYSTEM ONLINE" : "BACKEND OFFLINE"}</b>
      </header>

      <section className="professional-canvas" ref={resultRef}>
        <div className="professional-canvas__title">
          <span>QUALITY FIRST WORKFLOW / 01</span>
          <h1>模特 × 家具<br />商业合影生成</h1>
          <p>先锁定人物身份与家具原像素，再绑定姿态、深度和区域蒙版。未通过质量检测的图片不会作为成片交付。</p>
        </div>

        <div className="studio-result-stage">
          <i className="studio-scanline" aria-hidden="true" />
          {job?.outputs?.length ? (
            <div className="studio-result-grid">
              {job.outputs.map((output, index) => (
                <article className="studio-result-card" key={output.id}>
                  <img src={`${API}/api/files/${output.id}`} alt={`模拟候选图 ${index + 1}`} />
                  <footer><span>候选 {String(index + 1).padStart(2, "0")}</span><b>{output.quality_status === "mock_unverified" ? "未进行AI质量验证" : output.quality_status}</b></footer>
                </article>
              ))}
            </div>
          ) : (
            <div className="studio-empty-node">
              <span>AI</span>
              <strong>{job ? job.stage : "等待三张必传图片"}</strong>
              <small>{job ? `${job.progress}% · ${job.status}` : "上传模特、家具主视角与场景图片后创建任务"}</small>
            </div>
          )}
        </div>

        {job && <div className="studio-progress"><i style={{ width: `${job.progress}%` }} /><span>{job.stage}</span><b>{job.progress}%</b></div>}
        <div className="studio-quality-steps">
          <span>01 身份与体型</span><span>02 家具保护</span><span>03 构图蒙版</span><span>04 接触与光照</span><span>05 质量门槛</span>
        </div>
      </section>

      <aside className="professional-dock">
        <header><div className="professional-dock__brand"><img src="/brand-logo.jpg" alt="" /><span>COMMERCIAL LAB</span></div><h2>生成控制台</h2><p>三张图片全部必传</p></header>

        <section className="professional-module">
          <div className="professional-module__head"><span>01</span><strong>素材与特征</strong><em>INPUT</em></div>
          <div className="professional-uploads">
            {(Object.keys(assetLabels) as AssetKind[]).map((kind) => {
              const value = assets[kind];
              const label = assetLabels[kind];
              return (
                <label className={`professional-upload ${value ? "has-image" : ""}`} key={kind}>
                  <input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => upload(event, kind)} disabled={!backendOnline || uploading !== null} />
                  {value ? <img src={value.url} alt={`${label.title}预览`} /> : <span>＋</span>}
                  <div><b>{uploading === kind ? "上传中…" : label.title}</b><small>{value ? `${value.width} × ${value.height}` : label.note}</small></div>
                  <em>{value ? "READY" : label.tag}</em>
                </label>
              );
            })}
          </div>
        </section>

        <section className="professional-module">
          <div className="professional-module__head"><span>02</span><strong>构图模板</strong><em>CONTROL</em></div>
          <button className="composition-placeholder" type="button" disabled>
            <span>蒙版包待导入</span>
            <small>需要姿态图、深度图、人物/家具/保护/接触蒙版</small>
            <b>DEMO FLOW</b>
          </button>
        </section>

        <section className="professional-module">
          <div className="professional-module__head"><span>03</span><strong>输出参数</strong><em>OUTPUT</em></div>
          <div className="professional-parameters">
            <label><span>图片比例</span><select value={aspect} onChange={(event) => setAspect(event.target.value as typeof aspect)}>{aspectValues.map((value) => <option key={value}>{value}</option>)}</select></label>
            <label><span>分辨率</span><select value={resolution} onChange={(event) => setResolution(event.target.value as keyof typeof resolutionEdges)}>{(["1K", "2K", "4K"] as const).map((value) => <option key={value} disabled={capabilities ? !capabilities.supported_resolutions.includes(value) : false}>{value}{value === "2K" ? "（默认）" : ""}</option>)}</select></label>
          </div>
          <div className="output-spec"><span>实际输出</span><strong>{size.width} × {size.height}</strong></div>
          {!resolutionSupported && capabilities && <p className="resolution-warning">当前服务不支持直接{resolution}生成，已禁止提交，不会自动降级。</p>}
          <div className="provider-note"><b>{capabilities?.ready_for_commercial_generation ? "真实AI服务" : "流程模拟模式"}</b><span>{capabilities?.message || "正在检查生成服务…"}</span></div>
          {error && <p className="studio-error">{error}</p>}
          <button className={`professional-generate ${running ? "is-running" : ""}`} ref={buttonRef} type="button" onClick={generate} disabled={!backendOnline || !allAssetsReady || !resolutionSupported || running}>
            <i /><span>{running ? `${job?.progress || 0}% 处理中` : job?.status === "completed_mock" ? "重新运行模拟流程" : "创建4张候选"}</span><em>{allAssetsReady ? "GENERATE" : "请上传三张图片"}</em>
          </button>
          {job && ["failed", "cancelled", "quality_failed", "completed_mock"].includes(job.status) && <button className="professional-retry" type="button" onClick={retry}>重试当前任务</button>}
        </section>
      </aside>
    </main>
  );
}
