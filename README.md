# HiGHFlowBOT — Discord Verification & Web Panel

ระบบยืนยันตัวตน Discord อัตโนมัติ พร้อมหน้าต่าง Web Panel สไตล์ Gothic Glassmorphism (Flask) และคำสั่ง Slash Command จัดการ Embed แบบยืดหยุ่น รองรับการ Deploy บน Render รัน 24 ชั่วโมงด้วย UptimeRobot

---

## 📁 โครงสร้างโปรเจกต์ (Project Structure)
```
discord-verify-bot/
├── main.py              # โค้ดหลักรัน Discord Bot + Flask Web Server
├── Procfile             # ไฟล์กำหนดคำสั่ง Start สำหรับ Cloud Hosting (Render)
├── requirements.txt     # รายการ Library ที่จำเป็น
├── .env.example         # ตัวอย่างการตั้งค่า Environment Variables
├── .gitignore           # ป้องกันการ Push ไฟล์ .env ขึ้น GitHub
├── static/              # ที่เก็บ assets เช่น background.gif
│   ├── background.gif   # (แนะนำ) ภาพเคลื่อนไหวพื้นหลังหน้าเว็บ
│   └── README.md
└── templates/
    └── index.html       # หน้าเว็บ Verify Success สไตล์ Glassmorphism
```

---

## ⚙️ ค่า Environment Variables (.env)

| ตัวแปร | คำอธิบาย |
|---|---|
| `DISCORD_BOT_TOKEN` | Token ของบอทจาก Discord Developer Portal (`Bot` > `Reset Token`) |
| `CLIENT_ID` | Application ID จาก `OAuth2` > `General` |
| `CLIENT_SECRET` | Client Secret จาก `OAuth2` > `General` |
| `REDIRECT_URI` | URL ปลายทางหลังล็อกอิน เช่น `https://<your-render-app>.onrender.com/callback` |
| `GUILD_ID` | ID เซิร์ฟเวอร์ Discord ที่ต้องการแจกยศ |
| `VERIFIED_ROLE_ID` | ID ของยศ (Role) ที่ต้องการมอบให้เมื่อยืนยันตัวตนสำเร็จ |
| `PORT` | พอร์ตสำหรับ Flask (Render จะกำหนดให้อัตโนมัติเป็น 10000 หรือ 5000) |

---

## 🚀 คำสั่ง Slash Commands ของบอท

1. **/setup_verify**
   - ส่งข้อความ Embed ยืนยันตัวตนพร้อมปุ่ม Link สวยงาม
   - พารามิเตอร์ปรับแต่งได้: `channel`, `title`, `description`, `image_url`, `button_text`, `button_emoji`, `color_hex`
2. **/edit_verify**
   - แก้ไข Embed และปุ่มของข้อความเดิมได้โดยใช้ `message_id`
3. **/check_config**
   - ตรวจสอบสถานะการเชื่อมต่อบอท, เซิร์ฟเวอร์ และบทบาท
