import asyncio
import os
import shutil
import subprocess
import threading
import zipfile
import logging

import subprocess
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from odmpy.libby import (
    LibbyClient,
)

import requests

logging.basicConfig(
    filename="log.txt",
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

bot_token = ''

async def sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async def run():
        try:
            logger.info(f"sync - {update.effective_message.id}!")
            token = context.args[0]
            
            chat_id = update.effective_chat.id

            # Create a unique download directory for this user based on their chat ID
            odm_setting = f"odm/{chat_id}"
            shutil.rmtree(odm_setting)

            if not os.path.exists(odm_setting):
                os.makedirs(odm_setting)

            libby_client = LibbyClient(settings_folder=odm_setting)
            libby_client.get_chip()
            libby_client.clone_by_code(token)

            # Send a message to the user
            await update.effective_message.reply_text("Synced, now run /list or /download id")
        
        except (IndexError, ValueError) as err:
            logger.error(f"sync error - {odm_setting} - {err}")
            await update.effective_message.reply_text(f"Sync unsuccessful, please use another libby setup code.")

    def thread():
        loop = asyncio.new_event_loop()
        loop.run_until_complete(run())
    threading.Thread(target=thread).start()

async def list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async def run():
        try:
            chat_id = update.effective_chat.id

            # Create a unique download directory for this user based on their chat ID
            odm_setting = f"odm/{chat_id}"
            if not os.path.exists(odm_setting):
                await update.effective_message.reply_text(f"No libby account found, use: /sync XXXXXXXX (8 digit libby setup code)\nTo get a Libby setup code, see https://help.libbyapp.com/en-us/6070.htm")
                await update.effective_message.reply_text(f"Dont worry, this will not log you out from your phone. ")
                
            # Command to run the odmpy command with the specified setting
            command = ['odmpy', 'libby', '--setting', odm_setting]

            # Create a subprocess and connect to its stdout and stderr
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

            proc.stdin.write('\n')
            proc.stdin.flush()

            # Capture the output and errors (if any)
            output = proc.communicate()
            output_string = output[0]  # Access the string within the tuple
            formatted_output = output_string.replace('\\n', '\n')
            output_lines = formatted_output.split('\n')
            processed_output = '\n'.join(output_lines[3:-3])
            
            if not processed_output:
                await update.effective_message.reply_text("Hmm, nothing to see here. Did you have something on your loan or did you successfully did /sync?")    
            else:
                await update.effective_message.reply_text(processed_output)
                logger.info(f"list successful - {odm_setting} - {processed_output}")
        
        except (IndexError, ValueError) as err:
            logger.error(f"list error - {odm_setting} - {err}")
            await update.effective_message.reply_text("List Error")

    def thread():
        loop = asyncio.new_event_loop()
        loop.run_until_complete(run())
    threading.Thread(target=thread).start()


async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async def run():
        try:
            chat_id = update.effective_chat.id
            download_id = context.args[0]
            odm_setting = f"odm/{chat_id}"

            logger.info(f"download initiated - {odm_setting} - {chat_id} - {download_id}")
            await update.effective_message.reply_text("Please wait a while for download to complete")

            # Create a unique download directory for this user based on their chat ID
            #odm_setting = 'odmpy_settings'
            if not os.path.exists(odm_setting):
                await update.effective_message.reply_text("No sync token found, use: /sync token")
                raise Exception("No account found")
            
            download_folder = f"download/{chat_id}"
            if not os.path.exists(download_folder):
                os.makedirs(download_folder)

            # Command to run the odmpy command with the specified setting
            try:
                command = ['odmpy', '--retry', '3', 'libby', '-c', '-k', '-d', download_folder, '--setting', odm_setting, '--select', download_id]
                process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                output = process.stdout.decode('utf-8')
                error_output = process.stderr.decode('utf-8')
                if process.returncode != 0:
                    return
                logger.info(f"download odmpy output - {odm_setting} - {output}")
                logger.error(f"download odmpy error - {odm_setting} - {error_output}")
                
            except Exception as e:
                logger.error(f"download error - {e}")
                return

            audiobook_files = []

            for root, _, files in os.walk(download_folder):
                for file in files:
                    if file.endswith(".mp3") or file.endswith(".jpg") or file.endswith(".png"):
                        filepath = os.path.join(root, file)
                        audiobook_files.append(filepath)
            
            if len(audiobook_files):
                await update.effective_message.reply_text("Download finished, please wait for file to upload.")
                zip_file_path = f"{download_folder}/{chat_id}.zip"

                with zipfile.ZipFile(zip_file_path, "w", compression=zipfile.ZIP_STORED) as zip_file:
                    for file_path in audiobook_files:
                        zip_file.write(file_path, os.path.basename(file_path))

                url = "https://litterbox.catbox.moe/resources/internals/api.php"
                files = {
                    'reqtype': (None, 'fileupload'),
                    'time': (None, '72h'),
                    'fileToUpload': (zip_file_path, open(zip_file_path, 'rb'))
                }
                response = requests.post(url, files=files)
                if response.status_code == 200:
                    uploaded_url = response.text
                    logger.info(f"download upload successful - {odm_setting} - {uploaded_url}")
                    await update.effective_message.reply_text(f"File uploaded successfully. URL: {uploaded_url}")
                    await update.effective_message.reply_text(f"Link will only be valid for 72 hours.")
                else:
                    url = "https://pixeldrain.com/api/file"
                    files = {'file': (zip_file_path, open(zip_file_path, 'rb'))}
                    response = requests.post(url, files=files)
                    if response.status_code == 201:
                        data = response.json()  # Parse the JSON response
                        if data.get("success") and "id" in data:
                            file_id = data["id"]
                            file_url = f"https://pixeldrain.com/u/{file_id}"
                            print("File URL:", file_url)
                            logger.info(f"download upload successful - {odm_setting} - {file_url}")
                            await update.effective_message.reply_text(f"File uploaded successfully. URL: {file_url}")
                            #await update.effective_message.reply_text(f"Link will only be valid for 72 hours.")
                    else:
                        logger.error(f"download upload fail - {odm_setting} - {response}")
                        await update.effective_message.reply_text("Error uploading the file. Likely file hosts are down. Please try again later.")

                # Delete the chat ID directory and its contents from the local file system
            else:
                logger.error(f"No books to be found here")
                await update.effective_message.reply_text("Hmm, it doesnt seems I've downloaded any audiobook, check with /list to make sure its a valid audiobook you're downloading.")

            shutil.rmtree(download_folder)
        
        except (IndexError, ValueError) as err:
            logger.error(f"download error - {odm_setting} - {err}")
            await update.effective_message.reply_text("Error")

    def thread():
        loop = asyncio.new_event_loop()
        loop.run_until_complete(run())
    threading.Thread(target=thread).start()



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Libby Bot is ONLINE. I can download audiobook from your library.\nTo start, use /sync XXXXXXXX (8 digit Libby setup code).\nTo get a Libby setup code, see https://help.libbyapp.com/en-us/6070.htm\nDont worry, this will not log you out from your phone.\nIf you recently used the chatbot and successfully linked your libby account, you can move on to /list or /download function.\nThen use /list to list down audiobooks available to download, and use /download number to specify one title to be downloaded. Example: /download 1\nWait a while then a download link will be provided to you.\nDownload link is valid for 3 days, if audiobook is larger than 1GB, then upload will fail."
    )

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"I can download audiobook from your library.\nTo start, use /sync XXXXXXXX (8 digit Libby setup code).\nTo get a Libby setup code, see https://help.libbyapp.com/en-us/6070.htm\nDont worry, this will not log you out from your phone.\nIf you recently used the chatbot and successfully linked your libby account, you can move on to /list or /download function.\nThen use /list to list down audiobooks available to download, and use /download number to specify one title to be downloaded. Example: /download 1\nWait a while then a download link will be provided to you.\nDownload link is valid for 3 days, if audiobook is larger than 1GB, then upload will fail."
    )


if __name__ == "__main__":

    application = Application.builder().token(bot_token).build()

    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)

    sync_handler = CommandHandler('sync', sync)
    application.add_handler(sync_handler)

    list_handler = CommandHandler('list', list)
    application.add_handler(list_handler)

    download_handler = CommandHandler('download', download)
    application.add_handler(download_handler)

    help_handler = CommandHandler('help', help)
    application.add_handler(help_handler)

    # block thread!!

    application.run_polling()
