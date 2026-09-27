"use client";

import { ChangeEvent, DragEvent, useCallback, useEffect, useRef, useState } from "react";
import DetailPlanDialog, { type DetailSnapshot } from "./DetailPlanDialog";
import type { GenerateTask, InputParams, PlanDocument } from "../detail-page/models";
import { resultUrl } from "../detail-page/api";
import "./DetailPageLab.css";

type ProductImage = { id: string; url: string; name: string; file: File };

const languages = ["中文", "English", "日本語", "한국어"];
const counts = [4, 6, 8, 10, 12];
const ratios = ["9:16", "3:4", "1:1", "4:3"];
const resolutions = ["1K", "2K", "4K"];

function Icon({ name }: { name: "upload" | "spark" | "layers" | "back" | "check" }) {
  const paths = {
    upload: <><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5"/><path d="M5 15v4h14v-4"/></>,
    spark: <><path d="m12 3 1.35 4.15L17.5 8.5l-4.15 1.35L12 14l-1.35-4.15L6.5 8.5l4.15-1.35L12 3Z"/><path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z"/></>,
    layers: <><path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/></>,
    back: <><path d="m15 18-6-6 6-6"/></>,
    check: <><path d="m5 12 4 4L19 6"/></>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

export default function DetailPageLab() {
  const inputRef = useRef<HTMLInputElement>(null);
  const urlsRef = useRef<string[]>([]);
  const [images, setImages] = useState<ProductImage[]>([]);
  const [productName, setProductName] = useState("");
  const [sellingPoints, setSellingPoints] = useState("");
  const [notes, setNotes] = useState("");
  const [language, setLanguage] = useState("中文");
  const [count, setCount] = useState(8);
  const [ratio, setRatio] = useState("9:16");
  const [resolution, setResolution] = useState("1K");
  const [dragging, setDragging] = useState(false);
  const [schemeReady, setSchemeReady] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<DetailSnapshot | null>(null);
  const [result, setResult] = useState<{ task: GenerateTask; plan: PlanDocument } | null>(null);
  const receiveResult = useCallback((task: GenerateTask, plan: PlanDocument) => {
    setResult({ task, plan }); setSchemeReady(true);
  }, []);

  useEffect(() => () => urlsRef.current.forEach((url) => URL.revokeObjectURL(url)), []);

  const addImages = (files: FileList | null) => {
    if (!files) return;
    const accepted = Array.from(files).filter((file) => ["image/jpeg", "image/png", "image/webp"].includes(file.type) && file.size <= 20 * 1024 * 1024).slice(0, 12 - images.length);
    const next = accepted.map((file) => {
      const url = URL.createObjectURL(file);
      urlsRef.current.push(url);
      return { id: crypto.randomUUID(), url, name: file.name, file };
    });
    setImages((current) => [...current, ...next]);
    setSchemeReady(false);
  };

  const chooseImages = (event: ChangeEvent<HTMLInputElement>) => {
    addImages(event.target.files);
    event.target.value = "";
  };

  const dropImages = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    addImages(event.dataTransfer.files);
  };

  const removeImage = (id: string) => {
    const image = images.find((item) => item.id === id);
    if (image) {
      URL.revokeObjectURL(image.url);
      urlsRef.current = urlsRef.current.filter((url) => url !== image.url);
    }
    setImages((current) => current.filter((image) => image.id !== id));
    setSchemeReady(false);
  };

  const generateImages = () => {
    const languageCodes: Record<string, InputParams["language"]> = { "中文": "zh-CN", English: "en", "日本語": "ja", "한국어": "ko" };
    setSnapshot({ input: { productName: productName.trim(), sellingPoints, notes, fabric: "", craftsmanship: "", specifications: "",
      language: languageCodes[language], imageCount: count, aspectRatio: ratio as InputParams["aspectRatio"], resolution: resolution as InputParams["resolution"] },
      images: images.map((image, index) => ({ id: image.id, name: image.name, file: image.file, previewUrl: image.url, role: index === 0 ? "main" : "detail" })) });
    setPlanOpen(true);
  };

  const canGenerate = images.length > 0 && productName.trim().length > 0;
  const credit = count * 12;

  return (
    <main className="detail-lab">
      <header className="detail-topbar">
        <a href="/dashboard?tool=detail-page" className="detail-back"><Icon name="back" /><span>返回工作台</span></a>
        <div className="detail-brand"><i>42</i><div><strong>DETAIL PAGE LAB</strong><small>AI 商品详情页控制台</small></div></div>
        <div className="detail-system"><i /><span>AI CORE ONLINE</span><b>24ms</b></div>
      </header>

      <div className="detail-layout">
        <section className="detail-canvas" aria-label="详情页画布">
          <div className="canvas-toolbar">
            <div><span>按住 Ctrl 多选</span><i /> <span>双击查看详情</span><i /> <span>拖拽框选</span></div>
            <button type="button" onClick={() => inputRef.current?.click()}><Icon name="upload" />导入到画布</button>
          </div>

          <div className="canvas-workspace">
            <span className="canvas-axis canvas-axis--x" /><span className="canvas-axis canvas-axis--y" />
            <div className="canvas-corners"><i /><i /><i /><i /></div>
            {result?.task.items.some((item) => item.status === "completed") ? <div className="detail-generated-suite">{result.task.items.filter((item) => item.status === "completed" && resultUrl(item.previewUrl)).map((item) => { const planned = result.plan.items.find((entry) => entry.id === item.planItemId); return <figure key={item.planItemId}><a href={resultUrl(item.previewUrl)} target="_blank" rel="noreferrer"><img src={resultUrl(item.previewUrl)} alt={planned?.theme || "生成的详情图"} /></a><figcaption>#{planned?.order} · {planned?.theme}</figcaption></figure>; })}</div> : images.length === 0 ? (
              <div className="canvas-empty">
                <div className="orb"><Icon name="layers" /></div>
                <span>DETAIL COMPOSITION NODE</span>
                <p>上传产品图片，AI 将分析材质、结构与卖点并生成视觉叙事方案。</p>
                <button type="button" onClick={() => inputRef.current?.click()}><Icon name="upload" />添加产品图</button>
              </div>
            ) : (
              <div className={`canvas-preview ${schemeReady ? "has-scheme" : ""}`}>
                <div className="preview-copy"><span>AI PRODUCT STORY / 01</span><h1>{productName || "未命名产品"}</h1><p>{sellingPoints || "等待输入核心卖点，构建产品视觉叙事。"}</p></div>
                <div className="preview-hero"><img src={images[0].url} alt="产品主图预览" /><span>HERO VISUAL</span></div>
                {schemeReady && <div className="scheme-badge"><Icon name="check" /> 详情页方案已生成</div>}
              </div>
            )}
          </div>
          <footer className="canvas-footer"><span><i /> CANVAS READY</span><b>{ratio} · {resolution} · {language}</b></footer>
        </section>

        <aside className="detail-panel">
          <div className="panel-heading"><div><span>CONTROL PANEL</span><h2>详情页制作</h2></div><em>AI / 03</em></div>

          <section className="control-card upload-card">
            <header><div><span>01</span><strong>产品图</strong></div><em>已上传 <b>{images.length}</b> / 12 张</em></header>
            <label className={`detail-dropzone ${dragging ? "is-dragging" : ""} ${images.length ? "has-files" : ""}`} onDragEnter={() => setDragging(true)} onDragLeave={() => setDragging(false)} onDragOver={(event) => event.preventDefault()} onDrop={dropImages}>
              <input ref={inputRef} type="file" accept="image/*" multiple onChange={chooseImages} />
              <div className="upload-symbol"><Icon name="upload" /></div>
              <strong>上传或拖入产品图</strong><small>JPG / PNG / WEBP · 单张不超过 20MB</small>
            </label>
            {images.length > 0 && <div className="upload-strip">{images.map((image, index) => <button type="button" key={image.id} onClick={() => removeImage(image.id)} title={`移除 ${image.name}`}><img src={image.url} alt={`产品图 ${index + 1}`} /><span>×</span></button>)}</div>}
          </section>

          <section className="control-card info-card">
            <header><div><span>02</span><strong>产品信息</strong></div><em>PRODUCT DATA</em></header>
            <label><span>产品名称 <b>必填</b></span><input value={productName} onChange={(event) => { setProductName(event.target.value); setSchemeReady(false); }} placeholder="例如：全棉色织水洗棉四件套" /></label>
            <label><span>核心卖点 <i>选填</i></span><input value={sellingPoints} onChange={(event) => setSellingPoints(event.target.value)} placeholder="例如：60支长绒棉、刺绣工艺等" /></label>
            <label><span>补充说明 <i>选填</i></span><textarea value={notes} maxLength={300} onChange={(event) => setNotes(event.target.value)} placeholder="可以补充材质、尺寸、功能等信息…" /><small>{notes.length}/300</small></label>
          </section>

          <section className="control-card params-card">
            <header><div><span>03</span><strong>生成参数</strong></div><em>OUTPUT</em></header>
            <div className="param-grid">
              <label><span>语言</span><select value={language} onChange={(event) => setLanguage(event.target.value)}>{languages.map((item) => <option key={item}>{item}</option>)}</select></label>
              <label><span>生成张数</span><select value={count} onChange={(event) => setCount(Number(event.target.value))}>{counts.map((item) => <option value={item} key={item}>{item} 张</option>)}</select></label>
              <label><span>图片比例</span><select value={ratio} onChange={(event) => setRatio(event.target.value)}>{ratios.map((item) => <option key={item}>{item}</option>)}</select></label>
              <label><span>分辨率</span><select value={resolution} onChange={(event) => setResolution(event.target.value)}>{resolutions.map((item) => <option key={item}>{item}</option>)}</select></label>
            </div>
          </section>

          <section className="credit-card"><div><span>预计消耗积分</span><small>{count} 张 × 12 分</small></div><strong>{credit}<i>分</i></strong></section>
          <button className="action-button action-button--primary" type="button" disabled={!canGenerate} onClick={generateImages}><Icon name="spark" /><span>生成图片</span><em>GENERATE</em></button>
        </aside>
      </div>
      {snapshot && <DetailPlanDialog key={JSON.stringify({ input: snapshot.input, images: snapshot.images.map((image) => image.id) })} open={planOpen} snapshot={snapshot} onClose={() => setPlanOpen(false)} onResult={receiveResult} />}
    </main>
  );
}
