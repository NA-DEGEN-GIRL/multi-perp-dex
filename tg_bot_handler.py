import asyncio
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
import subprocess
from keys.key_telegram import TG_KEY
import time
import logging

def is_admin(user_id: int) -> bool:
    return user_id == TG_KEY.admin_id

def clean_bot_output(text: str) -> str:
    lines = text.splitlines()
    cleaned = [
        line for line in lines
        if "L1 Address:" not in line and "Account Index:" not in line
    ]
    return "\n".join(cleaned)

is_printing = False
print_task = None

async def stream_log(message,context,update):
    log_file = f"trade_auto_run.log"
    tail_lines = 10
    max_lines = 15
    edit_interval = 60
    min_interval = 60
    max_interval = 300
    buffer = []
    last_sent = None

    def format_block(lines):
        trimmed = lines[-max_lines:]
        quoted = '\n'.join([f"> {line.rstrip()}" for line in trimmed])
        content = f"{quoted}"
        safe_output = escape_markdown(content, version=2)[-3000:]
        return f"🖥 출력중\.\.\.```trade_auto_run.log\n{safe_output}```" #content[:1000]

    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()
            buffer = lines[-tail_lines:]
            initial_text = format_block(buffer)
            sent = await context.bot.send_message(chat_id=update.effective_user.id, text=initial_text, parse_mode=ParseMode.MARKDOWN_V2)
            #await message.edit_text(initial_text, parse_mode=ParseMode.MARKDOWN_V2)
            last_sent = initial_text
            f.seek(0, 2)
            last_edit_time = 0
            while is_printing:
                chunk = f.read()
                if chunk:
                    lines = chunk.splitlines(keepends=True)
                    buffer.extend(lines)
                    if len(buffer) > max_lines:
                        buffer = buffer[-max_lines:]
                    new_text = format_block(buffer)
                    #if new_text != last_sent:
                        
                    now = time.monotonic()
                    if now - last_edit_time >= edit_interval:
                        try:
                            #sent = await message.edit_text(new_text, parse_mode=ParseMode.MARKDOWN_V2)
                            await sent.delete()
                            sent = await context.bot.send_message(chat_id=update.effective_user.id, text=new_text, parse_mode=ParseMode.MARKDOWN_V2)
                            last_sent = new_text
                            last_edit_time = now
                            edit_interval = max(min_interval, edit_interval * 0.9)  # 점진적 감소

                        except Exception as e:
                            if "Too Many Requests" in str(e) or "Flood control exceeded" in str(e):
                                edit_interval = max_interval
                                logging.warning(f"Flood control triggered. Increasing interval to {edit_interval:.1f}s")
                            else:
                                logging.warning(f"메시지 수정 실패: {e}")
                        #await asyncio.sleep(5)
                else:
                    await asyncio.sleep(0.1)
    except Exception as e:
        logging.error(e, exc_info=True)


async def handle_log_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_printing, print_task
    try:
        sent = await context.bot.send_message(chat_id=update.effective_user.id, text=f"🖥 오토런 출력중...")
        is_printing = True
        task = asyncio.create_task(stream_log(sent,context,update))
        print_task = task
    except asyncio.CancelledError:
        logging.info("Log streaming cancelled.")

async def handle_stop_stream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_printing, print_task
    is_printing = False
    if print_task:
        print_task.cancel()
        
    await update.message.reply_text(f"출력 중단됨")    

async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip().lower().replace("/", "")
    edit_interval = 3
    min_interval = 3
    max_interval = 10

    if not is_admin(user_id):
        await update.message.reply_text("⛔ 접근 권한이 없습니다.")
        return

    if text in ["check", "order", "close", "reduce", "print", "stop_print", "auto", "kill"]:
        msg = await update.message.reply_text(f"🛠 `{text}` 실행 중\.\.\.", parse_mode=ParseMode.MARKDOWN_V2)

        if text == "print":
            await handle_log_stream(update,context)
            await update.message.reply_text("✅ 출력 실행됨")
            return
        elif text == "stop_print":
            await handle_stop_stream(update,context)
            await update.message.reply_text("🛑 출력 중단됨")
            return 
        
        elif text == 'kill':
            print("pkill", "-f", '"python main.py --module auto"')
            result = subprocess.run(["pkill", "-f", "python -u main.py --module auto"], check=False)
            if result.returncode == 0:
                await update.message.reply_text("🛑 오토런 프로세스 종료됨")
            else:
                await update.message.reply_text("⚠️ 종료할 프로세스가 없음 또는 실패")
            return
            
        elif text == "auto":
            print(f"nohup python -u main.py --module auto > trade_auto_run.log 2>&1 &")
            subprocess.Popen(
                f"nohup python -u main.py --module auto > trade_auto_run.log 2>&1 &",
                shell=True
            )
            await update.message.reply_text(f"✅ 오토런 실행됨")
            return
        
        else:
            process = subprocess.Popen(
                ["python", "main.py", "--module", text],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

        output_lines = []
        buffer = ""
        last_edit = time.monotonic()

        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                output_lines.append(line)
                buffer += line

            # 1.5초마다 edit_text
            now = time.monotonic()
            if now - last_edit >= edit_interval:
                safe_output = escape_markdown(clean_bot_output("".join(output_lines))[-2000:], version=2)
                try:
                    await sent.delete()
                except Exception as e:
                    pass
                try:
                    sent = await context.bot.send_message(chat_id=update.effective_user.id, text=f"📦{text} 결과:\n```output\n{safe_output}```", parse_mode=ParseMode.MARKDOWN_V2)
                    last_edit = now
                    edit_interval = max(min_interval, edit_interval * 0.9)  # 점진적 감소
                except Exception as e:
                    if "Too Many Requests" in str(e) or "Flood control exceeded" in str(e):
                        edit_interval = max_interval
                        print(f"Flood control triggered. Increasing interval to {edit_interval:.1f}s")
                    else:
                        print(f"메시지 수정 실패: {e}")

            #await asyncio.sleep(3)  # CPU 너무 안 잡아먹게

        # 최종 결과
        await sent.delete()
        safe_output = escape_markdown(clean_bot_output("".join(output_lines))[-2000:], version=2)
        sent = await context.bot.send_message(chat_id=update.effective_user.id, text=f"📦{text} 결과:\n```output\n{safe_output}```\n✅ Done", parse_mode=ParseMode.MARKDOWN_V2)

    else:
        await update.message.reply_text("❓ 지원하지 않는 명령입니다.")

def build_menu():
    buttons = [[KeyboardButton("/check"), KeyboardButton("/order"), KeyboardButton("/close"), KeyboardButton("/reduce")],
               [KeyboardButton("/auto"),KeyboardButton("/print"), KeyboardButton("/stop_print") , KeyboardButton("/kill")]]
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
    app.add_handler(CommandHandler(["check", "order", "close","reduce","auto","print","stop_print","kill"], handle_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_command))

    print("✅ Telegram bot started")
    app.run_polling()
    
if __name__ == "__main__":
    main()
