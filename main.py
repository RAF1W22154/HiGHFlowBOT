import os
import json
import threading
import discord
from discord.ext import commands
from flask import Flask, redirect, request, render_template
import requests

# ==========================================
# CONFIG
# ==========================================
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
app = Flask(__name__)

CLIENT_ID     = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI  = os.getenv("REDIRECT_URI")
ROLE_ID       = int(os.getenv("ROLE_ID", "0"))
SERVER_ID     = int(os.getenv("SERVER_ID", "0"))

# ==========================================
# BACKGROUND STORE  (guild_id -> image URL)
# เก็บใน backgrounds.json ใน disk
# ==========================================
BG_FILE = "backgrounds.json"

def load_backgrounds() -> dict:
    if os.path.exists(BG_FILE):
        with open(BG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_backgrounds(data: dict):
    with open(BG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_bg_url(guild_id: int) -> str | None:
    data = load_backgrounds()
    return data.get(str(guild_id))

# ==========================================
# BOT EVENTS
# ==========================================
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s).")
    except Exception as e:
        print(e)
    print(f"HiGHFlowBOT Logged in as {bot.user} (ID: {bot.user.id})")

# ==========================================
# /setup — ส่ง embed verify
# ==========================================
@bot.tree.command(name="setup", description="ส่งข้อความยืนยันตัวตนรับยศ HiGHFlowBOT")
async def setup(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้!", ephemeral=True)
        return

    oauth_url = (
        f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify%20guilds.join"
    )

    embed = discord.Embed(
        title="HiGHFlowBOT - Server Verify",
        description="กดปุ่มด้านล่างเพื่อยืนยันตัวตนและรับยศเข้าสู่เซิร์ฟเวอร์",
        color=0xff0000
    )

    class VerifyView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(discord.ui.Button(
                label="กดรับยศ HiGHFlowBOT",
                style=discord.ButtonStyle.link,
                url=oauth_url
            ))

    await interaction.channel.send(embed=embed, view=VerifyView())
    await interaction.response.send_message("สร้างระบบ Verify สำเร็จ!", ephemeral=True)

# ==========================================
# /change_background — เปลี่ยนพื้นหลัง per-server
# ==========================================
@bot.tree.command(
    name="change_background",
    description="เปลี่ยนพื้นหลังหน้า Verify ของเซิร์ฟเวอร์นี้ (Admin เท่านั้น)"
)
@discord.app_commands.describe(image="อัปโหลดรูปพื้นหลังที่ต้องการ (jpg/png/gif)")
async def change_background(interaction: discord.Interaction, image: discord.Attachment):
    # เฉพาะ Admin เท่านั้น
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้!",
            ephemeral=True
        )
        return

    # ตรวจว่าเป็นรูปภาพ
    allowed = ("image/jpeg", "image/png", "image/gif", "image/webp")
    if image.content_type not in allowed:
        await interaction.response.send_message(
            "❌ ไฟล์ต้องเป็นรูปภาพ (jpg, png, gif, webp) เท่านั้น",
            ephemeral=True
        )
        return

    # บันทึก URL รูปของ guild นี้
    guild_id = str(interaction.guild_id)
    data = load_backgrounds()
    data[guild_id] = image.url
    save_backgrounds(data)

    embed = discord.Embed(
        title="✅ เปลี่ยนพื้นหลังสำเร็จ",
        description=f"หน้า Verify ของเซิร์ฟเวอร์นี้ใช้พื้นหลังใหม่แล้ว\n[ดูรูปที่เลือก]({image.url})",
        color=0x00ff88
    )
    embed.set_thumbnail(url=image.url)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==========================================
# FLASK ROUTES
# ==========================================
@app.route("/")
def home():
    return "HiGHFlowBOT Web Server is Running!"

@app.route("/callback")
def callback():
    code    = request.args.get("code")
    guild_q = request.args.get("guild_id", str(SERVER_ID))

    if not code:
        return "Authorization failed!", 400

    # แลก code → access token
    token_res = requests.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    json_res     = token_res.json()
    access_token = json_res.get("access_token")
    if not access_token:
        return "Failed to get access token!", 400

    # ดึงข้อมูล user
    user_res  = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    user_data    = user_res.json()
    user_id      = user_data.get("id")
    username     = user_data.get("username", "")
    display_name = user_data.get("global_name") or username
    avatar_hash  = user_data.get("avatar")
    avatar_url   = (
        f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=256"
        if avatar_hash
        else "https://cdn.discordapp.com/embed/avatars/0.png"
    )

    # ให้ยศ
    bot_token = os.getenv("DISCORD_TOKEN")
    requests.put(
        f"https://discord.com/api/guilds/{SERVER_ID}/members/{user_id}/roles/{ROLE_ID}",
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type":  "application/json"
        }
    )

    # ดึงชื่อ Role
    role_res  = requests.get(
        f"https://discord.com/api/guilds/{SERVER_ID}/roles",
        headers={"Authorization": f"Bot {bot_token}"}
    )
    role_name = "member"
    for r in role_res.json():
        if str(r.get("id")) == str(ROLE_ID):
            role_name = r.get("name", "member")
            break

    # ดึง background URL ของ guild นี้ (ถ้ามี)
    bg_url = get_bg_url(int(guild_q))

    return render_template(
        "index.html",
        username=username,
        display_name=display_name,
        avatar_url=avatar_url,
        role_name=role_name,
        discord_return_url=f"https://discord.com/channels/{SERVER_ID}",
        bg_url=bg_url or ""
    )

# ==========================================
# RUN
# ==========================================
def run_web():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

if __name__ == "__main__":
    web_thread = threading.Thread(target=run_web)
    web_thread.start()
    bot.run(os.getenv("DISCORD_TOKEN"))
