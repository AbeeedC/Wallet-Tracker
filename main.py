import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import logging
import asyncio
import aiosqlite
from aiohttp import web

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

fh = logging.FileHandler('discord.log', encoding='utf-8', mode='w')
fh.setLevel(logging.DEBUG)

# Create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.ERROR)

# Create formatter and add it to the handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)

# Add the handlers to the logger
logger.addHandler(fh)
logger.addHandler(ch)
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

class MyBot(commands.Bot):
    async def webhook_setup(self):
        app = web.Application()
        app.add_routes([web.post('/helius-webhook', handle_webhook)])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 5000)
        await site.start()
    
    async def load_cogs(self):
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                await self.load_extension(f"cogs.{filename[:-3]}") 

    async def db_setup(self):
        async with aiosqlite.connect("main.db") as db:
            async with db.cursor() as cursor:
                await cursor.execute('CREATE TABLE IF NOT EXISTS wallets (name STRING, address STRING , guild INTEGER, channel INTEGER)')
            await db.commit()

    async def setup_hook(self):
        await self.load_cogs()
        await self.db_setup()
        asyncio.create_task(self.webhook_setup())

intents = discord.Intents.all()
intents.message_content = True

bot = MyBot(command_prefix='/', intents=intents)

@bot.event
async def on_ready():
    logger.debug('Bot ready!')
    channel = bot.get_channel(443827457062207493)
    print(f'Channel is {channel}')
    await channel.send('Hi')     

async def handle_webhook(request):
    from webhook import process_webhook
    data = await request.json()
    logger.debug(f"Received webhook data: {data}")
    await process_webhook(data, bot)
    return web.Response(text="Webhook received")

async def main():
    await bot.start(TOKEN)

if __name__ == '__main__':
    bot.run(TOKEN)
