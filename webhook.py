import discord
import os
import base58
import base64
import struct
from solders.pubkey import Pubkey
import datetime
import logging
import aiohttp
import aiosqlite
from main import bot

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

API_KEY = os.getenv('HELIUS_KEY')
url = f"https://mainnet.helius-rpc.com/?api-key={API_KEY}"

async def get_accountInfo(pubkey):
    pubkey = str(pubkey)
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [
            pubkey,
            {"commitment": "confirmed", "encoding": "base64"}
        ]
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as response:
            json_response = await response.json()
            if json_response.get('error') is not None:
                error = json_response.get('error').get('code')
                if error == -32602:
                    return 'Invalid address'
                else:
                    return 'Unknown error'
            elif json_response.get('error') is None:
                return json_response

def unpack_metadata_account(data):
    assert(data[0] == 4)
    i = 1
    source_account = base58.b58encode(bytes(struct.unpack('<' + "B"*32, data[i:i+32]))).decode('utf-8')
    i += 32
    mint_account = base58.b58encode(bytes(struct.unpack('<' + "B"*32, data[i:i+32]))).decode('utf-8')
    i += 32
    name_len = struct.unpack('<I', data[i:i+4])[0]
    i += 4
    name = struct.unpack('<' + "B"*name_len, data[i:i+name_len])
    i += name_len
    symbol_len = struct.unpack('<I', data[i:i+4])[0]
    i += 4 
    symbol = struct.unpack('<' + "B"*symbol_len, data[i:i+symbol_len])
    i += symbol_len
    uri_len = struct.unpack('<I', data[i:i+4])[0]
    i += 4 
    uri = struct.unpack('<' + "B"*uri_len, data[i:i+uri_len])
    i += uri_len
    fee = struct.unpack('<h', data[i:i+2])[0]
    i += 2
    has_creator = data[i] 
    i += 1
    creators = []
    verified = []
    share = []
    if has_creator:
        creator_len = struct.unpack('<I', data[i:i+4])[0]
        i += 4
        for _ in range(creator_len):
            creator = base58.b58encode(bytes(struct.unpack('<' + "B"*32, data[i:i+32])))
            creators.append(creator)
            i += 32
            verified.append(data[i])
            i += 1
            share.append(data[i])
            i += 1
    primary_sale_happened = bool(data[i])
    i += 1
    is_mutable = bool(data[i])
    metadata = {
        "update_authority": source_account,
        "mint": mint_account,
        "data": {
            "name": bytes(name).decode("utf-8").strip("\x00"),
            "symbol": bytes(symbol).decode("utf-8").strip("\x00"),
            "uri": bytes(uri).decode("utf-8").strip("\x00"),
            "seller_fee_basis_points": fee,
            "creators": creators,
            "verified": verified,
            "share": share,
        },
        "primary_sale_happened": primary_sale_happened,
        "is_mutable": is_mutable,
    }
    return metadata

async def get_metaData(ca):
    try:
        token_program = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        token_metadata_program = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")
        token_pubkey = Pubkey.from_string(ca)
        metadata_pda = Pubkey.find_program_address([b"metadata", bytes(token_metadata_program), bytes(token_pubkey)], token_metadata_program)[0]
        account_info = await get_accountInfo(metadata_pda)

        if not account_info or 'result' not in account_info or 'value' not in account_info['result']:
            raise ValueError(f"Invalid account info for {ca}")
        
        data = account_info['result']['value']['data'][0]
        decoded_data = base64.b64decode(data)
        metadata = unpack_metadata_account(decoded_data)

        if not metadata or 'data' not in metadata:
            raise ValueError(f"Invalid metadata for {ca}")
        
        async with aiohttp.ClientSession() as session:
            if metadata['data']['uri'] is None or len(metadata['data']['uri']) == 0:
                github_url = f"https://api.github.com/repos/solana-labs/token-list/contents/assets/mainnet/{ca}"
                async with session.get(github_url) as response:
                    github_response = await response.json()
                if not github_response:
                    raise ValueError(f"No GitHub response for {ca}")
                
                name = metadata['data'].get('name', '')
                symbol = metadata['data'].get('symbol', metadata['data']['symbol'])
                logo = github_response[0].get('download_url', None)
                createdOn = github_response[0].get('createdOn', None)
                twitter = github_response[0].get('twitter', None)
                telegram = github_response[0].get('telegram', None)
                website = github_response[0].get('website', None)
            else:
                uri = metadata['data']['uri']
                async with session.get(uri) as response:
                    ipfs_response = await response.json()
                if not ipfs_response:
                    raise ValueError(f"No IPFS response for {ca}")
            
                name = ipfs_response.get('name', '')
                symbol = ipfs_response.get('symbol', '')
                logo = ipfs_response.get('image', None)
                createdOn = ipfs_response.get('createdOn', None)
                twitter = ipfs_response.get('twitter', None)
                telegram = ipfs_response.get('telegram', None)
                website = ipfs_response.get('website', None)

        return name, symbol, logo, createdOn, twitter, telegram, website
    except Exception as e:
        print(f"Error in get_metaData: {e}")
        return None, None, None, None, None, None, None

def is_valid_transaction(webhook_data, address):
    # Define a threshold for significant native balance change (in lamports)
    threshold = 5000  # In lamports (1 SOL = 1,000,000 lamports)
    nativeBalanceChange = [i['nativeBalanceChange'] for i in webhook_data[0]['accountData'] if i['account'] == address][0]
    if abs(nativeBalanceChange) >= threshold:
        return True
    
    if len(webhook_data[0]['tokenTransfers']) >= 1:
        return True
    # If no criteria are met, return False
    print('not valid transaction')
    return False

async def swapInfo(data, txh, wallet):
    try:    
        postTokenBalances = data[0]['meta']['postTokenBalances']
        preTokenBalances = data[0]['meta']['preTokenBalances']
        token_addresses = [i['mint'] for i in postTokenBalances if i['owner'] == wallet] if len([i['mint'] for i in postTokenBalances if i['owner'] == wallet]) != 0 else []
        SPL_post_amount = [i['uiTokenAmount']['uiAmountString'] for i in postTokenBalances if i['owner'] == wallet] if [i['uiTokenAmount']['uiAmountString'] for i in postTokenBalances if i['owner'] == wallet] else [0]
        SPL_pre_amount = [i['uiTokenAmount']['uiAmountString'] for i in preTokenBalances if i['owner'] == wallet] if [i['uiTokenAmount']['uiAmountString'] for i in preTokenBalances if i['owner'] == wallet] else [0]
        token_change = [float(xi) - float(yi) for xi, yi in zip(SPL_post_amount, SPL_pre_amount)]

        info = None
        if len(token_addresses) == 2:
            if token_change[0] > 0:
                metadata_in = await get_metaData(token_addresses[0])
                metadata_out = await get_metaData(token_addresses[1])
                SPL_in = abs(token_change[0])
                SPL_out = abs(token_change[1])
                SPL_in_CA = token_addresses[0]
                SPL_out_CA = token_addresses[1]
                SPL_out_symbol = metadata_out[1]
                logo_out = metadata_out[2] if metadata_out[2] else ""
                SPL_in_symbol = metadata_in[1]
                logo_in = metadata_in[2] if metadata_in[2] else ""
                createdOn_in = metadata_in[3] if metadata_in[3] else None
                twitter_in = metadata_in[4] if metadata_in[4] else None
                telegram_in = metadata_in[5] if metadata_in[5] else None
                website_in = metadata_in[6] if metadata_in[6] else None
                info = [SPL_out, SPL_out_CA, SPL_out_symbol, logo_out, SPL_in, SPL_in_CA, SPL_in_symbol, logo_in, wallet, txh, createdOn_in, twitter_in, telegram_in, website_in]
            elif token_change[0] < 0:
                metadata_in =  await get_metaData(token_addresses[1])
                metadata_out = await get_metaData(token_addresses[0])
                SPL_in = abs(token_change[1])
                SPL_out = abs(token_change[0])
                SPL_in_CA = token_addresses[1]
                SPL_out_CA = token_addresses[0]
                SPL_out_symbol = metadata_out[1]
                logo_out = metadata_out[2] if metadata_out[2] else ""
                SPL_in_symbol = metadata_in[1]
                logo_in = metadata_in[2] if metadata_in[2] else ""
                createdOn_in = metadata_in[3] if metadata_in[3] else None
                twitter_in = metadata_in[4] if metadata_in[4] else None
                telegram_in = metadata_in[5] if metadata_in[5] else None
                website_in = metadata_in[6] if metadata_in[6] else None
                info = [SPL_out, SPL_out_CA, SPL_out_symbol, logo_out, SPL_in, SPL_in_CA, SPL_in_symbol, logo_in, wallet, txh, createdOn_in, twitter_in, telegram_in, website_in]
        elif len(token_addresses) == 1:
            SOL_change = (data[0]['meta']['preBalances'][0] - data['meta']['postBalances'][0]) / 1e9
            if SOL_change < 0:
                metadata_in = await get_metaData(token_addresses[0])
                SPL_in = abs(token_change[0])
                SPL_out = abs(SOL_change)
                SPL_in_CA = token_addresses[0]
                SPL_out_CA = 'So11111111111111111111111111111111111111112'
                SPL_out_symbol = 'SOL'
                logo_out = 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png'
                SPL_in_symbol = metadata_in[1]
                logo_in = metadata_in[2] if metadata_in[2] else ""
                createdOn_in = metadata_in[3] if metadata_in[3] else None
                twitter_in = metadata_in[4] if metadata_in[4] else None
                telegram_in = metadata_in[5] if metadata_in[5] else None
                website_in = metadata_in[6] if metadata_in[6] else None
                info = [SPL_out, SPL_out_CA, SPL_out_symbol, logo_out, SPL_in, SPL_in_CA, SPL_in_symbol, logo_in, wallet, txh, createdOn_in, twitter_in, telegram_in, website_in]
            elif SOL_change > 0:
                metadata_out = await get_metaData(token_addresses[0])
                SPL_out = abs(token_change[0])
                SPL_out_CA = token_addresses[0]
                SPL_out_symbol = metadata_out[1]
                logo_out = metadata_out[2] if metadata_out[2] else ""
                SPL_in = abs(SOL_change)
                SPL_in_symbol = 'So11111111111111111111111111111111111111112'
                SPL_in_symbol = 'SOL'
                logo_in = 'https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png'
                createdOn_in = None
                twitter_in = None
                telegram_in = None
                website_in = None
                info = [SPL_out, SPL_out_CA, SPL_out_symbol, logo_out, SPL_in, SPL_in_CA, SPL_in_symbol, logo_in, wallet, txh, createdOn_in, twitter_in, telegram_in, website_in]
        print(info)
        return info
    except Exception as e:
        logger.error(f"Error in swapInfo: {e}")
        return None        
            
async def process_webhook(data, bot):    
    if not data:
        logger.error("No data received")    

    account_keys = data[0]['transaction']['message']['accountKeys']
    placeholders = ', '.join(['?'] * len(account_keys))
    async with aiosqlite.connect("main.db") as db:
        async with db.cursor() as cursor:
            query = f'SELECT * FROM wallets WHERE address IN ({placeholders})'
            await cursor.execute(query, account_keys)
            rows = await cursor.fetchall()
            if rows:
                address_data = {row[1]: row for row in rows} 
                ordered_address_data = [address_data.get(address) for address in account_keys if address in address_data]
                if ordered_address_data:
                    tracked_wallet = ordered_address_data[0][1]
                    await cursor.execute('SELECT name, channel FROM wallets WHERE address = ?', (tracked_wallet,))
                    selected_rows = await cursor.fetchall()
                    nametags = [row[0] for row in selected_rows]
                    channel_ids = [row[1] for row in selected_rows]
                    logger.debug(f"Channel IDs for tracked wallet {tracked_wallet}: {channel_ids}")
            else:
                print('No tracked wallets found')

    signature = data[0]['transaction']['signatures'][0]
    logger.info(f"Account info for tracked wallet: {tracked_wallet}")
    logger.info(f"Transaction Hash is {signature} and the wallet being tracked is {tracked_wallet}.")
    info = await swapInfo(data, signature, tracked_wallet)
    if info:
        await send_embedded_transaction(info, nametags, channel_ids, bot=bot)
    else:
        logger.error("Error processing swapInfo: Info is None")

async def send_embedded_transaction(info, nametags, channel_ids, bot):
    print(channel_ids)
    for i in range(len(channel_ids)):
        embed = discord.Embed(
            title="Transaction Detected", 
            description=f"{nametags[i]} has swapped {info[0]} {info[2]} for {info[4]} {info[6]}", 
            colour=0xf6ee04, 
            timestamp=datetime.datetime.now()
        )
        embed.set_author(name="Swap")
        embed.add_field(name="Wallet", value=f"[{info[8][:4]}...{info[8][-4:]}](https://solscan.io/account/{info[8]})", inline=True)
        embed.add_field(name="Transaction", value=f"[{info[9][:4]}...{info[9][-4:]}](https://solscan.io/tx/{info[9]})", inline=True)
        social_links = []
        if info[11]:
            social_links.append(f"[Twitter]({info[11]})")
        if info[12]:
            social_links.append(f"[Telegram]({info[12]})")
        if info[13]:
            social_links.append(f"[Website]({info[13]})")

        social_links_str = " | ".join(social_links) if social_links else None
        if social_links_str:
            embed.add_field(name="Socials", value=social_links_str, inline=False)
        
        links = [
            f"[Photon](https://photon-sol.tinyastro.io/en/r/@proficyio/{info[5]})",
            f"[BullX](https://bullx.io/terminal?chainId=1399811149&address={info[5]})",
            f"[DEXScreener](https://dexscreener.com/solana/{info[5]})"
        ]
        if info[10] == 'https://pump.fun':
            links.append(f"[Pumpfun](https://pump.fun/{info[5]})")
        links_str = " | ".join(links)

        embed.add_field(name="Links", value=links_str, inline=False)
        if info[5]!= "So11111111111111111111111111111111111111112":
            embed.add_field(name="Contract Address", value=f"```{info[5]}```", inline=False)
        embed.set_thumbnail(url=info[7])
        embed.set_footer(text="Monitor", icon_url="https://slate.dan.onl/slate.png")

        print(channel_ids[i])
        await bot.wait_until_ready()
        channel = bot.get_channel(channel_ids[i])
        print(channel)
        await channel.send(embed=embed)
    logger.info(f"Info: {info}")
    logger.debug("Embed sent successfully.")
    logging.info("Transaction sent: %s", info)