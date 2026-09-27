import type { Metadata } from "next";
import LocalEditLab from "../ui/LocalEditLab";

export const metadata: Metadata = {
  title: "局部编辑｜家纺AI视觉工作台",
  description: "上传产品图片，框选需要精修的局部区域并设置输出参数。",
};

export default function LocalEditPage() {
  return <LocalEditLab />;
}
