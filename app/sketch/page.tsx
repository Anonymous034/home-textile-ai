import type { Metadata } from "next";
import SketchLab from "../ui/SketchLab";

export const metadata: Metadata = {
  title: "画稿生图｜家纺AI视觉工作台",
  description: "导入 A/B 版画稿、参考图，配置品类、面料与输出参数。",
};

export default function SketchPage() { return <SketchLab />; }
