from dataclasses import dataclass

@dataclass
class TelegramKey:
    admin_id: int
    bot_token: str

# trading account
TG_KEY = TelegramKey(
    admin_id = 1234, # your tg id, use id bot to find it
    bot_token= 'yourbot_token'
) 