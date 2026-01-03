"""
Proxy 설정 템플릿

BrightData 등 프록시 서비스 사용 시 설정
"""
from dataclasses import dataclass
from typing import Optional

@dataclass
class ProxyConfig:
    """프록시 설정"""
    host: str
    port: int
    username: str
    password: str
    # 고정 IP 사용 시 (BrightData ISP 등)
    static_ip: Optional[str] = None

    def build_url(self, ip: Optional[str] = None) -> str:
        """
        프록시 URL 생성
        ip: 특정 IP로 라우팅할 경우 (BrightData datacenter/ISP)
        """
        user = self.username
        if ip:
            # BrightData 형식: user-ip-X.X.X.X
            user = f"{self.username}-ip-{ip}"
        return f"http://{user}:{self.password}@{self.host}:{self.port}"


# BrightData 설정 예시
BRIGHTDATA_CONFIG = ProxyConfig(
    host="brd.superproxy.io",
    port=22225,
    username="brd-customer-CUSTOMER_ID-zone-ZONE_NAME",
    password="YOUR_PASSWORD",
    static_ip=None,  # 고정 IP 있으면 여기에
)

# 사용 예시:
# proxy_url = BRIGHTDATA_CONFIG.build_url()  # 일반
# proxy_url = BRIGHTDATA_CONFIG.build_url("1.2.3.4")  # 특정 IP로 라우팅


# 테스트용 IP 목록 (BrightData ISP 등에서 할당받은 IP들)
TEST_IPS = [
    # "1.2.3.4",
    # "5.6.7.8",
]
