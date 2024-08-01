# cogs/tracker.py
import discord
from discord.ext import commands
import aiohttp
import json
import logging
from solders.pubkey import Pubkey # type: ignore
import os
from dotenv import load_dotenv
import aiosqlite
from typing import Callable, Optional

logger = logging.getLogger(__name__)

api_key = os.getenv('HELIUS_KEY')
webhook_url = "https://api.helius.xyz/v0/webhooks/7723a8c5-233e-4180-83f1-d54c40778539"

class Pagination(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, get_page: Callable):
        self.interaction = interaction
        self.get_page = get_page
        self.total_pages: Optional[int] = None
        self.index = 1
        super().__init__(timeout=100)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user == self.interaction.user:
            return True
        else:
            emb = discord.Embed(
                description="Only the author of the command can perform this action.",
                color=16711680
            )
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return False

    async def navigate(self):
        emb, self.total_pages = await self.get_page(self.index)
        if self.total_pages > 1:
            self.update_buttons()
        await self.interaction.response.send_message(embed=emb, view=self)

    async def edit_page(self, interaction: discord.Interaction):
        emb, self.total_pages = await self.get_page(self.index)
        self.update_buttons()
        await interaction.response.edit_message(embed=emb, view=self)

    def update_buttons(self):
        self.first_page_button.disabled = self.index == 1
        self.last_page_button.disabled = self.index == self.total_pages

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.blurple)
    async def first_page_button(self, interaction: discord.Interaction, button: discord.Button):
        self.index = 1
        await self.edit_page(interaction)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.blurple)
    async def previous(self, interaction: discord.Interaction, button: discord.Button):
        self.index -= 1
        await self.edit_page(interaction)

    @discord.ui.button(label="Go to page", style=discord.ButtonStyle.gray)
    async def go_to_page_button(self, interaction: discord.Interaction, button: discord.Button):
        modal = GoToPageModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.blurple)
    async def next(self, interaction: discord.Interaction, button: discord.Button):
        self.index += 1
        await self.edit_page(interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.blurple)
    async def last_page_button(self, interaction: discord.Interaction, button: discord.Button):
        self.index = self.total_pages
        await self.edit_page(interaction)

    async def on_timeout(self):
        # Remove buttons on timeout
        message = await self.interaction.original_response()
        await message.edit(view=None)

    @staticmethod
    def compute_total_pages(total_results: int, results_per_page: int) -> int:
        return ((total_results - 1) // results_per_page) + 1
    
class GoToPageModal(discord.ui.Modal, title="Go to Page"):
    page_number = discord.ui.TextInput(label="Page number", style=discord.TextStyle.short)

    def __init__(self, paginator: Pagination):
        super().__init__()
        self.paginator = paginator

    async def on_submit(self, interaction: discord.Interaction):
        try:
            page = int(self.page_number.value)
            if 1 <= page <= self.paginator.total_pages:
                self.paginator.index = page
                await self.paginator.edit_page(interaction)
            else:
                await interaction.response.send_message(f"Invalid page number. Please enter a number between 1 and {self.paginator.total_pages}.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Invalid input. Please enter a valid page number.", ephemeral=True)

class Tracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logger.debug(f"{self.__class__.__name__} is online! running new version V1.4")

    @staticmethod
    def is_valid_solana_address(address: str) -> bool:
        try:
            Pubkey.from_string(address)  # Use Pubkey.from_string() for validation
            return True
        except ValueError:
            return False
    
    async def modify_address(self, address: str, action: str):
        if not self.is_valid_solana_address(address):
            print('Invalid Solana address')
        
        headers = {
            'Content-Type': 'application/json',
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{webhook_url}?api-key={api_key}", headers=headers) as response:
                webhook_data = await response.json()

            logger.debug(f"Retrieved webhook data: {webhook_data}")
            account_addresses = webhook_data.get('accountAddresses', [])
            logger.debug(f"Current account addresses: {account_addresses}")

            if action == 'add':
                if address in account_addresses:
                    print('Address is already in Webhook list')
                else:
                    account_addresses.append(address)
            elif action == 'remove':
                if address not in account_addresses:
                    print('Address is not being tracked')
                else:
                    account_addresses.remove(address)
                    logger.debug(f"Address removed from Webhook: {address}")
            else:
                print('Invalid action specified')

            logger.debug(f"Updated account addresses: {account_addresses}")
            
            update_payload = {
                "webhookURL": webhook_data.get('webhookURL', ''),
                "transactionTypes": webhook_data.get('transactionTypes', []),
                "accountAddresses": account_addresses,
                "webhookType": webhook_data.get('webhookType', ''),
            }

            logger.debug(f"Update payload: {update_payload}")
            
            async with session.put(f"{webhook_url}?api-key={api_key}", headers=headers, data=json.dumps(update_payload)) as update_response:
                if update_response.status == 200:
                    logger.debug(f"Update successful")
                else:
                    logger.debug("Failed to update the address list")
                    return 'Failed to update the address list'

    @commands.command()
    async def sync(self, ctx) -> None:
        if ctx.author.id == 335798958708228099:
            fmt = await ctx.bot.tree.sync()
            await ctx.send(f"Synced {len(fmt)} commands to all servers")
        else:
            return

    tracker_group = discord.app_commands.Group(name="tracker", description="Address-related commands")
    
    @tracker_group.command(name="add", description="Track an address")
    async def add(self, interaction: discord.Interaction, address: str, channel: discord.TextChannel, nametag: str = None):
        if not self.is_valid_solana_address(address):
            await interaction.response.defer()
            await interaction.followup.send('Invalid Solana address')
            return
        if nametag is None:
            nametag = address
        async with aiosqlite.connect("main.db") as db:
            async with db.cursor() as cursor:
                await cursor.execute('SELECT * FROM wallets WHERE name = ? AND guild = ?', (nametag, interaction.guild_id,))
                nametag_data = await cursor.fetchall()
                if nametag_data:
                    await interaction.response.defer() 
                    await interaction.followup.send(f'Nametag "{nametag}" is already being used')
                    return
                
                await cursor.execute('SELECT * FROM wallets WHERE address = ? AND guild = ?', (address, interaction.guild_id,))
                address_data = await cursor.fetchall()
                if address_data:
                    print(address_data)
                    await interaction.response.defer() 
                    await interaction.followup.send('Address is already being tracked')
                    return

                await cursor.execute('INSERT INTO wallets (name, address, guild, channel) VALUES (?, ?, ?, ?)', (nametag, address, interaction.guild_id, channel.id,))
                await db.commit()
                await interaction.response.defer() 
                await self.modify_address(address, 'add')
                await interaction.followup.send(f'Now tracking address {address} as {nametag}')                                     

    @tracker_group.command(name="remove", description="Untrack an address")
    async def remove(self, interaction: discord.Interaction, address: str):
        async with aiosqlite.connect("main.db") as db:
            async with db.cursor() as cursor:
                await cursor.execute('SELECT * FROM wallets WHERE address = ? AND guild = ?', (address, interaction.guild_id,))
                data = await cursor.fetchall()
                if not data:
                    await interaction.response.defer()
                    await interaction.followup.send('Address is not being tracked')
                    return
                
                await cursor.execute('DELETE FROM wallets WHERE address = ? AND guild = ?', (address, interaction.guild_id,))
                await db.commit()
                await interaction.response.defer()
                await self.modify_address(address, 'remove')
                await interaction.followup.send(f'No longer tracking {address}')

    @tracker_group.command(name="list", description="List of tracked addresses")
    async def list_wallets(self, interaction: discord.Interaction):
        async def get_page(index: int):
            async with aiosqlite.connect("main.db") as db:
                async with db.cursor() as cursor:
                    await cursor.execute('SELECT name, address FROM wallets WHERE guild = ?', (interaction.guild_id,))
                    selected_rows = await cursor.fetchall()
                    nametags = [row[0] for row in selected_rows]
                    addresses = [row[1] for row in selected_rows]

            per_page = 5
            total_pages = Pagination.compute_total_pages(len(addresses), per_page)
            start_index = (index - 1) * per_page
            end_index = start_index + per_page
            data = [f"**{i+1}.** [**{nametags[i]}**](https://solscan.io/account/{addresses[i]}): `{addresses[i]}`" for i in range(start_index, min(end_index, len(addresses)))]

            embed = discord.Embed(
                title=f"Wallet list",
                description="You are currently tracking the following wallets:",
                colour=0xf6ee04,
            )
            embed.add_field(name="", value="\n".join(data), inline=False)
            embed.set_footer(text=f"Page {index}/{total_pages}")
            return embed, total_pages

        paginator = Pagination(interaction, get_page)
        await paginator.navigate()

async def setup(bot):
    await bot.add_cog(Tracker(bot))



