import unittest

import rsa
from Crypto.PublicKey import RSA
from alipay.aop.api.util.SignatureUtils import get_sign_content, sign_with_rsa2

from backend.app.alipay_gateway import AlipayGateway, AlipaySettings


class AlipayGatewayTests(unittest.TestCase):
    def test_rsa2_notification_verification_rejects_tampering(self):
        public_key, private_key = rsa.newkeys(2048)
        public_pem = RSA.import_key(public_key.save_pkcs1(format="PEM")).publickey().export_key().decode()
        private_pem = private_key.save_pkcs1(format="PEM").decode()
        settings = AlipaySettings(
            requested_mode="sandbox", mode="sandbox", app_id="sandbox-app",
            app_private_key=private_pem, alipay_public_key=public_pem,
            public_base_url="http://example.test", gateway_url="https://openapi.alipaydev.com/gateway.do",
            seller_id="", configured=True,
        )
        gateway = object.__new__(AlipayGateway)
        gateway.settings = settings
        parameters = {
            "app_id": "sandbox-app", "out_trade_no": "ALI001", "total_amount": "199.00",
            "trade_status": "TRADE_SUCCESS", "sign_type": "RSA2",
        }
        parameters["sign"] = sign_with_rsa2(private_pem, get_sign_content({key: value for key, value in parameters.items() if key != "sign_type"}), "utf-8")
        self.assertTrue(gateway.verify_parameters(parameters))
        self.assertFalse(gateway.verify_parameters({**parameters, "total_amount": "1.00"}))


if __name__ == "__main__":
    unittest.main()
