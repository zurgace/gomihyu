import os as _os; REPO, TMP = _os.environ['GOMI_REPO'], _os.environ['GOMI_TMP']
# Event-controlled intake races, using only synthetic posts and in-process services.
import asyncio, copy, itertools, os, sys, types
from collections import deque
from contextlib import asynccontextmanager

os.environ.update(DISCORD_BOT_TOKEN='fake', PEOPLE_FILE=f'{TMP}/image_people.json')
sys.path.insert(0, REPO)
import bot
from chatlog import ChatLog
from meld import landed_replies
from finetuning.build_dataset import render

NS = types.SimpleNamespace
ids = itertools.count(30000)
ME = NS(id=1, name='Gomihyu', display_name='Gomihyu', bot=True)
MIRA = NS(id=2, name='Mira', display_name='Mira', bot=False)
SOL = NS(id=3, name='Sol', display_name='Sol', bot=False)
OTHER = NS(id=4, name='Other', display_name='Other', bot=True)
bot.client._connection.user = ME
bot.examples = []; bot.earned = []
bot.VISION = True; bot.CHIME_IN_THRESHOLD = 0


class Channel:
    def __init__(self):
        self.id, self.name, self.guild = next(ids), 'synthetic-images', NS(emojis=[])
        self.sent = []

    @asynccontextmanager
    async def typing(self):
        yield

    async def send(self, text, **kw):
        result = NS(id=next(ids))
        self.sent.append((result.id, text, kw))
        return result


class Post:
    def __init__(self, ch, author, text, image=False):
        self.id, self.channel, self.guild = next(ids), ch, ch.guild
        self.author, self.content = author, text
        self.mentions, self.role_mentions, self.channel_mentions = [], [], []
        self.reference = None
        self.attachments = [NS(content_type='image/png', url='https://example.invalid/image')] if image else []
        self.stickers, self.embeds = [], []

    async def add_reaction(self, emoji):
        pass

    def to_reference(self, **kw):
        return NS(message_id=self.id)


async def wait(event):
    await asyncio.wait_for(event.wait(), 3)


async def identical_captions(order, evict):
    ch = Channel()
    if evict:
        bot.history[ch.id] = deque(maxlen=2)
    calls, started, release = [], asyncio.Event(), asyncio.Event()
    old_look = bot.look_at
    older = Post(ch, MIRA, 'gomi what is this?', image=True)
    newer = Post(ch, MIRA, older.content, image=True)
    looking = {p.id: asyncio.Event() for p in (older, newer)}
    looked = {p.id: asyncio.Event() for p in (older, newer)}
    descriptions = {older.id: 'a red kite', newer.id: 'a blue boat'}

    async def fake(payload):
        calls.append(copy.deepcopy(payload))
        if len(calls) == 1:
            started.set(); await release.wait()
            answer = 'Hello there.'
        else:
            answer = 'The older picture is a kite. The newer picture is a boat.'
        return {'message': {'content': answer}, 'done_reason': 'stop'}

    async def look(post):
        looking[post.id].set(); await looked[post.id].wait()
        # Refetched Discord objects must retain the same observation identity.
        return copy.copy(post), {('attachment', 0): descriptions[post.id]}

    bot.ollama_chat, bot.look_at = fake, look
    first = asyncio.create_task(bot.on_message(Post(ch, SOL, 'gomi hello')))
    await wait(started)
    older_task = asyncio.create_task(bot.on_message(older)); await wait(looking[older.id])
    await bot.send_reply(ch, ch.id, 'An intervening bot post.')
    await bot.on_message(Post(ch, OTHER, 'Visible context between the pictures.'))
    newer_task = asyncio.create_task(bot.on_message(newer)); await wait(looking[newer.id])
    tasks = {older.id: older_task, newer.id: newer_task}
    posts = (older, newer) if order == 'older-first' else (newer, older)
    for post in posts:
        looked[post.id].set(); await tasks[post.id]
        requests = {p.id: line for _, line, p in bot.unanswered[ch.id]}
        assert requests[post.id] == f'Mira: {post.content} [image: {descriptions[post.id]}]'
        latest_line = next(line for line in reversed(bot.history[ch.id]) if line.startswith('Mira:'))
        expected = descriptions[newer.id] if looked[newer.id].is_set() else None
        assert latest_line == f'Mira: {newer.content} [image{": " + expected if expected else ""}]', \
            f'{order}, eviction={evict}: older vision overwrote the newer post: {latest_line}'
    release.set(); await first
    bot.look_at = old_look
    assert len(calls) == 2 and not bot.unanswered[ch.id]
    prompt = calls[-1]['messages'][1]['content']
    assert 'The newest message, from Mira:\nMira: gomi what is this? [image: a blue boat]\n\n' in prompt
    targets = prompt.split('These messages still need your reply:\n', 1)[1].split('\nAnswer these requests', 1)[0]
    assert targets.splitlines() == [f'Mira: {p.content} [image: {descriptions[p.id]}]' for p in (older, newer)]
    assert bot.latest_post[ch.id].message.id == newer.id
    stored = ChatLog(bot.chat_log.folder).read(ch.id)
    human = {e['id']: e for e in stored if e['author'] == 'Mira'}
    for post in (older, newer):
        assert human[post.id]['text'] == post.content
        assert human[post.id]['context'] == f'{post.content} [image: {descriptions[post.id]}]'
    reply = next(e for e in stored if e['text'].startswith('The older picture'))
    assert reply['answered_requests'] == [older.id, newer.id]


async def persisted_arrival():
    ch = Channel(); calls = []
    old_look = bot.look_at
    looking, looked = asyncio.Event(), asyncio.Event()
    older = Post(ch, MIRA, 'here is my old picture', image=True)
    newer = Post(ch, SOL, 'what time does our session start?')

    async def look(post):
        looking.set(); await looked.wait()
        return post, {('attachment', 0): 'a red kite'}

    async def fake(payload):
        calls.append(copy.deepcopy(payload))
        return {'message': {'content': 'Our session starts at eight.'}, 'done_reason': 'stop'}

    bot.look_at, bot.ollama_chat = look, fake
    first = asyncio.create_task(bot.on_message(older)); await wait(looking)
    second = asyncio.create_task(bot.on_message(newer)); await asyncio.sleep(0)
    looked.set(); await asyncio.gather(first, second)
    bot.look_at = old_look
    assert len(calls) == len(ch.sent) == 1
    assert 'newest message, from Sol:\nSol: what time does our session start?\n\n' in calls[0]['messages'][1]['content']
    reply_id = ch.sent[0][0]
    disk = ChatLog(bot.chat_log.folder)
    entries = disk.read(ch.id)
    assert [e['id'] for e in entries] == [older.id, newer.id, reply_id], 'saved history follows vision completion'
    assert entries[0]['text'] == older.content and entries[0]['context'].endswith('[image: a red kite]')
    assert entries[-1]['answered_requests'] == []
    bot.history[ch.id].clear(); bot.reload_history()
    assert list(bot.history[ch.id]) == ['Mira: here is my old picture [image: a red kite]',
                                      'Sol: what time does our session start?', 'Gomihyu: Our session starts at eight.']
    disk.add(ch.id, '#synthetic-images', None, MIRA.id, MIRA.name, '🔥', kind='reaction', to=reply_id)
    examples = landed_replies(disk.read(ch.id, reactions=True))
    assert len(examples) == 1
    example = examples[0]
    assert [m['id'] for m in example['history_meta']] == [older.id, newer.id]
    rendered = render(example)['messages'][1]['content']
    assert 'newest message, from Sol:\nSol: what time does our session start?\n\n' in rendered
    assert 'newest message, from Mira' not in rendered


async def main():
    for order in ('older-first', 'newer-first'):
        for evict in (False, True):
            await identical_captions(order, evict)
    await persisted_arrival()
    print('IMAGE IDENTITY AND ARRIVAL TESTS PASSED')


asyncio.run(main())
