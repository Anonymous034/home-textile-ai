"use client";

import {
  CSSProperties,
  ElementType,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { gsap } from "gsap";
import "./MaskedHeading.css";

const clamp = (value: number, min: number, max: number) =>
  value < min ? min : value > max ? max : value;

type MaskedHeadingProps = {
  id?: string;
  text?: string;
  tag?: ElementType;
  mediaType?: "image" | "video";
  src: string;
  poster?: string;
  fillScale?: number;
  parallax?: number;
  drift?: number;
  brightness?: number;
  saturation?: number;
  grayscale?: boolean;
  reveal?: "rise" | "wipe" | "fade" | "none";
  duration?: number;
  stagger?: number;
  trigger?: "view" | "hover" | "load";
  align?: CSSProperties["textAlign"];
  weight?: number;
  tracking?: number;
  lineHeight?: number;
  textScale?: number;
  className?: string;
  style?: CSSProperties;
};

export default function MaskedHeading({
  id,
  text = "Designed in the details",
  tag: Tag = "h2",
  mediaType = "image",
  src,
  poster = "",
  fillScale = 1.25,
  parallax = 26,
  drift = 18,
  brightness = 1,
  saturation = 1,
  grayscale = false,
  reveal = "rise",
  duration = 1.1,
  stagger = 0.09,
  trigger = "view",
  align = "center",
  weight = 700,
  tracking = -0.03,
  lineHeight = 1.06,
  textScale = 0.115,
  className = "",
  style,
}: MaskedHeadingProps) {
  const rootRef = useRef<HTMLElement | null>(null);
  const measureRef = useRef<HTMLSpanElement | null>(null);
  const revealRef = useRef<HTMLSpanElement | null>(null);
  const mediaRef = useRef<HTMLSpanElement | null>(null);
  const wordRefs = useRef<Array<HTMLSpanElement | null>>([]);
  const baseRefs = useRef<Array<HTMLElement | null>>([]);
  const glyphRefs = useRef<Array<SVGTextElement | null>>([]);
  const tweenRef = useRef<gsap.core.Tween | null>(null);
  const offsetRef = useRef({ x: 0, y: 0, tx: 0, ty: 0 });
  const [reduceMotion, setReduceMotion] = useState(false);
  const [mediaFailed, setMediaFailed] = useState(false);

  const clipId = `mh-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const words = useMemo(() => String(text).split(/\s+/).filter(Boolean), [text]);
  const settingsRef = useRef({ fillScale, parallax, drift, brightness, saturation, grayscale, textScale });
  settingsRef.current = { fillScale, parallax, drift, brightness, saturation, grayscale, textScale };

  const place = useCallback(() => {
    const root = rootRef.current;
    const media = mediaRef.current;
    if (!root || !media) return;
    const settings = settingsRef.current;
    const maxX = Math.max(0, ((settings.fillScale - 1) / 2) * root.clientWidth);
    const maxY = Math.max(0, ((settings.fillScale - 1) / 2) * root.clientHeight);
    const offset = offsetRef.current;
    media.style.transform = `translate3d(${clamp(offset.x, -maxX, maxX).toFixed(2)}px, ${clamp(offset.y, -maxY, maxY).toFixed(2)}px, 0) scale(${settings.fillScale})`;
    media.style.filter = `brightness(${settings.brightness}) saturate(${settings.saturation})${settings.grayscale ? " grayscale(1)" : ""}`;
  }, []);

  const sync = useCallback(() => {
    const root = rootRef.current;
    const measure = measureRef.current;
    if (!root || !measure) return;
    root.style.fontSize = `${clamp(root.clientWidth * settingsRef.current.textScale, 32, 150).toFixed(1)}px`;
    const computed = window.getComputedStyle(measure);
    wordRefs.current.forEach((word, index) => {
      const baseline = baseRefs.current[index];
      const glyph = glyphRefs.current[index];
      if (!word || !baseline || !glyph) return;
      glyph.setAttribute("x", `${word.offsetLeft}`);
      glyph.setAttribute("y", `${baseline.offsetTop}`);
      glyph.style.fontFamily = computed.fontFamily;
      glyph.style.fontSize = computed.fontSize;
      glyph.style.fontWeight = computed.fontWeight;
      glyph.style.fontStyle = computed.fontStyle;
      glyph.style.letterSpacing = computed.letterSpacing;
    });
    place();
  }, [place]);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduceMotion(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    sync();
    const observer = new ResizeObserver(sync);
    observer.observe(root);
    document.fonts?.ready.then(sync).catch(() => undefined);
    if (reduceMotion) {
      place();
      return () => observer.disconnect();
    }

    let frameId = 0;
    let last = performance.now();
    let clock = 0;
    const frame = (now: number) => {
      const delta = Math.min(0.05, (now - last) / 1000);
      last = now;
      clock += delta;
      const settings = settingsRef.current;
      const offset = offsetRef.current;
      const ease = 1 - Math.exp(-delta / 0.18);
      offset.x += (offset.tx + Math.sin(clock * 0.21) * settings.drift - offset.x) * ease;
      offset.y += (offset.ty + Math.cos(clock * 0.17) * settings.drift * 0.6 - offset.y) * ease;
      place();
      frameId = requestAnimationFrame(frame);
    };
    const onMove = (event: PointerEvent) => {
      const rect = root.getBoundingClientRect();
      const amount = settingsRef.current.parallax;
      offsetRef.current.tx = clamp(((event.clientX - rect.left) / (rect.width || 1)) * 2 - 1, -1, 1) * -amount;
      offsetRef.current.ty = clamp(((event.clientY - rect.top) / (rect.height || 1)) * 2 - 1, -1, 1) * -amount;
    };
    const onLeave = () => {
      offsetRef.current.tx = 0;
      offsetRef.current.ty = 0;
    };
    root.addEventListener("pointermove", onMove);
    root.addEventListener("pointerleave", onLeave);
    frameId = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(frameId);
      observer.disconnect();
      root.removeEventListener("pointermove", onMove);
      root.removeEventListener("pointerleave", onLeave);
    };
  }, [place, reduceMotion, sync]);

  useEffect(() => {
    const root = rootRef.current;
    const layer = revealRef.current;
    const glyphs = glyphRefs.current.filter(Boolean) as SVGTextElement[];
    if (!root || !layer || !glyphs.length || reduceMotion || reveal === "none") return;
    const distance = () => (parseFloat(window.getComputedStyle(root).fontSize) || 48) * 1.15;
    const play = () => {
      tweenRef.current?.kill();
      if (reveal === "rise") {
        gsap.set(layer, { opacity: 1, scale: 1, clipPath: "inset(0 0 0 0)" });
        tweenRef.current = gsap.fromTo(glyphs, { y: distance() }, { y: 0, duration, stagger, ease: "power4.out", overwrite: "auto" });
      } else if (reveal === "wipe") {
        tweenRef.current = gsap.fromTo(layer, { clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0% 0 0)", duration, ease: "power3.inOut" });
      } else {
        tweenRef.current = gsap.fromTo(layer, { opacity: 0, scale: 1.08 }, { opacity: 1, scale: 1, duration, ease: "power3.out" });
      }
    };
    if (trigger === "hover") {
      root.addEventListener("pointerenter", play);
      return () => root.removeEventListener("pointerenter", play);
    }
    if (trigger === "view") {
      const observer = new IntersectionObserver(entries => {
        if (entries.some(entry => entry.isIntersecting)) {
          play();
          observer.disconnect();
        }
      }, { threshold: 0.25 });
      observer.observe(root);
      return () => observer.disconnect();
    }
    play();
    return () => tweenRef.current?.kill();
  }, [duration, reduceMotion, reveal, stagger, trigger, words]);

  const fallback = mediaFailed || (!src && !poster);
  const HeadingTag = Tag as ElementType;

  return (
    <HeadingTag
      id={id}
      ref={rootRef}
      aria-label={text}
      className={`masked-heading ${fallback ? "masked-heading--fallback" : ""} ${className}`.trim()}
      style={{ textAlign: align, fontWeight: weight, letterSpacing: `${tracking}em`, lineHeight, ...style }}
    >
      <span ref={measureRef} className="masked-heading__measure" aria-hidden="true">
        {words.map((word, index) => (
          <span key={`${word}-${index}`} ref={element => { wordRefs.current[index] = element; }} className="masked-heading__word">
            {word}<i ref={element => { baseRefs.current[index] = element; }} className="masked-heading__baseline" />
          </span>
        ))}
      </span>
      <svg className="masked-heading__defs" aria-hidden="true" focusable="false">
        <defs>
          <clipPath id={clipId} clipPathUnits="userSpaceOnUse">
            {words.map((word, index) => <text key={`${word}-${index}`} ref={element => { glyphRefs.current[index] = element; }}>{word}</text>)}
          </clipPath>
        </defs>
      </svg>
      <span ref={revealRef} className="masked-heading__reveal" aria-hidden="true">
        <span className="masked-heading__clip" style={{ clipPath: `url(#${clipId})` }}>
          <span ref={mediaRef} className="masked-heading__media">
            {mediaType === "video" && !reduceMotion ? (
              <video className="masked-heading__source" src={src} poster={poster} autoPlay muted loop playsInline preload="metadata" onError={() => setMediaFailed(true)} />
            ) : (
              <img className="masked-heading__source" src={reduceMotion && poster ? poster : src} alt="" draggable={false} onError={() => setMediaFailed(true)} />
            )}
          </span>
        </span>
      </span>
    </HeadingTag>
  );
}
