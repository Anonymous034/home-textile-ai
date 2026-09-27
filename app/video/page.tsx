import type { Metadata } from "next";
import VideoLab from "../ui/VideoLab";

export const metadata: Metadata = {
  title: "爆款视频｜强视觉ai生图",
  description: "导入产品素材，配置视频参考、平台规格与输出参数。",
};

export default function VideoPage() {
  return <VideoLab />;
}
