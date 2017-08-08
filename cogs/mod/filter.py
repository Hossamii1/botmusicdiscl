import logging
from typing import Tuple

import discord
from discord.ext import commands

from core import checks, Config
from core.bot import Red
from core.utils.chat_formatting import pagify
from .common import is_allowed_by_hierarchy, is_mod_or_superior


class Filter:
    """Filter-related commands"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.settings = Config.get_conf(self, 4766951341)
        default_guild_settings = {
            "filter": []
        }
        self.settings.register_guild(**default_guild_settings)
        global logger
        logger = logging.getLogger("mod")
        # Prevents the logger from being loaded again in case of module reload
        if logger.level == 0:
            logger.setLevel(logging.INFO)
            handler = logging.FileHandler(
                filename='mod.log', encoding='utf-8', mode='a')
            handler.setFormatter(
                logging.Formatter('%(asctime)s %(message)s', datefmt="[%d/%m/%Y %H:%M]"))
            logger.addHandler(handler)

    @commands.group(name="filter")
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    async def _filter(self, ctx: commands.Context):
        """Adds/removes words from filter

        Use double quotes to add/remove sentences
        Using this command with no subcommands will send
        the list of the server's filtered words."""
        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)
            server = ctx.guild
            author = ctx.author
            word_list = self.settings.guild(server).filter()
            if word_list:
                words = ", ".join(word_list)
                words = "Filtered in this server:\n\n" + words
                try:
                    for page in pagify(words, delims=[" ", "\n"], shorten_by=8):
                        await author.send(page)
                except discord.Forbidden:
                    await ctx.send("I can't send direct messages to you.")

    @_filter.command(name="add")
    async def filter_add(self, ctx: commands.Context, *words: str):
        """Adds words to the filter

        Use double quotes to add sentences
        Examples:
        filter add word1 word2 word3
        filter add \"This is a sentence\""""
        if words == ():
            await self.bot.send_cmd_help(ctx)
            return
        server = ctx.guild
        added = await self.add_to_filter(server, words)
        if added:
            await ctx.send("Words added to filter.")
        else:
            await ctx.send("Words already in the filter.")

    @_filter.command(name="remove")
    async def filter_remove(self, ctx: commands.Context, *words: str):
        """Remove words from the filter

        Use double quotes to remove sentences
        Examples:
        filter remove word1 word2 word3
        filter remove \"This is a sentence\""""
        if words == ():
            await self.bot.send_cmd_help(ctx)
            return
        server = ctx.guild
        removed = self.remove_from_filter(server, words)
        if removed:
            await ctx.send("Words removed from filter.")
        else:
            await ctx.send("Those words weren't in the filter.")

    async def add_to_filter(self, server: discord.Guild, *words: tuple) -> bool:
        added = 0
        cur_list = self.settings.guild(server).filter()
        for w in words:
            if w.lower() not in cur_list and w != "":
                cur_list.append(w.lower())
                added += 1
        if added:
            await self.settings.guild(server).set("filter", cur_list)
            return True
        else:
            return False

    async def remove_from_filter(self, server: discord.Guild, *words: tuple) -> bool:
        removed = 0
        cur_list = self.settings.guild(server).filter()
        for w in words:
            if w.lower() in cur_list:
                cur_list.remove(w.lower())
                removed += 1
        if removed:
            await self.settings.guild(server).set("filter", cur_list)
            return True
        else:
            return False

    async def check_filter(self, message: discord.Message):
        server = message.guild
        word_list = self.settings.guild(server).filter()
        if word_list:
            for w in word_list:
                if w in message.content.lower():
                    try:
                        await message.delete(reason="Filtered: {}".format(w))
                    except:
                        pass

    async def on_message(self, message: discord.Message):
        author = message.author
        valid_user = isinstance(author, discord.Member) and not author.bot

        #  Bots and mods or superior are ignored from the filter
        mod_or_superior = await is_mod_or_superior(self.bot, obj=author)
        if not valid_user or mod_or_superior:
            return

        await self.check_filter(message)

    async def on_message_edit(self, _, message):
        author = message.author
        if message.server is None or self.bot.user == author:
            return

        valid_user = isinstance(author, discord.Member) and not author.bot
        mod_or_superior = await is_mod_or_superior(self.bot, obj=author)
        if not valid_user or mod_or_superior:
            return

        await self.check_filter(message)
