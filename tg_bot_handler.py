import asyncio
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
import subprocess
from keys.key_telegram import TG_KEY

def is_admin(user_id: int) -> bool:
    return user_id == TG_KEY.admin_id

def clean_bot_output(text: str) -> str:
    lines = text.splitlines()
    cleaned = [
        line for line in lines
        if "L1 Address:" not in line and "Account Index:" not in line
    ]
    return "\n".join(cleaned)

async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip().lower().replace("/", "")

    if not is_admin(user_id):
        await update.message.reply_text("⛔ 접근 권한이 없습니다.")
        return

    if text in ["check", "order", "close","reduce"]:
        print(text)
        msg = await update.message.reply_text(f"🛠 `{text}` 실행 중...", parse_mode=ParseMode.MARKDOWN)

        # 실시간 subprocess 실행
        process = subprocess.Popen(
            ["python", "main.py", "--module", text],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        output = ""
        while True:
            line = process.stdout.readline()
            if not line:
                break
            output += line
            safe_output = escape_markdown(clean_bot_output(output[-4000:]), version=2)
            try:
                await msg.edit_text(f"📦{text} 결과:\n```output\n{safe_output}```",parse_mode=ParseMode.MARKDOWN_V2)
            except Exception:
                pass  # 메시지가 너무 자주 수정되면 에러날 수 있음

            await asyncio.sleep(0.1)  # 텔레그램 rate limit 고려
        await msg.edit_text(f"📦{text} 결과:\n```output\n{safe_output}```\n✅ Done",parse_mode=ParseMode.MARKDOWN_V2)
        
        process.wait()
    else:
        await update.message.reply_text("❓ 지원하지 않는 명령입니다.")

def build_menu():
    buttons = [[KeyboardButton("/check"), KeyboardButton("/order"), KeyboardButton("/close"), KeyboardButton("/reduce")]]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 명령을 선택하세요.", reply_markup=build_menu())

def main():
    app = ApplicationBuilder().token(TG_KEY.bot_token).build()

    # ✅ 봇 켜졌다고 관리자에게 메시지 전송
    asyncio.get_event_loop().run_until_complete(
        app.bot.send_message(
            chat_id=TG_KEY.admin_id,
            text="✅ 봇이 켜졌습니다.",
            parse_mode=ParseMode.MARKDOWN
        )
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler(["check", "order", "close","reduce"], handle_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_command))

    print("✅ Telegram bot started")
    app.run_polling()
    
if __name__ == "__main__":
    main()
