import discord
import asyncio
import threading
import io
from http.server import HTTPServer, BaseHTTPRequestHandler
from discord.ext import commands
from config import (
    DISCORD_TOKEN, TICKET_CATEGORY_ID, STAFF_ROLE_ID,
    TRANSCRIPT_CHANNEL_ID, FOUNDERSHIP_TEAM_ROLE_ID,
    ROLE_LEAD_ADMIN, ROLE_SENIOR_ADMIN, ROLE_ADMIN, ROLE_JUNIOR_ADMIN, ROLE_TRIAL_ADMIN,
    ROLE_ADMINISTRATION_TEAM,
    ROLE_LEAD_MOD, ROLE_SENIOR_MOD, ROLE_MOD, ROLE_JUNIOR_MOD, ROLE_TRIAL_MOD,
    ROLE_MODERATION_TEAM, ROLE_STAFF_TEAM
)
from handlers.ticket_handler import (
    handle_new_ticket, handle_followup_message,
    stop_ticket, is_active_ticket, is_first_message_done,
    active_tickets
)

# ───────────────────────────────────────────
# HTTP SERVER
# ───────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass

def run_http_server():
    server = HTTPServer(("0.0.0.0", 10000), HealthHandler)
    server.serve_forever()

# ───────────────────────────────────────────
# BOT SETUP
# ───────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

async def get_prefix(bot, message):
    return ["!"]

bot = commands.Bot(command_prefix=get_prefix, intents=intents)

# ───────────────────────────────────────────
# HELPERS
# ───────────────────────────────────────────

def is_staff(ctx: commands.Context) -> bool:
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    return staff_role in ctx.author.roles

def is_ticket_channel(ctx: commands.Context) -> bool:
    return (
        ctx.channel.category is not None
        and ctx.channel.category.id == TICKET_CATEGORY_ID
        and ctx.channel.name.startswith("support-")
    )

async def send_transcript(channel: discord.TextChannel, guild: discord.Guild, closed_by: discord.Member):
    transcript_channel = guild.get_channel(TRANSCRIPT_CHANNEL_ID)
    if not transcript_channel:
        print(f"[Transcript] Channel {TRANSCRIPT_CHANNEL_ID} not found!")
        return
    messages = []
    async for msg in channel.history(limit=500, oldest_first=True):
        timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
        content = msg.content or "(no text content)"
        messages.append(f"[{timestamp}] {msg.author.display_name}: {content}")
    transcript_text = "\n".join(messages) if messages else "(No messages)"
    embed = discord.Embed(
        title=f"📋 Ticket Transcript — #{channel.name}",
        color=discord.Color.blurple(),
        description=f"**Closed by:** {closed_by.mention}\n**Channel:** #{channel.name}"
    )
    embed.set_footer(text=f"Ticket closed • {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    file = discord.File(
        fp=io.BytesIO(transcript_text.encode("utf-8")),
        filename=f"transcript-{channel.name}.txt"
    )
    await transcript_channel.send(embed=embed, file=file)
    print(f"[Transcript] Sent for #{channel.name}")

# ───────────────────────────────────────────
# EVENTS
# ───────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Bot online: {bot.user}")
    print(f"📂 Watching category ID: {TICKET_CATEGORY_ID}")

@bot.event
async def on_guild_channel_create(channel):
    if not isinstance(channel, discord.TextChannel):
        return
    if not channel.category or channel.category.id != TICKET_CATEGORY_ID:
        return
    if not channel.name.startswith("support-"):
        return
    print(f"[+] Ticket detected: #{channel.name}")
    asyncio.create_task(handle_new_ticket(bot, channel, channel.guild))

@bot.event
async def on_message(message: discord.Message):
    await bot.process_commands(message)
    if message.author.bot:
        return
    if not message.guild:
        return

    # Komut mesajlarını AI'ya gönderme
    if message.content.startswith("!"):
        return

    if not message.channel.category:
        return
    if message.channel.category.id != TICKET_CATEGORY_ID:
        return
    if not message.channel.name.startswith("support-"):
        return

    channel_id = message.channel.id
    if not is_active_ticket(channel_id):
        return
    ticket = active_tickets.get(channel_id)
    if not ticket:
        return

    # Sadece ticket sahibinin mesajları işlensin
    ticket_user = ticket.get("user")
    if ticket_user and message.author.id != ticket_user.id:
        return

    if ticket.get("waiting", False):
        return
    if not is_first_message_done(channel_id):
        return

    await handle_followup_message(message, message.guild)

# ───────────────────────────────────────────
# TICKET COMMANDS
# ───────────────────────────────────────────

@bot.command(name="stop")
async def stop_command(ctx: commands.Context):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return
    if not is_active_ticket(ctx.channel.id):
        await ctx.send("❌ Not an active ticket.")
        return
    stop_ticket(ctx.channel.id)
    await ctx.send("🛑 New Jersey | Support disabled.")

@bot.command(name="close")
async def close_command(ctx: commands.Context):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return

    class ConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)
            self.confirmed = None

        @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Only the command user can confirm.", ephemeral=True)
                return
            self.confirmed = True
            self.stop()
            await interaction.response.defer()

        @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Only the command user can cancel.", ephemeral=True)
                return
            self.confirmed = False
            self.stop()
            await interaction.response.defer()

    view = ConfirmView()
    confirm_msg = await ctx.send(
        "⚠️ Are you sure you want to close this ticket?\n"
        "The ticket will be **deleted in 30 seconds** after confirmation.",
        view=view
    )
    await view.wait()

    if view.confirmed is None:
        for item in view.children:
            item.disabled = True
        await confirm_msg.edit(content="⏰ Close request timed out. Ticket was **not** closed.", view=view)
        return

    if not view.confirmed:
        for item in view.children:
            item.disabled = True
        await confirm_msg.edit(content="❌ Ticket close **cancelled**.", view=view)
        return

    for item in view.children:
        item.disabled = True
    await confirm_msg.edit(content="✅ Ticket confirmed for closure. Sending transcript...", view=view)

    stop_ticket(ctx.channel.id)
    await send_transcript(ctx.channel, ctx.guild, ctx.author)

    countdown_msg = await ctx.send("🗑️ This ticket will be deleted in **30 seconds**...")
    for i in [25, 20, 15, 10, 5]:
        await asyncio.sleep(5)
        try:
            await countdown_msg.edit(content=f"🗑️ This ticket will be deleted in **{i} seconds**...")
        except Exception:
            pass
    await asyncio.sleep(5)

    try:
        await ctx.channel.delete(reason=f"Ticket closed by {ctx.author.display_name}")
    except Exception as e:
        print(f"[Close] Failed to delete channel: {e}")

@bot.command(name="claim")
async def claim_command(ctx: commands.Context):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return
    await ctx.channel.edit(topic=f"Claimed by {ctx.author.display_name}")
    await ctx.send(f"✅ Ticket claimed by {ctx.author.mention}.")

@bot.command(name="unclaim")
async def unclaim_command(ctx: commands.Context):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return
    await ctx.channel.edit(topic=None)
    await ctx.send("✅ Ticket unclaimed.")

@bot.command(name="rename")
async def rename_command(ctx: commands.Context, *, new_name: str = None):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return
    if not new_name:
        await ctx.send("❌ Usage: `!rename <new name>`")
        return
    safe_name = new_name.lower().replace(" ", "-")
    await ctx.channel.edit(name=f"support-{safe_name}")
    await ctx.send(f"✅ Channel renamed to `support-{safe_name}`.")

@bot.command(name="remove")
async def remove_command(ctx: commands.Context, member: discord.Member = None):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return
    if not member:
        await ctx.send("❌ Usage: `!remove @user`")
        return
    await ctx.channel.set_permissions(member, overwrite=None)
    await ctx.send(f"✅ {member.mention} removed from this ticket.")

@bot.command(name="add")
async def add_command(ctx: commands.Context, member: discord.Member = None):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return
    if not member:
        await ctx.send("❌ Usage: `!add @user`")
        return
    await ctx.channel.set_permissions(member, read_messages=True, send_messages=True)
    await ctx.send(f"✅ {member.mention} added to this ticket.")

# ───────────────────────────────────────────
# !cmds
# ───────────────────────────────────────────

@bot.command(name="cmds")
async def cmds_command(ctx: commands.Context):
    embed = discord.Embed(
        title="📖 New Jersey | Support — Commands",
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="🎫 Ticket Commands",
        value=(
            "`!stop` — Disable AI assistance in this ticket\n"
            "`!close` — Close & delete ticket (confirmation + transcript)\n"
            "`!claim` — Claim this ticket\n"
            "`!unclaim` — Unclaim this ticket\n"
            "`!rename <name>` — Rename the ticket channel\n"
            "`!add @user` — Add a user to this ticket\n"
            "`!remove @user` — Remove a user from this ticket"
        ),
        inline=False
    )
    embed.set_footer(text="New Jersey | Support • New Jersey State Roleplay | ER:LC")
    await ctx.send(embed=embed)

# ───────────────────────────────────────────
# MAIN
# ───────────────────────────────────────────

if __name__ == "__main__":
    t = threading.Thread(target=run_http_server, daemon=True)
    t.start()
    print("🌐 HTTP health server started on port 10000")
    bot.run(DISCORD_TOKEN)
