"use client";

import { useEffect, useRef, useState } from "react";
import { validateSketchUpload } from "./sketch-upload";
import "./TemplateLab.css";
import "./SketchLab.css";

const API = (process.env.NEXT_PUBLIC_STUDIO_API ?? "").replace(/\/+$/, "");
type ImageAsset = { url: string; name: string; file: File };
type GeneratedImage = { url: string; id: string };
type Slot = "a" | "b" | "reference";

function Icon({ name }: { name: "back" | "upload" | "sketch" | "chevron" }) {
  const paths = {
    back: <path d="m15 18-6-6 6-6" />,
    upload: <><path d="M12 16V4m0 0L7 9m5-5 5 5M5 15v5h14v-5" /></>,
    sketch: <><path d="M20 10V4H4v16h7M4 16l5-5 5 4m1-8h.01M14 20l2-5 4-4 3 3-4 4-5 2Z" /></>,
    chevron: <path d="m8 10 4 4 4-4" />,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

function UploadArea({ label, image, multiple = false, onFiles, onRemove, onError }: {
  label: string; image?: ImageAsset; multiple?: boolean;
  onFiles: (files: File[]) => void; onRemove?: () => void; onError?: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  return <div className="sketch-upload-wrap">
    <input ref={input} className="sketch-file-input" type="file" accept="image/jpeg,image/png,image/webp" multiple={multiple} aria-label={label} onChange={(event) => { onFiles(Array.from(event.target.files ?? [])); event.target.value = ""; }} />
    <div className={`sketch-upload ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); onFiles(Array.from(event.dataTransfer.files)); }}>
      <button type="button" onClick={() => input.current?.click()} aria-label={image ? `更换${label}` : label}>
        {image ? <img src={image.url} alt={image.name} onError={onError} /> : <Icon name="upload" />}
        <span>{image ? "点击更换图片" : label}</span>
      </button>
    </div>
    {image && <div className="sketch-file-meta"><span title={image.name}>{image.name}</span><button type="button" onClick={onRemove}>移除</button></div>}
  </div>;
}

export default function SketchLab() {
  const mainInput = useRef<HTMLInputElement>(null);
  const urls = useRef(new Set<string>());
  const [a, setA] = useState<ImageAsset | null>(null);
  const [b, setB] = useState<ImageAsset | null>(null);
  const [references, setReferences] = useState<ImageAsset[]>([]);
  const [bMode, setBMode] = useState("image");
  const [color, setColor] = useState("#ffffff");
  const [category, setCategory] = useState("四件套");
  const [fabric, setFabric] = useState("");
  const [craft, setCraft] = useState("");
  const [ratio, setRatio] = useState("3:4");
  const [resolution, setResolution] = useState("1K");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [generating, setGenerating] = useState(false);
  const [completed, setCompleted] = useState(0);
  const [results, setResults] = useState<GeneratedImage[]>([]);
  const [selectedResult, setSelectedResult] = useState<number | null>(null);
  const count = Math.max(1, references.length);

  useEffect(() => {
    const ownedUrls = urls.current;
    return () => { ownedUrls.forEach((url) => URL.revokeObjectURL(url)); ownedUrls.clear(); };
  }, []);

  function release(image: ImageAsset | null) {
    if (image) { URL.revokeObjectURL(image.url); urls.current.delete(image.url); }
  }

  function remove(slot: Slot, image?: ImageAsset) {
    if (slot === "a") { release(a); setA(null); }
    else if (slot === "b") { release(b); setB(null); }
    else if (image) { release(image); setReferences((current) => current.filter((item) => item.url !== image.url)); }
    setNotice("");
    setResults([]); setSelectedResult(null);
  }

  function invalidImage(slot: Slot, image?: ImageAsset) {
    remove(slot, image);
    setError("无法读取图片内容，已移除损坏图片，请重新上传。");
  }

  function upload(slot: Slot, files: File[]) {
    if (!files.length) return;
    const message = validateSketchUpload(files, slot === "reference" ? references.length : 0, slot === "reference" ? 12 : 1);
    setError(message);
    setNotice("");
    if (message) return;
    const images = files.map((file) => {
      const url = URL.createObjectURL(file);
      urls.current.add(url);
      return { url, name: file.name, file };
    });
    if (slot === "a") { release(a); setA(images[0]); }
    else if (slot === "b") { release(b); setB(images[0]); }
    else setReferences((current) => [...current, ...images]);
    setResults([]); setSelectedResult(null);
  }

  async function generate() {
    if (!a || generating) return;
    setGenerating(true); setCompleted(0); setResults([]); setSelectedResult(null); setError(""); setNotice("");
    const tasks = references.length ? references : [null];
    try {
      for (let index = 0; index < tasks.length; index++) {
        const form = new FormData();
        form.append("a_image", a.file);
        if (bMode === "image" && b) form.append("b_image", b.file);
        if (tasks[index]) form.append("reference_image", tasks[index]!.file);
        for (const [key, value] of Object.entries({ b_mode: bMode, color, category, fabric, craft, aspect_ratio: ratio, resolution })) form.append(key, value);
        const response = await fetch(`${API}/api/sketch/generate`, { method: "POST", body: form, signal: AbortSignal.timeout(360000) });
        const data = await response.json().catch(() => ({})) as { id?: string; result_url?: string; detail?: string };
        if (!response.ok || !data.result_url || !data.id) throw new Error(data.detail || `生成服务返回 HTTP ${response.status}`);
        const generated = { id: data.id, url: `${API}${data.result_url}` };
        setResults((current) => [...current, generated]);
        setSelectedResult(index);
        setCompleted(index + 1);
      }
      setNotice(`已生成 ${tasks.length} 张图片，可在画布中切换并下载。页面未扣除积分。`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "生成失败，请检查后端服务。素材与参数仍保留在页面中。");
    } finally {
      setGenerating(false);
    }
  }

  return <main className="template-lab sketch-lab">
    <header className="template-hud">
      <a className="template-back" href="/dashboard?tool=sketch"><Icon name="back" /><span>返回</span></a>
      <div className="template-brand"><img src="/brand-logo.jpg" alt="" /><div><strong>SKETCH IMAGE LAB</strong><small>AI 画稿生图控制台</small></div></div>
      <div className="template-status"><i /><span>LOCAL WORKSPACE</span><b>本地预览</b></div>
    </header>
    <div className="template-layout">
      <section className="template-canvas" aria-label="画稿生图画布">
        <div className="template-toolbar"><div><span>{selectedResult === null ? "画稿素材预览" : `生成结果 ${selectedResult + 1}/${results.length}`}</span><i /><span>{generating ? `正在生成 ${completed + 1}/${count}` : "拖入 A 版画稿"}</span></div><button type="button" onClick={() => mainInput.current?.click()}><Icon name="upload" />导入到画布</button></div>
        <input ref={mainInput} className="sketch-file-input" type="file" accept="image/jpeg,image/png,image/webp" aria-label="导入 A 版画稿" onChange={(event) => { upload("a", Array.from(event.target.files ?? [])); event.target.value = ""; }} />
        <div className="template-stage sketch-stage" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); upload("a", Array.from(event.dataTransfer.files)); }}>
          <span className="template-grid-glow" aria-hidden="true" /><div className="template-stage-corners" aria-hidden="true"><i /><i /><i /><i /></div>
          {selectedResult !== null && results[selectedResult] ? <figure className="sketch-preview"><img src={results[selectedResult].url} alt={`生成结果 ${selectedResult + 1}`} /><figcaption><span>画稿生图 · 生成结果 {selectedResult + 1}</span><a href={results[selectedResult].url} download={`画稿生图-${selectedResult + 1}.png`} target="_blank" rel="noreferrer">下载图片</a></figcaption></figure> : a ? <figure className="sketch-preview"><img src={a.url} alt={`A 版原图：${a.name}`} onError={() => invalidImage("a")} /><figcaption><span>A 版画稿 · 原图预览，非生成结果</span><strong>{a.name}</strong></figcaption></figure> : <div className="template-empty"><div className="template-orbit"><Icon name="sketch" /></div><span>SKETCH INPUT / CANVAS READY</span><p>导入 A 版画稿，在右侧补充配色、参考图与材质参数。</p><button type="button" onClick={() => mainInput.current?.click()}><Icon name="upload" />添加画稿</button></div>}
          {results.length > 0 && <div className="sketch-result-switch" role="group" aria-label="切换画稿和生成结果"><button type="button" aria-pressed={selectedResult === null} onClick={() => setSelectedResult(null)}>原稿</button>{results.map((item, index) => <button key={item.id} type="button" aria-pressed={selectedResult === index} onClick={() => setSelectedResult(index)}>{index + 1}</button>)}</div>}
        </div>
        <footer className="template-footer"><span><i />{a ? "SOURCE LOADED" : "CANVAS READY"}</span><b>{category} · {ratio} · {resolution}</b></footer>
      </section>
      <aside className="template-panel" aria-label="画稿生图设置">
        <div className="sketch-tool-menu template-panel-title"><span><i><Icon name="sketch" /></i><h1>画稿生图</h1></span></div>
        <section className="template-card">
          <header><div><span>01</span><strong>画稿素材</strong></div><em>DESIGN INPUT</em></header>
          <p>JPG / PNG / WEBP · 单张不超过 20MB</p>
          <div className="sketch-versions">
            <div className="sketch-version"><h2>A 版 <small className="is-required">必填</small></h2><UploadArea label="上传或拖入 A 版" image={a ?? undefined} onFiles={(files) => upload("a", files)} onRemove={() => remove("a")} onError={() => invalidImage("a")} /></div>
            <div className="sketch-version"><h2>B 版 <small>选填</small></h2><div className="sketch-mode" role="group" aria-label="B 版素材类型"><button type="button" aria-pressed={bMode === "image"} onClick={() => setBMode("image")}>上传图片</button><button type="button" aria-pressed={bMode === "color"} onClick={() => setBMode("color")}><i style={{ backgroundColor: color }} />选择纯色</button></div>{bMode === "image" ? <UploadArea label="上传或拖入 B 版" image={b ?? undefined} onFiles={(files) => upload("b", files)} onRemove={() => remove("b")} onError={() => invalidImage("b")} /> : <label className="sketch-color"><span>B 版纯色</span><input type="color" value={color} onChange={(event) => setColor(event.target.value)} /><strong>{color.toUpperCase()}</strong></label>}</div>
          </div>
        </section>
        <section className="template-card sketch-references">
          <header><div><span>02</span><strong>参考图 <small>选填</small></strong></div><em>{references.length}/12 个任务</em></header>
          <UploadArea label="上传或拖入参考图" multiple onFiles={(files) => upload("reference", files)} />
          {references.length > 0 && <div className="sketch-thumbnails">{references.map((item, index) => <div key={item.url}><img src={item.url} alt={`参考图 ${index + 1}：${item.name}`} onError={() => invalidImage("reference", item)} /><button type="button" aria-label={`移除参考图 ${index + 1}`} onClick={() => remove("reference", item)}>×</button></div>)}</div>}
          <p>每张参考图对应 1 张输出；未上传时默认 1 张。</p>
        </section>
        <section className="template-card">
          <header><div><span>03</span><strong>产品信息</strong></div><em>MATERIAL DATA</em></header>
          <div className="sketch-fields"><label htmlFor="sketch-category">品类<select id="sketch-category" value={category} onChange={(event) => setCategory(event.target.value)}>{["四件套", "被子", "枕头", "窗帘", "沙发", "椅子", "其他"].map((item) => <option key={item}>{item}</option>)}</select></label><label htmlFor="sketch-fabric">面料<input id="sketch-fabric" value={fabric} maxLength={100} onChange={(event) => setFabric(event.target.value)} placeholder="填写面料" /></label><label className="sketch-field-wide" htmlFor="sketch-craft">工艺<input id="sketch-craft" value={craft} maxLength={200} onChange={(event) => setCraft(event.target.value)} placeholder="填写工艺" /></label></div>
        </section>
        <section className="template-specs"><label><span>图片比例</span><select value={ratio} onChange={(event) => setRatio(event.target.value)}>{["3:4", "1:1", "4:3", "9:16", "16:9"].map((item) => <option key={item}>{item}</option>)}</select></label><label><span>分辨率</span><select value={resolution} onChange={(event) => setResolution(event.target.value)}>{["1K", "2K", "4K"].map((item) => <option key={item}>{item}</option>)}</select></label></section>
        {error && <p className="sketch-error" role="alert">{error}</p>}
        <div className="template-credit"><span>预计消耗积分<small>{count} 张 × 8 分 · 当前不会扣费</small></span><strong>{count * 8}<i>分</i></strong></div>
        <button className="template-generate" type="button" disabled={!a || generating} aria-describedby="sketch-service-note" onClick={generate}><span>{generating ? `正在生成 ${completed + 1}/${count} 张…` : `生成 ${count} 张`}</span><em>GENERATE</em></button>
        <p id="sketch-service-note" className="sketch-service-note">由 Agent Plan 图片服务生成 · 每张参考图对应一张结果</p>
        {notice && <p className="sketch-notice" role="status">{notice}</p>}
      </aside>
    </div>
  </main>;
}
