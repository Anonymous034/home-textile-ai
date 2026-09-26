"""Small, server-only adapter around Alipay's official Python SDK."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient
from alipay.aop.api.domain.AlipayTradeCloseModel import AlipayTradeCloseModel
from alipay.aop.api.domain.AlipayTradePagePayModel import AlipayTradePagePayModel
from alipay.aop.api.domain.AlipayTradeQueryModel import AlipayTradeQueryModel
from alipay.aop.api.request.AlipayTradeCloseRequest import AlipayTradeCloseRequest
from alipay.aop.api.request.AlipayTradePagePayRequest import AlipayTradePagePayRequest
from alipay.aop.api.request.AlipayTradeQueryRequest import AlipayTradeQueryRequest
from alipay.aop.api.response.AlipayTradeCloseResponse import AlipayTradeCloseResponse
from alipay.aop.api.response.AlipayTradeQueryResponse import AlipayTradeQueryResponse
from alipay.aop.api.util.SignatureUtils import get_sign_content, verify_with_rsa


BACKEND_DIR = Path(__file__).resolve().parents[1]
SANDBOX_GATEWAY = "https://openapi.alipaydev.com/gateway.do"
PRODUCTION_GATEWAY = "https://openapi.alipay.com/gateway.do"


class AlipayConfigurationError(RuntimeError):
    pass


class AlipayGatewayError(RuntimeError):
    pass


@dataclass(frozen=True)
class AlipaySettings:
    requested_mode: str
    mode: str
    app_id: str
    app_private_key: str
    alipay_public_key: str
    public_base_url: str
    gateway_url: str
    seller_id: str
    configured: bool

    @property
    def is_mock(self) -> bool:
        return self.mode != "production"


def _key_content(value: str) -> str:
    if not value:
        return ""
    path = Path(value)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def load_alipay_settings() -> AlipaySettings:
    requested = os.getenv("ALIPAY_MODE", "mock").strip().lower()
    if requested not in {"mock", "sandbox", "production"}:
        requested = "mock"
    app_id = os.getenv("ALIPAY_APP_ID", "").strip()
    private_key = _key_content(os.getenv("ALIPAY_APP_PRIVATE_KEY_FILE", ""))
    public_key = _key_content(os.getenv("ALIPAY_PUBLIC_KEY_FILE", ""))
    public_base_url = os.getenv("ALIPAY_PUBLIC_BASE_URL", "").strip().rstrip("/")
    parsed = urlparse(public_base_url)
    valid_base_url = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    configured = requested in {"sandbox", "production"} and bool(app_id and private_key and public_key and valid_base_url)
    mode = requested if configured else "mock"
    default_gateway = SANDBOX_GATEWAY if mode == "sandbox" else PRODUCTION_GATEWAY
    return AlipaySettings(
        requested_mode=requested,
        mode=mode,
        app_id=app_id,
        app_private_key=private_key,
        alipay_public_key=public_key,
        public_base_url=public_base_url,
        gateway_url=os.getenv("ALIPAY_GATEWAY_URL", "").strip() or default_gateway,
        seller_id=os.getenv("ALIPAY_SELLER_ID", "").strip(),
        configured=configured,
    )


class AlipayGateway:
    def __init__(self, settings: AlipaySettings):
        if not settings.configured:
            raise AlipayConfigurationError("支付宝参数尚未配置完整")
        self.settings = settings
        config = AlipayClientConfig()
        config.server_url = settings.gateway_url
        config.app_id = settings.app_id
        config.app_private_key = settings.app_private_key
        config.alipay_public_key = settings.alipay_public_key
        config.sign_type = "RSA2"
        config.timeout = 15
        self.client = DefaultAlipayClient(alipay_client_config=config)

    def create_checkout(self, order_id: str, amount_cents: int, subject: str) -> str:
        model = AlipayTradePagePayModel()
        model.out_trade_no = order_id
        model.total_amount = f"{amount_cents / 100:.2f}"
        model.subject = subject
        model.body = "家具 AI 创作积分充值"
        model.product_code = "FAST_INSTANT_TRADE_PAY"
        model.timeout_express = "15m"
        request = AlipayTradePagePayRequest(biz_model=model)
        request.notify_url = f"{self.settings.public_base_url}/api/payments/alipay/notify"
        request.return_url = f"{self.settings.public_base_url}/api/payments/alipay/return"
        try:
            return self.client.page_execute(request, http_method="GET")
        except Exception as exc:
            raise AlipayGatewayError("支付宝收银台地址生成失败") from exc

    def query(self, order_id: str) -> dict[str, str | None]:
        model = AlipayTradeQueryModel()
        model.out_trade_no = order_id
        request = AlipayTradeQueryRequest(biz_model=model)
        try:
            content = self.client.execute(request)
            response = AlipayTradeQueryResponse()
            response.parse_response_content(content)
        except Exception as exc:
            raise AlipayGatewayError("支付宝订单查询失败") from exc
        return {
            "success": response.is_success(),
            "code": response.code,
            "sub_code": response.sub_code,
            "trade_status": response.trade_status,
            "trade_no": response.trade_no,
            "out_trade_no": response.out_trade_no,
            "total_amount": response.total_amount,
        }

    def close(self, order_id: str) -> dict[str, str | bool | None]:
        model = AlipayTradeCloseModel()
        model.out_trade_no = order_id
        request = AlipayTradeCloseRequest(biz_model=model)
        try:
            content = self.client.execute(request)
            response = AlipayTradeCloseResponse()
            response.parse_response_content(content)
        except Exception as exc:
            raise AlipayGatewayError("支付宝订单关闭失败") from exc
        return {"success": response.is_success(), "code": response.code, "sub_code": response.sub_code}

    def verify_parameters(self, parameters: dict[str, str]) -> bool:
        sign = parameters.get("sign", "")
        sign_type = parameters.get("sign_type", "RSA2")
        if not sign or sign_type.upper() != "RSA2":
            return False
        unsigned = {key: value for key, value in parameters.items() if key not in {"sign", "sign_type"} and value != ""}
        content = get_sign_content(unsigned).encode("utf-8")
        try:
            return verify_with_rsa(self.settings.alipay_public_key, content, sign)
        except Exception:
            return False


def get_alipay_gateway() -> AlipayGateway | None:
    settings = load_alipay_settings()
    return AlipayGateway(settings) if settings.configured else None
