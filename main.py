import os
import sys
import threading
import logging
import requests
from urllib.parse import quote
from dotenv import load_dotenv

import discord
from discord import app_commands
from discord.ext import commands
import jinja2
from flask import Flask, request, render_template, render_template_string, redirect, jsonify

# ==============================================================================
# 1. SETUP & CONFIGURATION
# ==============================================================================
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("HiGHFlowBOT")

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
CLIENT_ID = os.getenv("CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("REDIRECT_URI", "").strip()
# Fallback IDs for backward compatibility (optional in multi-server mode)
GUILD_ID = os.getenv("GUILD_ID", "").strip()
VERIFIED_ROLE_ID = os.getenv("VERIFIED_ROLE_ID", "").strip()
PORT = int(os.getenv("PORT", 5000))

# Default gothic banner image for Discord Embed
DEFAULT_EMBED_BANNER = "https://raw.githubusercontent.com/RAF1W22154/HiGHFlowBOT/main/static/banner.png"

# Multi-Server Stateless OAuth2 URL Generator
def get_oauth_url(guild_id: str = None, role_id: str = None) -> str:
    encoded_redirect = quote(REDIRECT_URI, safe="")
    base_url = (
        f"https://discord.com/api/oauth2/authorize?"
        f"client_id={CLIENT_ID}&redirect_uri={encoded_redirect}&response_type=code&scope=identify%20email%20guilds.join"
    )
    # State parameter carries guild_id and role_id across servers statelessly
    target_guild = guild_id or GUILD_ID
    target_role = role_id or VERIFIED_ROLE_ID
    if target_guild and target_role:
        base_url += f"&state={target_guild}_{target_role}"
    return base_url

# ==============================================================================
# 2. FLASK WEB SERVER (OAuth2 & Uptime Keep-Alive)
# ==============================================================================
flask_app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    template_folder=os.path.join(BASE_DIR, "templates")
)

# Search for templates in both templates/ and root directory
flask_app.jinja_loader = jinja2.ChoiceLoader([
    jinja2.FileSystemLoader(os.path.join(BASE_DIR, "templates")),
    jinja2.FileSystemLoader(BASE_DIR),
])

log_werkzeug = logging.getLogger('werkzeug')
log_werkzeug.setLevel(logging.WARNING)

@flask_app.route("/", methods=["GET"])
def health_check():
    """UptimeRobot ping endpoint to keep Render web service awake 24/7."""
    return jsonify({
        "status": "online",
        "service": "HiGHFlowBOT Multi-Server Verification Service",
        "active": True
    }), 200

@flask_app.route("/verify", methods=["GET"])
def initiate_verify():
    """Redirects the user to Discord OAuth2 Authorization."""
    if not CLIENT_ID or not REDIRECT_URI:
        return "<h3>Configuration Error: CLIENT_ID or REDIRECT_URI is missing.</h3>", 500
    guild_id = request.args.get("guild_id")
    role_id = request.args.get("role_id")
    return redirect(get_oauth_url(guild_id=guild_id, role_id=role_id))

@flask_app.route("/callback", methods=["GET"])
def oauth_callback():
    code = request.args.get("code")
    error = request.args.get("error")
    state = request.args.get("state", "").strip()

    if error:
        logger.warning(f"OAuth error received: {error}")
        return f"<h3>Authentication Cancelled: {error}</h3>", 400

    if not code:
        return "<h3>Invalid Request: Authorization code missing.</h3>", 400

    # Resolve target guild and role from state parameter (Multi-Server)
    target_guild_id = GUILD_ID
    target_role_id = VERIFIED_ROLE_ID
    if state and "_" in state:
        parts = state.split("_", 1)
        if parts[0].isdigit() and parts[1].isdigit():
            target_guild_id = parts[0]
            target_role_id = parts[1]

    # 1. Exchange OAuth code for Access Token
    token_url = "https://discord.com/api/v10/oauth2/token"
    token_data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        token_response = requests.post(token_url, data=token_data, headers=headers, timeout=10)
        if token_response.status_code != 200:
            logger.error(f"Failed to fetch token: {token_response.text}")
            return f"<h3>Token Exchange Failed ({token_response.status_code}). Please try again.</h3>", 400

        token_json = token_response.json()
        access_token = token_json.get("access_token")

        # 2. Fetch User Profile Info via OAuth Access Token
        user_url = "https://discord.com/api/v10/users/@me"
        user_headers = {"Authorization": f"Bearer {access_token}"}
        user_response = requests.get(user_url, headers=user_headers, timeout=10)

        if user_response.status_code != 200:
            logger.error(f"Failed to fetch user data: {user_response.text}")
            return "<h3>Failed to retrieve user profile from Discord.</h3>", 400

        user_data = user_response.json()
        user_id = user_data.get("id")
        username = user_data.get("username", "Unknown")
        display_name = user_data.get("global_name") or username
        avatar_hash = user_data.get("avatar")
        is_verified = user_data.get("verified") is True
        user_email = user_data.get("email")

        if avatar_hash:
            ext = "gif" if avatar_hash.startswith("a_") else "png"
            avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=256"
        else:
            default_index = (int(user_id) >> 22) % 6
            avatar_url = f"https://cdn.discordapp.com/embed/avatars/{default_index}.png"

        discord_return_url = f"https://discord.com/channels/{target_guild_id}" if target_guild_id else "https://discord.com/channels/@me"
        retry_url = get_oauth_url(guild_id=target_guild_id, role_id=target_role_id)

        # 2.1 Security Enforcement: บัญชีต้องยืนยัน Email หรือเบอร์โทรศัพท์บน Discord แล้วเท่านั้น
        if not is_verified or not user_email:
            logger.warning(f"User {username} ({user_id}) denied role: account unverified on Discord (verified={is_verified}, email={user_email})")
            try:
                return render_template(
                    "unverified.html",
                    avatar_url=avatar_url,
                    username=username,
                    display_name=display_name,
                    retry_url=retry_url,
                    discord_return_url=discord_return_url
                ), 403
            except Exception as t_err:
                logger.warning(f"render_template unverified failed ({t_err}), trying fallback...")
                for possible_path in [
                    os.path.join(BASE_DIR, "unverified.html"),
                    os.path.join(BASE_DIR, "templates", "unverified.html"),
                ]:
                    if os.path.exists(possible_path):
                        with open(possible_path, "r", encoding="utf-8") as f:
                            return render_template_string(
                                f.read(),
                                avatar_url=avatar_url,
                                username=username,
                                display_name=display_name,
                                retry_url=retry_url,
                                discord_return_url=discord_return_url
                            ), 403
                raise t_err

        # 3. Add Member / Assign Role via Discord REST API (Bot Token)
        bot_auth_headers = {
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "Content-Type": "application/json"
        }

        if target_guild_id:
            # Attempt to add user to guild if not present (guilds.join scope)
            add_guild_url = f"https://discord.com/api/v10/guilds/{target_guild_id}/members/{user_id}"
            add_payload = {
                "access_token": access_token,
                "roles": [str(target_role_id)] if target_role_id else []
            }
            add_res = requests.put(add_guild_url, json=add_payload, headers=bot_auth_headers, timeout=10)

            # If user is already in guild (HTTP 204), explicitly add role
            if add_res.status_code in [201, 204]:
                if target_role_id:
                    role_assign_url = f"https://discord.com/api/v10/guilds/{target_guild_id}/members/{user_id}/roles/{target_role_id}"
                    role_res = requests.put(role_assign_url, headers=bot_auth_headers, timeout=10)
                    if role_res.status_code in [204, 200]:
                        logger.info(f"Assigned role {target_role_id} in guild {target_guild_id} to {username} ({user_id})")
                    else:
                        logger.warning(f"Role assign API responded with {role_res.status_code}: {role_res.text}")
            else:
                logger.warning(f"Member add API responded with {add_res.status_code}: {add_res.text}")

        # Resolve role name for UI presentation
        resolved_role_name = "Member"
        if bot.is_ready() and target_guild_id and target_role_id:
            guild = bot.get_guild(int(target_guild_id))
            if guild:
                role_obj = guild.get_role(int(target_role_id))
                if role_obj:
                    resolved_role_name = role_obj.name

        discord_return_url = f"https://discord.com/channels/{target_guild_id}" if target_guild_id else "https://discord.com/channels/@me"

        # Render Gothic Glassmorphism Success Page
        try:
            return render_template(
                "index.html",
                avatar_url=avatar_url,
                username=username,
                display_name=display_name,
                role_name=resolved_role_name,
                discord_return_url=discord_return_url
            )
        except Exception as t_err:
            logger.warning(f"render_template failed ({t_err}), trying direct file read fallback...")
            for possible_path in [
                os.path.join(BASE_DIR, "index.html"),
                os.path.join(BASE_DIR, "templates", "index.html"),
            ]:
                if os.path.exists(possible_path):
                    with open(possible_path, "r", encoding="utf-8") as f:
                        return render_template_string(
                            f.read(),
                            avatar_url=avatar_url,
                            username=username,
                            display_name=display_name,
                            role_name=resolved_role_name,
                            discord_return_url=discord_return_url
                        )
            raise t_err

    except Exception as e:
        logger.exception(f"Unhandled exception during OAuth verification: {e}")
        return f"<h3>Internal Server Error during verification: {str(e)}</h3>", 500

def run_flask_service():
    """Runs the Flask web server in a separate background daemon thread."""
    logger.info(f"Starting Flask Web Server on 0.0.0.0:{PORT}...")
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


# ==============================================================================
# 3. DISCORD BOT & SLASH COMMANDS (Multi-Server Ready)
# ==============================================================================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class VerificationBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} Slash command(s) successfully across all guilds.")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

bot = VerificationBot()

@bot.event
async def on_ready():
    logger.info(f"Discord Bot logged in as {bot.user.name} ({bot.user.id})")
    logger.info(f"Currently active in {len(bot.guilds)} guild(s)")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="HiGHFlow Multi-Server Verification")
    )

# ------------------------------------------------------------------------------
# UI Component: Verification Link Button
# ------------------------------------------------------------------------------
class VerificationLinkView(discord.ui.View):
    def __init__(self, verify_url: str, button_label: str = "รับยศ + · Member", button_emoji: str = "🛡️"):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                label=button_label,
                url=verify_url,
                emoji=button_emoji
            )
        )

# ------------------------------------------------------------------------------
# Slash Command: /setup_verify (เลือกยศในคำสั่งได้ทันที รองรับหลาย Server)
# ------------------------------------------------------------------------------
@bot.tree.command(name="setup_verify", description="สร้างข้อความ Embed สำหรับยืนยันตัวตนรับยศ (Admin Only)")
@app_commands.describe(
    role="เลือกยศที่ต้องการแจกเมื่อผู้ใช้ยืนยันตัวตนสำเร็จ",
    channel="ห้องที่ต้องการให้ส่งข้อความ Embed (ค่าเริ่มต้น: ห้องปัจจุบัน)",
    title="หัวข้อของ Embed (ค่าเริ่มต้น: 'รับยศ')",
    description="ข้อความคำอธิบายภายใน Embed (ค่าเริ่มต้น: 'รับยศเพื่อเห็นช่อง')",
    image_url="ลิงก์รูปภาพขนาดใหญ่ตรงกลาง (ค่าเริ่มต้น: แบนเนอร์ HiGHFlowBOT)",
    button_text="ข้อความบนปุ่มกดรับยศ (ค่าเริ่มต้น: 'กดที่นี่เพื่อรับยศ')",
    button_emoji="อิโมจิบนปุ่ม (ค่าเริ่มต้น: ✅)",
    color_hex="รหัสสีด้านข้างของ Embed (ค่าเริ่มต้น: #FFFFFF)"
)
@app_commands.default_permissions(administrator=True)
async def setup_verify(
    interaction: discord.Interaction,
    role: discord.Role,
    channel: discord.TextChannel = None,
    title: str = "รับยศ",
    description: str = "รับยศเพื่อเห็นช่อง",
    image_url: str = DEFAULT_EMBED_BANNER,
    button_text: str = "กดที่นี่เพื่อรับยศ",
    button_emoji: str = "✅",
    color_hex: str = "#FFFFFF"
):
    # ป้องกัน Discord Interaction Timeout (3 วินาที)
    await interaction.response.defer(ephemeral=True)

    if not interaction.guild:
        await interaction.followup.send("❌ คำสั่งนี้สามารถใช้งานได้เฉพาะภายในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
        return

    # ตรวจสอบสิทธิ์ของบอทในการมอบยศ
    bot_member = interaction.guild.me
    if not bot_member.guild_permissions.manage_roles:
        await interaction.followup.send("❌ บอทไม่มีสิทธิ์ `Manage Roles` (จัดการบทบาท) ในเซิร์ฟเวอร์นี้", ephemeral=True)
        return

    if bot_member.top_role <= role:
        await interaction.followup.send(
            f"⚠️ **ลำดับยศไม่ถูกต้อง:** ยศสูงสุดของบอท ({bot_member.top_role.mention}) "
            f"ต้องอยู่ **สูงกว่า** ยศที่ต้องการแจก ({role.mention})\n"
            f"กรุณาไปที่ Server Settings > Roles แล้วลากยศบอทขึ้นไปไว้ด้านบน",
            ephemeral=True
        )
        return

    target_channel = channel or interaction.channel

    # Parse color
    try:
        color_val = int(color_hex.replace("#", "").replace("0x", ""), 16)
    except ValueError:
        color_val = 0xFFFFFF

    embed = discord.Embed(
        title=title,
        description=description,
        color=color_val
    )

    if image_url:
        embed.set_image(url=image_url)

    # สร้าง OAuth URL ประจำเซิร์ฟเวอร์และยศที่เลือก
    verify_url = get_oauth_url(guild_id=str(interaction.guild_id), role_id=str(role.id))
    btn_label = button_text or f"รับยศ + · {role.name}"

    view = VerificationLinkView(verify_url=verify_url, button_label=btn_label, button_emoji=button_emoji)

    await target_channel.send(embed=embed, view=view)
    await interaction.followup.send(
        f"✅ ส่งข้อความยืนยันตัวตนสำหรับยศ {role.mention} ไปยังห้อง {target_channel.mention} เรียบร้อยแล้ว!",
        ephemeral=True
    )

# ------------------------------------------------------------------------------
# Slash Command: /edit_verify
# ------------------------------------------------------------------------------
@bot.tree.command(name="edit_verify", description="แก้ไขข้อความ Embed ยืนยันตัวตนที่มีอยู่แล้ว (Admin Only)")
@app_commands.describe(
    message_id="ID ของข้อความที่ต้องการแก้ไข",
    channel="ห้องที่ข้อความนั้นอยู่",
    role="ยศใหม่ที่ต้องการแจก (หากต้องการเปลี่ยน)",
    title="หัวข้อใหม่ (เว้นว่างไว้หากไม่ต้องการเปลี่ยน)",
    description="คำอธิบายใหม่ (เว้นว่างไว้หากไม่ต้องการเปลี่ยน)",
    image_url="ลิงก์รูปภาพใหม่ (เว้นว่างไว้หากไม่ต้องการเปลี่ยน)",
    button_text="ข้อความปุ่มใหม่ (เว้นว่างไว้หากไม่ต้องการเปลี่ยน)",
    button_emoji="อิโมจิปุ่มใหม่ (เว้นว่างไว้หากไม่ต้องการเปลี่ยน)"
)
@app_commands.default_permissions(administrator=True)
async def edit_verify(
    interaction: discord.Interaction,
    message_id: str,
    channel: discord.TextChannel = None,
    role: discord.Role = None,
    title: str = None,
    description: str = None,
    image_url: str = None,
    button_text: str = None,
    button_emoji: str = None
):
    await interaction.response.defer(ephemeral=True)
    target_channel = channel or interaction.channel
    try:
        msg = await target_channel.fetch_message(int(message_id))
    except Exception as e:
        await interaction.followup.send(f"❌ ไม่พบข้อความ ID `{message_id}` ในห้อง {target_channel.mention}: {e}", ephemeral=True)
        return

    if not msg.embeds:
        await interaction.followup.send("❌ ข้อความดังกล่าวไม่มี Embed", ephemeral=True)
        return

    current_embed = msg.embeds[0]
    new_embed = discord.Embed(
        title=title if title is not None else current_embed.title,
        description=description if description is not None else current_embed.description,
        color=current_embed.color or 0xFFFFFF
    )

    img = image_url if image_url is not None else (current_embed.image.url if current_embed.image else None)
    if img:
        new_embed.set_image(url=img)

    # ดึง URL เก่าจากปุ่มเดิม หรือสร้างใหม่หากมีการระบุยศใหม่
    old_url = None
    if msg.components and len(msg.components[0].children) > 0:
        old_url = getattr(msg.components[0].children[0], "url", None)

    if role:
        new_url = get_oauth_url(guild_id=str(interaction.guild_id), role_id=str(role.id))
        btn_lbl = button_text or f"รับยศ + · {role.name}"
    else:
        new_url = old_url or get_oauth_url(guild_id=str(interaction.guild_id))
        btn_lbl = button_text or "กดที่นี่เพื่อรับยศ"

    btn_emj = button_emoji or "✅"
    new_view = VerificationLinkView(verify_url=new_url, button_label=btn_lbl, button_emoji=btn_emj)

    await msg.edit(embed=new_embed, view=new_view)
    await interaction.followup.send(f"✅ แก้ไขข้อความ ID `{message_id}` เรียบร้อยแล้ว", ephemeral=True)

# ------------------------------------------------------------------------------
# Slash Command: /check_config (ตรวจเช็คระบบเจาะจงเฉพาะ Server ปัจจุบัน)
# ------------------------------------------------------------------------------
@bot.tree.command(name="check_config", description="ตรวจสอบสถานะการเชื่อมต่อและสิทธิ์ของบอทในเซิร์ฟเวอร์นี้ (Admin Only)")
@app_commands.default_permissions(administrator=True)
async def check_config(interaction: discord.Interaction):
    # ยืดเวลา interaction ทันที ไม่ให้ขึ้น "แอปพลิเคชันไม่ตอบสนอง"
    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    bot_member = guild.me if guild else None

    has_manage_roles = bot_member.guild_permissions.manage_roles if bot_member else False
    is_admin = bot_member.guild_permissions.administrator if bot_member else False

    status_lines = [
        f"**Server Name:** `{guild.name if guild else 'DM / Not in Guild'}`",
        f"**Server ID (Guild ID):** `{guild.id if guild else 'N/A'}` ✅",
        f"**Bot Top Role:** `{bot_member.top_role.name if bot_member else 'N/A'}`",
        f"**Manage Roles Permission:** `{'✅ มีสิทธิ์' if has_manage_roles or is_admin else '❌ ไม่มีสิทธิ์'}`",
        f"**Client ID:** `{CLIENT_ID[:6]}...` {'✅' if CLIENT_ID else '❌'}",
        f"**Redirect URI:** `{REDIRECT_URI or 'Not Set'}` {'✅' if REDIRECT_URI else '❌'}",
        f"**Multi-Server Mode:** `✅ ทำงานอิสระทุก Server`",
        f"**Flask Port:** `{PORT}` ✅"
    ]

    embed = discord.Embed(
        title=f"⚙️ Status Diagnostic — {guild.name if guild else 'Global'}",
        description="\n".join(status_lines),
        color=0x2ecc71 if (CLIENT_ID and REDIRECT_URI and (has_manage_roles or is_admin)) else 0xe74c3c,
        timestamp=discord.utils.utcnow()
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


# ==============================================================================
# 4. ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        logger.critical("DISCORD_BOT_TOKEN is not configured! Please set it in .env or Environment Variables.")
        sys.exit(1)

    # 1. Launch Flask Web Server in Daemon Thread
    flask_thread = threading.Thread(target=run_flask_service, daemon=True)
    flask_thread.start()

    # 2. Run Discord Bot in Main Thread
    logger.info("Connecting Discord Bot...")
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except Exception as e:
        logger.critical(f"Failed to start Discord Bot: {e}")
        sys.exit(1)
