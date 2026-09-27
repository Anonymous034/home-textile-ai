import type { Metadata } from "next";
import UpscaleLab from "../ui/UpscaleLab";

export const metadata: Metadata = {
  title: "一键高清｜强视觉ai生图",
  description: "批量导入图片，预览素材并配置高清处理方式。",
};

export default function UpscalePage() {
  return <UpscaleLab />;
}
