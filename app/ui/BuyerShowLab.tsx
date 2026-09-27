"use client";

import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import "./TemplateLab.css";
import "./BuyerShowLab.css";
import BuyerPlanDialog, { type BuyerPlanDraft } from "./BuyerPlanDialog";
import { buyerResultUrl, type BuyerTask } from "../buyer-show/api";

type ProductImage = { url: string; name: string; file: File };

function Icon({ name }: { name: "back" | "upload" | "buyer" | "chevron" | "spark" }) {
  const paths = {
    back: <path d="m15 18-6-6 6-6" />,
    upload: <><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" /><path d="M5 15v4h14v-4" /></>,
    buyer: <><rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="12" cy="9" r="3" /><path d="M6 19v-2a6 6 0 0 1 12 0v2" /></>,
    chevron: <path d="m8 10 4 4 4-4" />,
    spark: <><path d="m12 3 1.35 4.15L17.5 8.5l-4.15 1.35L12 14l-1.35-4.15L6.5 8.5l4.15-1.35L12 3Z" /><path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z" /></>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

export default function BuyerShowLab() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [product, setProduct] = useState<ProductImage | null>(null);
  const [style, setStyle] = useState("更真实");
  const [productName, setProductName] = useState("");
  const [productFeatures, setProductFeatures] = useState("");
  const [material, setMaterial] = useState("");
  const [sellingPoints, setSellingPoints] = useState("");
  const [count, setCount] = useState(1);
  const [ratio, setRatio] = useState("3:4");
  const [resolution, setResolution] = useState("1K");
  const [notes, setNotes] = useState("");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<BuyerPlanDraft | null>(null);
  const [result, setResult] = useState<BuyerTask | null>(null);

  useEffect(() => {
    if (!product) return;
    return () => URL.revokeObjectURL(product.url);
  }, [product]);

  const importImage = (files: FileList | null) => {
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
    setError("");
    setProduct({ url: URL.createObjectURL(file), name: file.name, file });
    setProductName((current) => current || file.name.replace(/\.[^.]+$/, ""));
  };

  const onChoose = (event: ChangeEvent<HTMLInputElement>) => {
    importImage(event.target.files);
    event.target.value = "";
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    importImage(event.dataTransfer.files);
  };

  const imageError = () => {
    setProduct(null);
    setError("无法读取这张图片，请换一张有效的产品图。");
  };

  const generate = () => {
    if (!product) return;
    if (!productName.trim()) { setError("请填写产品名称。"); return; }
    setError("");
    setDraft({ file: product.file, productName, productFeatures, material, sellingPoints, notes, style: style as "更真实" | "更精致", count, ratio, resolution });
  };
  const handleComplete = useCallback((task: BuyerTask) => { setResult(task); }, []);
  const handleProgress = useCallback((task: BuyerTask) => { setResult(task); }, []);

  return (
    <main className="template-lab buyer-lab">
      <header className="template-hud">
        <a className="template-back" href="/dashboard?tool=buyer-show"><Icon name="back" /><span>返回</span></a>
        <div className="template-brand"><i>42</i><div><strong>BUYER SHOW LAB</strong><small>AI 买家秀创作控制台</small></div></div>
        <div className="template-status"><i /><span>LOCAL WORKSPACE</span><b>本地预览</b></div>
      </header>

      <div className="template-layout">
        <section className="template-canvas" aria-label="买家秀画布">
          <div className="template-toolbar">
            <div><span>产品素材预览</span><i /><span>支持拖入图片</span></div>
            <button type="button" onClick={() => inputRef.current?.click()}><Icon name="upload" />导入到画布</button>
          </div>
          <div className={`template-stage buyer-stage ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }} onDrop={onDrop}>
            <span className="template-grid-glow" aria-hidden="true" />
            <div className="template-stage-corners" aria-hidden="true"><i /><i /><i /><i /></div>
            {result?.items.some((item) => item.previewUrl) ? (
              <div className="buyer-result-grid">{result.items.filter((item) => item.previewUrl).map((item) => <a key={item.index} href={buyerResultUrl(item.downloadUrl!)}><img src={buyerResultUrl(item.previewUrl!)} alt={`生活场景结果 ${item.index}`} /><span>#{String(item.index).padStart(2, "0")} 下载图片</span></a>)}</div>
            ) : product ? (
              <figure className="buyer-product-preview">
                <img src={product.url} alt={`产品原图：${product.name}`} onError={imageError} />
                <figcaption><span>产品原图预览 · 非生成结果</span><strong>{product.name}</strong></figcaption>
              </figure>
            ) : (
              <div className="template-empty buyer-empty">
                <div className="template-orbit"><Icon name="buyer" /></div>
                <span>BUYER SHOW / CANVAS READY</span>
                <p>导入产品图片，在右侧选择风格与输出参数。</p>
                <button type="button" onClick={() => inputRef.current?.click()}><Icon name="upload" />添加产品图</button>
              </div>
            )}
          </div>
          <footer className="template-footer"><span><i />{product ? "SOURCE LOADED" : "CANVAS READY"}</span><b>{style} · {count} 张 · {ratio} · {resolution}</b></footer>
        </section>

        <aside className="template-panel buyer-panel" aria-label="买家秀设置">
          <div className="buyer-tool-menu template-panel-title"><span><i><Icon name="buyer" /></i><h1>买家秀</h1></span></div>

          <section className="template-card buyer-upload-card">
            <header><div><span>01</span><strong>产品图片</strong></div><em>PRODUCT INPUT</em></header>
            <input ref={inputRef} id="buyer-product-input" className="buyer-file-input" type="file" accept="image/jpeg,image/png,image/webp" aria-label="上传产品图片" onChange={onChoose} />
            <div className={`buyer-dropzone ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
              <button type="button" onClick={() => inputRef.current?.click()} aria-label={product ? "更换产品图片" : "上传产品图片"}>
                {product ? <img src={product.url} alt="已上传产品缩略图" onError={imageError} /> : <span className="buyer-upload-icon"><Icon name="upload" /></span>}
                <strong>{product ? "点击更换产品图" : "上传或拖入产品图"}</strong>
                <small>JPG / PNG / WEBP · 不超过 20MB</small>
              </button>
            </div>
            {product && <div className="buyer-file-meta"><span title={product.name}>{product.name}</span><button type="button" onClick={() => { setProduct(null); setError(""); }}>移除</button></div>}
            {error && <p className="buyer-error" role="alert">{error}</p>}
          </section>

          <section className="template-card buyer-options-card">
            <fieldset><legend><span>02</span>买家秀风格</legend><div className="buyer-segments buyer-segments--two">{["更真实", "更精致"].map((item) => <label key={item}><input type="radio" name="buyer-style" value={item} checked={style === item} onChange={() => setStyle(item)} /><span>{item}</span></label>)}</div></fieldset>
            <div className="buyer-divider" />
            <label className="buyer-count-input"><span>生成张数</span><input name="buyer-count" type="number" min={1} max={12} value={count} onChange={(event) => setCount(Math.min(12, Math.max(1, Number(event.target.value) || 1)))} /><em>1–12 张</em></label>
          </section>

          <section className="template-card buyer-info-card">
            <header><div><span>03</span><strong>产品信息</strong></div><em>PRODUCT DATA</em></header>
            <label><span>产品名称 <i>必填</i></span><input value={productName} maxLength={120} onChange={(event) => setProductName(event.target.value)} placeholder="例如：全棉四件套" /></label>
            <label><span>产品特征 <i>选填</i></span><textarea value={productFeatures} maxLength={1000} onChange={(event) => setProductFeatures(event.target.value)} placeholder="颜色、纹理、版型与结构特征" /></label>
            <label><span>材质 / 工艺 <i>选填</i></span><input value={material} maxLength={500} onChange={(event) => setMaterial(event.target.value)} placeholder="例如：300g 重磅精梳棉" /></label>
            <label><span>核心卖点 <i>选填</i></span><textarea value={sellingPoints} maxLength={1000} onChange={(event) => setSellingPoints(event.target.value)} placeholder="适用场景、功能与卖点" /></label>
          </section>

          <section className="template-specs">
            <label><span>图片比例</span><select value={ratio} onChange={(event) => setRatio(event.target.value)}>{["3:4", "1:1", "4:3", "9:16", "16:9"].map((item) => <option key={item}>{item}</option>)}</select></label>
            <label><span>分辨率</span><select value={resolution} onChange={(event) => setResolution(event.target.value)}>{["1K", "2K", "4K"].map((item) => <option key={item}>{item}</option>)}</select></label>
          </section>

          <label className="template-note"><span>补充说明 <i>（选填）</i></span><textarea value={notes} maxLength={300} onChange={(event) => setNotes(event.target.value)} placeholder="请输入补充说明" /><small aria-hidden="true">{notes.length}/300</small></label>
          <div className="template-credit" aria-live="polite"><span>预计消耗积分<small>{count} 张 × 8 分 · 当前不会扣费</small></span><strong>{count * 8}<i>分</i></strong></div>
          <button className="template-generate" type="button" disabled={!product || !productName.trim() || Boolean(draft)} onClick={generate}><span><Icon name="spark" />生成图像</span></button>
        </aside>
      </div>
      {draft && <BuyerPlanDialog draft={draft} onClose={() => setDraft(null)} onProgress={handleProgress} onComplete={handleComplete} />}
    </main>
  );
}
