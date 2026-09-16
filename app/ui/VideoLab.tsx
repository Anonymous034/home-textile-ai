"use client";

import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import "./TemplateLab.css";
import "./VideoLab.css";

type ImageAsset = { name: string; url: string };
type ReferenceMode = "链接导入" | "上传视频";

function Icon({ name }: { name: "back" | "upload" | "video" | "link" | "chevron" | "spark" }) {
  const paths = {
    back: <path d="m15 18-6-6 6-6" />,
    upload: <><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" /><path d="M5 15v4h14v-4" /></>,
    video: <><rect x="3" y="5" width="13" height="14" rx="2" /><path d="m16 10 5-3v10l-5-3z" /></>,
    link: <><path d="M10 13a4 4 0 0 0 5.66.04l2.12-2.12a4 4 0 0 0-5.66-5.66l-1.21 1.2" /><path d="M14 11a4 4 0 0 0-5.66-.04l-2.12 2.12a4 4 0 0 0 5.66 5.66l1.21-1.2" /></>,
    chevron: <path d="m8 10 4 4 4-4" />,
    spark: <><path d="m12 3 1.35 4.15L17.5 8.5l-4.15 1.35L12 14l-1.35-4.15L6.5 8.5l4.15-1.35L12 3Z" /><path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z" /></>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

export default function VideoLab() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [assets, setAssets] = useState<ImageAsset[]>([]);
  const [dragging, setDragging] = useState(false);
  const [mode, setMode] = useState<ReferenceMode>("链接导入");
  const [reference, setReference] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [platform, setPlatform] = useState("网页端 16:9");
  const [market, setMarket] = useState("中国");
  const [language, setLanguage] = useState("中文");
  const [duration, setDuration] = useState(10);
  const [resolution, setResolution] = useState("720P");
  const [notes, setNotes] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => () => assets.forEach((asset) => URL.revokeObjectURL(asset.url)), [assets]);

  const addAssets = (files: FileList | null) => {
    const selected = Array.from(files ?? []).filter((file) => ["image/jpeg", "image/png", "image/webp"].includes(file.type)).slice(0, 4 - assets.length);
    if (!selected.length) return;
    setAssets((current) => [...current, ...selected.map((file) => ({ name: file.name, url: URL.createObjectURL(file) }))].slice(0, 4));
    setNotice("");
  };
  const choose = (event: ChangeEvent<HTMLInputElement>) => { addAssets(event.target.files); event.target.value = ""; };
  const drop = (event: DragEvent<HTMLDivElement>) => { event.preventDefault(); setDragging(false); addAssets(event.dataTransfer.files); };
  const credits = duration * (resolution === "1080P" ? 28 : 20);

  return <main className="template-lab video-lab">
    <header className="template-hud">
      <a className="template-back" href="/dashboard?tool=video"><Icon name="back" /><span>返回工作台</span></a>
      <div className="template-brand"><i>42</i><div><strong>VIRAL VIDEO LAB</strong><small>AI 家具视频创作控制台</small></div></div>
      <div className="template-status"><i /><span>LOCAL WORKSPACE</span><b>本地预览</b></div>
    </header>

    <div className="template-layout">
      <section className="template-canvas" aria-label="爆款视频预览画布">
        <div className="template-toolbar"><div><span>视频创作预览</span><i /><span>{assets.length ? `${assets.length} 张产品素材已就绪` : "等待导入产品素材"}</span></div><button type="button" onClick={() => inputRef.current?.click()}><Icon name="upload" />导入产品素材</button></div>
        <div className={`template-stage video-stage ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}>
          <span className="template-grid-glow" /><div className="template-stage-corners" aria-hidden="true"><i /><i /><i /><i /></div>
          {assets.length ? <div className="video-storyboard"><div className="video-storyboard__header"><span>SHOT PLAN / 01</span><strong>{platform}</strong></div><div className="video-storyboard__frames">{assets.map((asset, index) => <figure key={asset.url}><img src={asset.url} alt={`产品素材 ${index + 1}：${asset.name}`} /><figcaption><span>0{index + 1}</span><small>{index === 0 ? "产品主视角" : "细节镜头"}</small></figcaption></figure>)}<div className="video-storyboard__end"><Icon name="video" /><span>AI MOTION</span></div></div><div className="video-storyboard__timeline"><i /><span>0:00</span><b>镜头节奏将在生成时自动编排</b><span>{duration} 秒</span></div></div> : <div className="template-empty"><div className="template-orbit"><Icon name="video" /></div><span>VIRAL VIDEO / CANVAS READY</span><p>添加 1–4 张家具产品图，在右侧配置参考视频与输出规格。</p><button type="button" onClick={() => inputRef.current?.click()}><Icon name="upload" />添加产品素材</button></div>}
        </div>
        <footer className="template-footer"><span><i />{assets.length ? "STORYBOARD READY" : "CANVAS READY"}</span><b>{platform} · {duration} 秒 · {resolution}</b></footer>
      </section>

      <aside className="template-panel video-panel" aria-label="爆款视频设置">
        <section className="template-card video-input-card"><header><div><span>01</span><strong>产品素材</strong></div><em>{assets.length}/4 张</em></header><input ref={inputRef} className="video-file" type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={choose} /><div className={`video-dropzone ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}><button type="button" onClick={() => inputRef.current?.click()}><Icon name="upload" /><strong>上传或拖入图片</strong><small>支持 1–4 张 JPG / PNG / WEBP</small></button></div>{assets.length > 0 && <div className="video-thumbs">{assets.map((asset, index) => <figure key={asset.url}><img src={asset.url} alt="" /><button type="button" aria-label={`移除素材 ${index + 1}`} onClick={() => setAssets((current) => { URL.revokeObjectURL(asset.url); return current.filter((item) => item.url !== asset.url); })}>×</button></figure>)}</div>}</section>
        <section className="template-card video-reference"><header><div><span>02</span><strong>参考视频 <i>（选填）</i></strong></div><em>REFERENCE</em></header><div className="video-tabs">{(["链接导入", "上传视频"] as ReferenceMode[]).map((item) => <button key={item} type="button" className={mode === item ? "is-active" : ""} onClick={() => setMode(item)}>{item}</button>)}</div>{mode === "链接导入" ? <><label><Icon name="link" /><input value={reference} onChange={(event) => setReference(event.target.value)} placeholder="粘贴抖音或小红书视频链接" /></label><div className="video-authorize"><label><input type="checkbox" checked={authorized} onChange={(event) => setAuthorized(event.target.checked)} />已获内容授权</label><button type="button" disabled={!reference || !authorized} onClick={() => setNotice("参考视频导入服务尚未接入；链接仅保留在当前页面，未上传。")}>导入</button></div></> : <button className="video-file-button" type="button" onClick={() => setNotice("视频上传服务尚未接入；当前可先使用产品素材与参数完成预览。")}>选择本地参考视频</button>}</section>
        <section className="template-card video-spec-card"><header><div><span>03</span><strong>平台规格</strong></div></header><label className="video-wide"><select value={platform} onChange={(event) => setPlatform(event.target.value)}>{["网页端 16:9", "通用电商 1:1", "抖音/小红书 9:16"].map((item) => <option key={item}>{item}</option>)}</select></label><div className="video-selects"><label><span>目标市场</span><select value={market} onChange={(event) => setMarket(event.target.value)}>{["中国", "北美", "欧洲", "日韩"].map((item) => <option key={item}>{item}</option>)}</select></label><label><span>语言</span><select value={language} onChange={(event) => setLanguage(event.target.value)}>{["中文", "English", "西班牙语", "法语", "德语", "日语", "韩语"].map((item) => <option key={item}>{item}</option>)}</select></label></div></section>
        <label className="template-note"><span>补充说明 <i>（选填）</i></span><textarea value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={300} placeholder="例如：突出沙发材质与空间氛围" /><small>{notes.length}/300</small></label>
        <section className="template-specs video-output"><label className="video-duration"><span>时长</span><output htmlFor="video-duration-range">{duration} 秒</output><input id="video-duration-range" type="range" min={5} max={15} step={1} value={duration} onChange={(event) => setDuration(Number(event.target.value))} aria-label="视频时长（秒）" /><small><i>5</i><i>10</i><i>15</i></small></label><label><span>清晰度</span><select value={resolution} onChange={(event) => setResolution(event.target.value)}><option>480P</option><option>720P</option><option>1080P</option></select></label></section>
        <div className="template-credit"><span>预计消耗积分<small>生成服务接入后才会扣费</small></span><strong>{credits}<i>分</i></strong></div>
        <button className="template-generate" type="button" disabled={!assets.length} onClick={() => setNotice("爆款视频生成服务尚未接入；已保存当前素材与参数预览，未扣除积分。")}><span>生成爆款视频</span><em><Icon name="spark" /> GENERATE</em></button>{notice && <p className="video-notice" role="status">{notice}</p>}
      </aside>
    </div>
  </main>;
}
