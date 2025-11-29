from dataclasses import dataclass

@dataclass
class PacificaKEY:
    public_key: str
    agent_public_key: str
    agent_private_key: str
    
PACIFICA_KEY = PacificaKEY(
    public_key = "", # 지갑 주소
    agent_public_key = "", # api 만드는곳에서 생성
    agent_private_key = "" # api 만드는곳에서 생성
)
