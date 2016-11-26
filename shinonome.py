# coding: utf-8

import configparser
import discord
from discord.ext import commands
import asyncio
import random

config = configparser.ConfigParser()
config.read('shinonome.ini')
settings = config['settings']

description = '''
Nano is an android schoolgirl, built by the Professor. 
She worries about keeping her identity as a robot from 
other people, even though the large wind-up key on her 
back makes it quite obvious. Her limbs will sometimes 
fall apart, revealing items that the Professor 
installed into her system without her noticing, 
ranging from beam-firing weapons to Swiss rolls. She 
is the Professor's caretaker, and spends her days 
helping her and doing all the household chores.'''
bot = commands.Bot(command_prefix=commands.when_mentioned_or('!'), description=description)

@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')
    await bot.change_presence(game=discord.Game(name='the game of life'))

@bot.command()
async def add(left : int, right : int):
    """Adds two numbers together."""
    await bot.say(left + right)

@bot.command()
async def roll(dice='1d6'):
    """Rolls a dice in NdN format."""
    try:
        rolls, limit = map(int, dice.split('d'))
    except Exception:
        await bot.say('Format has to be in NdN!')
        return

    result = ', '.join(str(random.randint(1, limit)) for r in range(rolls))
    await bot.say(result)

@bot.command(description='For when you wanna settle the score some other way')
async def choose(*choices : str):
    """Chooses between multiple choices."""
    await bot.say(random.choice(choices))

@bot.command()
async def joined(member : discord.Member):
    """Says when a member joined."""
    await bot.say('{0.name} joined in {0.joined_at}'.format(member))

if not discord.opus.is_loaded():
    discord.opus.load_opus('opus')

class VoiceEntry:
    def __init__(self, message, player):
        self.requester = message.author
        self.channel = message.channel
        self.player = player

    def __str__(self):
        fmt = '*{0.title}* uploaded by {0.uploader} and requested by {1.display_name}'
        duration = self.player.duration
        if duration:
            fmt = fmt + ' [length: {0[0]}m {0[1]}s]'.format(divmod(duration, 60))
        return fmt.format(self.player, self.requester)

class VoiceState:
    def __init__(self, bot):
        self.current = None
        self.voice = None
        self.bot = bot
        self.play_next_song = asyncio.Event()
        self.songs = asyncio.Queue()
        self.skip_votes = set() # a set of user_ids that voted
        self.audio_player = self.bot.loop.create_task(self.audio_player_task())
        self.queue = []

    def is_playing(self):
        if self.voice is None or self.current is None:
            return False

        player = self.current.player
        return not player.is_done()

    @property
    def player(self):
        return self.current.player

    def skip(self):
        self.skip_votes.clear()
        if self.is_playing():
            self.player.stop()

    def toggle_next(self):
        self.bot.loop.call_soon_threadsafe(self.play_next_song.set)

    async def audio_player_task(self):
        while True:
            self.play_next_song.clear()
            self.current = await self.songs.get()
            await self.bot.send_message(self.current.channel, 'Now playing ' + str(self.current))
            self.current.player.start()
            await self.play_next_song.wait()
            self.queue.pop(0)

class Music:
    """Voice related commands.
    Works in multiple servers at once.
    """
    def __init__(self, bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, server):
        state = self.voice_states.get(server.id)
        if state is None:
            state = VoiceState(self.bot)
            self.voice_states[server.id] = state

        return state

    async def create_voice_client(self, channel):
        voice = await self.bot.join_voice_channel(channel)
        state = self.get_voice_state(channel.server)
        state.voice = voice

    def __unload(self):
        for state in self.voice_states.values():
            try:
                state.audio_player.cancel()
                if state.voice:
                    self.bot.loop.create_task(state.voice.disconnect())
            except:
                pass

    @commands.command(pass_context=True, no_pm=True)
    async def join(self, ctx, *, channel : discord.Channel):
        """Joins a voice channel."""
        try:
            await self.create_voice_client(channel)
        except discord.ClientException:
            await self.bot.say('Already in a voice channel...')
        except discord.InvalidArgument:
            await self.bot.say('This is not a voice channel...')
        else:
            await self.bot.say('Ready to play audio in ' + channel.name)

    @commands.command(pass_context=True, no_pm=True)
    async def summon(self, ctx):
        """Summons the bot to join your voice channel."""
        summoned_channel = ctx.message.author.voice_channel
        if summoned_channel is None:
            await self.bot.say('You are not in a voice channel.')
            return False

        state = self.get_voice_state(ctx.message.server)
        if state.voice is None:
            state.voice = await self.bot.join_voice_channel(summoned_channel)
        else:
            await state.voice.move_to(summoned_channel)

        return True

    @commands.command(pass_context=True, no_pm=True)
    async def play(self, ctx, *, song : str):
        """Plays a song.
        If there is a song currently in the queue, then it is
        queued until the next song is done playing.
        This command automatically searches as well from YouTube.
        The list of supported sites can be found here:
        https://rg3.github.io/youtube-dl/supportedsites.html
        """
        state = self.get_voice_state(ctx.message.server)
        opts = {
            'default_search': 'auto',
            'quiet': True,
        }

        if state.voice is None:
            success = await ctx.invoke(self.summon)
            if not success:
                return

        try:
            player = await state.voice.create_ytdl_player(song, ytdl_options=opts, after=state.toggle_next)
        except Exception as e:
            fmt = 'An error occurred while processing this request: ```py\n{}: {}\n```'
            await self.bot.send_message(ctx.message.channel, fmt.format(type(e).__name__, e))
        else:
            player.volume = 0.6
            entry = VoiceEntry(ctx.message, player)
            await self.bot.say('Enqueued ' + str(entry))
            await state.songs.put(entry)
            state.queue.append(str(entry))

    @commands.command(pass_context=True, no_pm=True)
    async def volume(self, ctx, value : int):
        """Sets the volume of the currently playing song."""

        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.volume = value / 100
            await self.bot.say('Set the volume to {:.0%}'.format(player.volume))

    @commands.command(pass_context=True, no_pm=True)
    async def pause(self, ctx):
        """Pauses the currently played song."""
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.pause()

    @commands.command(pass_context=True, no_pm=True)
    async def resume(self, ctx):
        """Resumes the currently played song."""
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.resume()

    @commands.command(pass_context=True, no_pm=True)
    async def stop(self, ctx):
        """Stops playing audio and leaves the voice channel.
        This also clears the queue.
        """
        server = ctx.message.server
        state = self.get_voice_state(server)

        if state.is_playing():
            player = state.player
            player.stop()

        try:
            state.audio_player.cancel()
            del self.voice_states[server.id]
            await state.voice.disconnect()
        except:
            pass

    @commands.command(pass_context=True, no_pm=True)
    async def skip(self, ctx):
        """Vote to skip a song. The song requester can automatically skip.
        3 skip votes are needed for the song to be skipped.
        """

        state = self.get_voice_state(ctx.message.server)
        if not state.is_playing():
            await self.bot.say('Not playing any music right now...')
            return

        voter = ctx.message.author
        if voter == state.current.requester:
            await self.bot.say('Requester requested skipping song...')
            state.skip()
        elif voter.id not in state.skip_votes:
            state.skip_votes.add(voter.id)
            total_votes = len(state.skip_votes)
            if total_votes >= 3:
                await self.bot.say('Skip vote passed, skipping song...')
                state.skip()
            else:
                await self.bot.say('Skip vote added, currently at [{}/3]'.format(total_votes))
        else:
            await self.bot.say('You have already voted to skip this song.')

    @commands.command(pass_context=True, no_pm=True)
    async def playing(self, ctx):
        """Shows info about the currently played song."""

        state = self.get_voice_state(ctx.message.server)
        if state.current is None:
            await self.bot.say('Not playing anything.')
        else:
            skip_count = len(state.skip_votes)
            await self.bot.say('Now playing {} [skips: {}/3]'.format(state.current, skip_count))

    @commands.command(pass_context=True, no_pm=True)
    async def playing(self, ctx):
        """Shows info about the currently played song."""

        state = self.get_voice_state(ctx.message.server)
        if state.current is None:
            await self.bot.say('Not playing anything.')
        else:
            skip_count = len(state.skip_votes)
            await self.bot.say('Now playing {} [skips: {}/3]'.format(state.current, skip_count))

    @commands.command(pass_context=True, no_pm=True)
    async def queue(self, ctx):
        """Lists the songs currently queued up."""

        state = self.get_voice_state(ctx.message.server)
        if len(state.queue) == 0:
            await self.bot.say('Queue is empty.')
        else:
            text = ''
            for i, song in enumerate(state.queue, 1):
                text = text + '\n' + str(i) + '. ' + str(song)
            await self.bot.say(text)

class Copypasta:
    """Copypasta posting commands.
    """
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def wewlad(self):
        await bot.say('''⠖⠚⠉⠉⠳⣦⢀⢀⢀⢀⢀⢀⢀⢀⣼⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⣀⣀⡀⢀⢀⢀⣀⣀
⢀⢀⢀⡴⢋⣀⡀⢀⢀⢀⢀⢻⣷⢀⢀⢀⢀⢀⢀⣼⠇⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⣠⣾⠿⠛⠉⠁⢀⣴⡟⠁⢀⡇⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⣠⣤ ⢀⢀⠎⣰⣿⠿⣿⡄⢀⢀⢀⢸⣿⡆⢀⢀⢀⢀⣾⡿⢀⢀⢀⢀⡀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⣰⡟⠁⢀⢀⢀⢀⣾⡟⢀⢀⢀⡟⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢠⣿⡿ ⢀⠏⢰⣿⡟⢀⣿⡇⢀⢀⢀⣿⣿⡇⢀⢀⢀⢮⣿⠇⢀⢀⢠⠞⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢰⠏⢀⢀⢀⢀⢀⣿⣿⠁⢀⢀⢸⠇⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⣼⣿⠃ ⡜⢀⣾⡿⠃⢠⣿⠁⢀⢀⢸⣿⣿⠁⢀⢀⢊⣿⡟⢀⢀⡰⠃⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⡿⢀⢀⢀⢀⢀⣾⣿⠇⢀⢀⢠⠏⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢠⣿⡟ ⡇⢀⠋⢀⢀⣾⡏⢀⢀⢀⣿⣿⡏⢀⠠⠃⣾⣿⠇⢀⡴⠁⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⡇⢀⢀⢀⢀⣼⣿⡟⢀⢀⣰⠋⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⣼⣿⠁ ⠹⣄⣀⣤⣿⠟⢀⢀⢀⣾⣿⡟⢀⡐⠁⣼⣿⡟⢀⡰⣡⣶⡶⣆⢀⢀⣀⣀⢀⢀⣀⣀⢀⢀⣀⣀⢀⢀⢀⢀⢀⢀⢀⢷⢀⢀⢀⢸⣿⣿⠃⣠⠞⢁⣴⣶⣠⣶⡆⢀⢀⢀⣠⣶⣶⣰⣿⡏ ⢀⠈⠉⠉⢀⢀⢀⢀⣼⣿⡟⠁⠄⢀⢰⣿⣿⠃⣰⣿⣿⠏⢀⣿⢀⣸⣿⠏⢀⢸⣿⠃⢀⣼⣿⠇⢀⢀⢀⢀⢀⢀⢀⢀⠑⢀⢠⣿⣿⣿⠋⠁⣰⣿⡟⠁⣿⣿⢀⢀⢀⣴⣿⠟⢀⣿⡿ ⢀⢀⢀⢀⢀⢀⢀⣼⣿⠟⡀⢀⢀⢀⣿⣿⡟⢠⣿⣿⡟⢀⣰⠇⢀⣿⡿⢀⢀⣿⡏⢀⢰⣿⡏⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢰⣿⣿⠃⢀⣼⣿⡟⢀⣸⣿⠃⢀⢀⣼⣿⡏⢀⣼⣿⠃ ⢀⢀⢀⢀⢀⢀⣼⡿⠋⢀⢀⢀⢀⢸⣿⣿⠃⣿⣿⣿⠁⣰⠏⢀⣼⣿⠃⢀⣾⡿⢀⢠⣿⡟⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⣿⣿⡏⢀⣰⣿⣿⠁⢠⣿⡏⢀⢀⣸⣿⡿⢀⢰⣿⠇ ⢀⢀⢀⢀⢀⣾⣟⠕⠁⢀⢀⢀⢀⢸⣿⣿⣼⣿⣿⡿⠊⠁⣰⢣⣿⡟⢀⣰⣿⠃⢀⣾⣿⠁⡼⢀⢀⢀⣰⡾⠿⠿⣿⣶⣦⣾⣿⡟⢀⢀⣿⣿⡇⢀⣾⡿⢀⡞⢰⣿⣿⠇⢠⣿⡟⢠⡏ ⢀⢀⢀⢠⣾⡿⠁⢀⢀⢀⢀⢀⢀⢸⣿⣿⠃⣿⣿⢀⢀⡴⠃⣾⣿⣧⣰⣿⣿⣄⣾⣿⣧⡼⠁⢀⢀⢀⣿⢀⢀⢀⢀⢹⣿⣿⣟⢀⢀⢸⣿⣿⣧⣾⣿⣷⡾⠁⣼⣿⣿⣤⣿⣿⣷⡟ ⢀⢀⢀⠟⠉⢀⢀⢀⢀⢀⢀⢀⢀⢀⠻⠋⢀⢿⣿⣶⠟⠁⢀⠻⣿⡿⠛⣿⣿⠏⢿⣿⠟⠁⢀⢀⢀⢀⠘⠦⣤⣤⡶⠟⢻⣿⣿⢀⢀⠘⣿⣿⠋⢿⣿⠟⢀⢀⠸⣿⡿⠋⣿⣿⠏ ⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢿⣿⣇⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⣀⣠⣤⣤⣤⣤⣀⡀ ⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⠈⢿⣿⣆⢀⢀⢀⢀⢀⢀⣠⡤⠶⠛⠛⠛⠻⢿⣿⣿⣿⣿⣶⣄ ⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⢀⠙⠿⣷⣤⣤⠶⠞⠋⠁⢀⢀⢀⢀⢀⢀⠈⠻⠛⠉⠉⠉⠙
    ''')

    @commands.command()
    async def sakurako(self):
        await bot.say('''░░░░░▄▄▄▀▀▀▀▀▄▄ 
░░░░░░░░▄▄▀▀▒▒▒▒▒▒▒▒▒▒▀▀▄▄▄ 
░░░░░░▄▀▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒█▀▀▄ 
░░░░░█▐▒▒▒▐▐▒▒▒▌▐▒▒▌▌▒▒▌▒▒▒▒▀▄░▀▄ 
░░░░█▐▄▒▒▒▌▌▒▒▌░▌▒▐▐▐▒▒▐▒▒▌▒▀▄▀▄ 
░░░█▐▒▒▀▀▌░▀▀▀░░▀▀▀░░▀▀▄▌▌▐▒▒▒▌▐ 
░░▐▒▒▀▀▄▐░▀▀▄▄░░░░░░░░░░░▐▒▌▒▒▐░▌ 
░░▐▒▌▒▒▒▌░▄▄▄▄█▄░░░░░░░▄▄▄▐▐▄▄▀ 
░░▌▐▒▒▒▐░░░░░░░░░░░░░▀█▄░░░░▌▌ 
▄▀▒▒▌▒▒▐░░░░░░░▄░░▄░░░░░▀▀░░▌▌ 
▄▄▀▒▐▒▒▐░░░░░░░▐▀▀▀▄▄▀░░░░░░▌▌ 
▄▄▀▀▄▒▒▐░░░░░░░▌▒▒▒▒▐░░░░░░▐▒▐ 
░░░░█▌▒▒▌░░░░░▐▒▒▒▒▒▌░░░░░░▌▐▒▀▀▄ 
░░▄▀▒▒▒▒▐░░░░░▐▒▒▒▒▐░░░░░▄█▄▒▐▒▒▒▌ 
▄▀▒▒▒▒▒▄██▀▄▄░░▀▄▄▀░░▄▄▀█▄░█▀▒▒▒▒▐ 
▐▒▒▒▄▄▀██▌░░░▀▀▀▀████░█░░▀█▄▒▒▒▄▀ 
░▀▄▄▐▐▌▐██░░▄░░░▐███░█░░░░░█▄▄▒▌ 
▀▄░░▀▄▀▄▀█▀▀▄▀▄▄██▀▄▀░░░░░▄▀▄░▐▒▌''')

    @commands.command()
    async def akari(self):
        await bot.say('''▌█████▌█░████████▐▀██▀
░▄█████░█████▌░█░▀██████▌█▄▄▀▄
░▌███▌█░▐███▌▌░░▄▄░▌█▌███▐███░▀
▐░▐██░░▄▄▐▀█░░░▐▄█▀▌█▐███▐█
░░███░▌▄█▌░░▀░░▀██░░▀██████▌
░░░▀█▌▀██▀░▄░░░░░░░░░███▐███
░░░░██▌░░░░░░░░░░░░░▐███████
░░░░███░░░░░▀█▀░░░░░▐██▐███▀▌
░░░░▌█▌█▄░░░░░░░░░▄▄████▀░▀
░░░░░░█▀██▄▄▄░▄▄▀▀▒█▀█░▀''')

    @commands.command()
    async def pacer(self):
        await bot.say('''The FitnessGram Pacer Test is a multistage aerobic capacity test that progressively gets more difficult as it continues. The 20 meter pacer test will begin in 30 seconds. Line up at the start. The running speed starts slowly but gets faster each minute after you hear this signal bodeboop. A sing lap should be completed every time you hear this sound. ding Remember to run in a straight line and run as long as possible. The second time you fail to complete a lap before the sound, your test is over. The test will begin on the word start. On your mark. Get ready!… Start. ding﻿''')

bot.add_cog(Music(bot))
bot.add_cog(Copypasta(bot))

bot.run(settings['token'])
