from telegram.ext import Updater, CommandHandler

# Bot ka start command
def start(update, context):
    update.message.reply_text("Hello! I'm alive 🚀")

def help_command(update, context):
    update.message.reply_text("Use /start to check I'm alive.")

def main():
    # Yahan apna token daalo
    TOKEN = "7692558555:AAGQNbUyBRqiictdEsbCIon8jzEPAtGnZHQ"
    
    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()