"""Public payment callbacks. No account identity is inferred from callback requests."""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from .account import amount_to_cents, settle_alipay_order
from .alipay_gateway import get_alipay_gateway, load_alipay_settings

router = APIRouter(prefix="/api/payments", tags=["payments"])
logger = logging.getLogger(__name__)


def _string_parameters(items) -> dict[str, str]:
    return {str(key): str(value) for key, value in items if isinstance(value, (str, int, float))}


@router.post("/alipay/notify", response_class=PlainTextResponse)
async def alipay_notify(request: Request) -> PlainTextResponse:
    gateway = get_alipay_gateway()
    if not gateway:
        return PlainTextResponse("failure")
    form = await request.form()
    parameters = _string_parameters(form.multi_items())
    if not gateway.verify_parameters(parameters):
        logger.warning("Rejected Alipay notification: signature verification failed")
        return PlainTextResponse("failure")
    settings = gateway.settings
    if parameters.get("app_id") != settings.app_id:
        logger.warning("Rejected Alipay notification: app_id mismatch")
        return PlainTextResponse("failure")
    if settings.seller_id and parameters.get("seller_id") != settings.seller_id:
        logger.warning("Rejected Alipay notification: seller_id mismatch")
        return PlainTextResponse("failure")
    if parameters.get("trade_status") not in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        return PlainTextResponse("success")
    try:
        settle_alipay_order(
            parameters.get("out_trade_no", ""),
            parameters.get("trade_no", ""),
            amount_to_cents(parameters.get("total_amount")),
            parameters.get("notify_time"),
        )
    except ValueError as exc:
        logger.warning("Rejected Alipay notification: %s", exc)
        return PlainTextResponse("failure")
    return PlainTextResponse("success")


@router.get("/alipay/return")
def alipay_return(request: Request) -> RedirectResponse:
    settings = load_alipay_settings()
    gateway = get_alipay_gateway()
    fallback = settings.public_base_url or "http://49.232.95.85"
    parameters = _string_parameters(request.query_params.multi_items())
    if not gateway or not gateway.verify_parameters(parameters):
        return RedirectResponse(f"{fallback}/recharge?alipay_return=invalid", status_code=303)
    order_id = quote(parameters.get("out_trade_no", ""), safe="")
    return RedirectResponse(f"{gateway.settings.public_base_url}/recharge?order_id={order_id}&alipay_return=1", status_code=303)
