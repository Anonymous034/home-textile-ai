import type { Metadata } from "next";
import BuyerShowLab from "../ui/BuyerShowLab";

export const metadata: Metadata = {
  title: "买家秀｜强视觉ai生图",
  description: "导入产品图片，配置买家秀风格、张数与输出参数。",
};

export default function BuyerShowPage() {
  return <BuyerShowLab />;
}
