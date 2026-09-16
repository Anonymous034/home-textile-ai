import type { Metadata } from "next";
import PatternLab from "../ui/PatternLab";

export const metadata: Metadata = {
  title: "花型创作｜家纺AI视觉工作台",
  description: "上传花型元素，调整连续方式、尺寸与底色，预览并导出平铺花型。",
};

export default function PatternPage() {
  return <PatternLab />;
}
