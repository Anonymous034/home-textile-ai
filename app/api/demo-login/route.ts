const expectedAnswers: Record<string, string> = {
  "subtract-17-1": "16",
  "add-8-4": "12",
  "subtract-9-3": "6",
};

export async function POST(request: Request) {
  let body: Record<string, unknown>;

  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return Response.json({ ok: false, message: "提交的信息格式不正确" }, { status: 400 });
  }

  const phone = String(body.phone ?? "").trim();
  const humanAnswer = String(body.humanAnswer ?? "").trim();
  const verificationCode = String(body.verificationCode ?? "").trim();
  const challengeId = String(body.challengeId ?? "");
  const expectedAnswer = expectedAnswers[challengeId];

  if (phone !== "123") {
    return Response.json({ ok: false, message: "演示手机号不正确，请填写 123" }, { status: 400 });
  }
  if (!expectedAnswer || humanAnswer !== expectedAnswer) {
    return Response.json({ ok: false, message: "人机验证答案不正确" }, { status: 400 });
  }
  if (verificationCode !== "123456") {
    return Response.json({ ok: false, message: "验证码不正确，请填写 123456" }, { status: 400 });
  }

  return Response.json({ ok: true });
}
