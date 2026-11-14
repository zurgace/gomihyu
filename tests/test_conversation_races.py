import os as _os; REPO, TMP = _os.environ['GOMI_REPO'], _os.environ['GOMI_TMP']
# Async boundaries are held by events; no inference, Discord, or wall-clock races.
import asyncio, copy, itertools, json, os, sys, types
from contextlib import asynccontextmanager

os.environ.update(DISCORD_BOT_TOKEN='fake', PEOPLE_FILE=f'{TMP}/race_people.json')
sys.path.insert(0, REPO)
import bot

NS = types.SimpleNamespace
ids = itertools.count(10000)
ME = NS(id=1, name='Gomihyu', display_name='Gomihyu', bot=True)
MIRA = NS(id=2, name='Mira', display_name='Mira', bot=False)
SOL = NS(id=3, name='Sol', display_name='Sol', bot=False)
bot.client._connection.user = ME
bot.examples = []; bot.earned = []
bot.VISION = False; bot.CHIME_IN_THRESHOLD = 0; bot.REACT_ONLY_MAX_WORDS = 2


class Channel:
    def __init__(self, fail=False):
        self.id, self.name, self.guild = next(ids), 'synthetic', NS(emojis=[])
        self.sent, self.fail, self.attempts = [], fail, 0

    @asynccontextmanager
    async def typing(self):
        yield

    async def send(self, text, **kw):
        self.attempts += 1
        if self.fail == 'timeout':
            self.sent.append(text)  # the remote may have accepted it before the connection broke
            raise TimeoutError('synthetic ambiguous delivery')
        if self.fail:
            raise bot.discord.HTTPException(NS(status=403, reason='forbidden'), 'fake delivery failure')
        self.sent.append(text)
        return NS(id=next(ids))


class Post:
    def __init__(self, ch, author, text, image=False):
        self.id, self.channel, self.guild = next(ids), ch, ch.guild
        self.author, self.content = author, text
        self.mentions, self.role_mentions, self.channel_mentions = [], [], []
        self.reference = None
        self.attachments = [NS(content_type='image/png', url='https://example.invalid/picture')] if image else []
        self.stickers, self.embeds = [], []
        self.reacting, self.reacted = None, None

    async def add_reaction(self, emoji):
        if self.reacting:
            self.reacting.set()
            await self.reacted.wait()

    def to_reference(self, **kw):
        return NS(message_id=self.id)


async def wait(event):
    await asyncio.wait_for(event.wait(), 3)


def model(answers, pause=0):
    calls, started, release = [], asyncio.Event(), asyncio.Event()

    async def fake(payload):
        index = len(calls)
        calls.append(copy.deepcopy(payload))
        assert index < len(answers), 'unexpected extra generation'
        if index == pause:
            started.set()
            await release.wait()
        answer = answers[index]
        if answer is None or isinstance(answer, dict):
            return answer
        return {'message': {'content': answer}, 'done_reason': 'stop'}

    bot.ollama_chat = fake
    return calls, started, release


async def reaction_vision():
    bot.VISION = True; bot.CHIME_IN_THRESHOLD = 8
    ch = Channel(); first_post = Post(ch, MIRA, 'who wants to play chess?')
    first_post.reacting, first_post.reacted = asyncio.Event(), asyncio.Event()
    looking, looked, decision_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    old_look, old_chime = bot.look_at, bot.chimes_in
    calls = []

    async def fake(payload):
        calls.append(copy.deepcopy(payload))
        if 'format' in payload:
            content = json.dumps({'read': 'question', 'interest': 10, 'react': 10, 'emoji': '🔥'})
        else:
            content = 'The picture shows a sleeping cat.'
        return {'message': {'content': content}, 'done_reason': 'stop'}

    async def look(post):
        looking.set(); await looked.wait()
        return post, {('attachment', 0): 'a sleeping cat'}

    async def chime(cid):
        result = await old_chime(cid)
        decision_done.set()
        return result

    bot.ollama_chat, bot.look_at, bot.chimes_in = fake, look, chime
    first = asyncio.create_task(bot.on_message(first_post))
    await wait(first_post.reacting)
    picture = Post(ch, SOL, 'gomi what is in this picture?', image=True)
    second = asyncio.create_task(bot.on_message(picture))
    await wait(looking)
    first_post.reacted.set()
    await wait(decision_done)
    premature = any('format' not in call for call in calls)
    looked.set()
    await asyncio.gather(first, second)
    bot.look_at, bot.chimes_in = old_look, old_chime
    bot.VISION = False; bot.CHIME_IN_THRESHOLD = 0
    assert not premature, 'generated before vision completed after reaction await'
    replies = [call for call in calls if 'format' not in call]
    assert len(replies) == len(ch.sent) == 1
    assert '[image: a sleeping cat]' in replies[0]['messages'][1]['content']


async def short_correction():
    ch = Channel(); calls, started, release = model(['Chess it is.', '{"interest": 0, "react": 0, "emoji": "none"}'])
    first = asyncio.create_task(bot.on_message(Post(ch, MIRA, 'we could play chess after dinner')))
    await wait(started)
    await bot.on_message(Post(ch, SOL, 'nevermind'))
    release.set(); await first
    assert not ch.sent, 'short reaction-only correction did not invalidate unsolicited draft'


async def slow_image():
    ch = Channel(); calls, started, release = model(['Chess it is.', '{"interest": 0, "react": 0, "emoji": "none"}'])
    looking, looked = asyncio.Event(), asyncio.Event()
    old_look = bot.look_at

    async def look(post):
        looking.set(); await looked.wait()
        return post, {('attachment', 0): 'a sleeping cat'}

    bot.VISION = True; bot.look_at = look
    first = asyncio.create_task(bot.on_message(Post(ch, MIRA, 'we could play chess after dinner')))
    await wait(started)
    second = asyncio.create_task(bot.on_message(Post(ch, SOL, '', image=True)))
    await wait(looking)
    release.set(); await first
    stale_sent = list(ch.sent)
    looked.set(); await second
    bot.VISION = False; bot.look_at = old_look
    assert not stale_sent and not ch.sent, 'draft sent while newer image was awaiting vision'


async def pending_shape():
    ch = Channel()
    answer = 'Two plus two equals four. Three plus three equals six. Four plus four equals eight.'
    calls, started, release = model(['Hello there.', answer])
    first = asyncio.create_task(bot.on_message(Post(ch, SOL, 'gomi hi')))
    await wait(started)
    questions = [Post(ch, MIRA, text) for text in ('gomi what is two plus two?', 'gomi what is three plus three?',
                                                 'gomi what is four plus four?')]
    for question in questions:
        await bot.on_message(question)
    await bot.on_message(Post(ch, SOL, 'pizza just arrived'))
    release.set(); await first
    assert ch.sent == ['Hello there.', answer], 'pending answer clipped by unrelated quick-chatter shape'
    sent = [e for e in bot.chat_log.read(ch.id) if e['author'] == 'Gomihyu']
    assert sent[-1]['answered_requests'] == [q.id for q in questions]


async def pending_pings():
    ch = Channel()
    bot.handles['rex'] = 5
    calls, started, release = model(['Hello there.', '@Mira, four. @Sol, six. Ask @Rex about the next round.'])
    first = asyncio.create_task(bot.on_message(Post(ch, SOL, 'gomi hello')))
    await wait(started)
    await bot.on_message(Post(ch, MIRA, 'gomi what is two plus two?'))
    await bot.on_message(Post(ch, SOL, 'gomi what is three plus three?'))
    release.set(); await first
    assert len(calls) == 2 and ch.sent[-1] == 'four. Sol, six. Ask <@5> about the next round.', ch.sent


async def failure(answer, delivery=False):
    ch = Channel(fail=delivery)
    calls, started, release = model([answer])
    question = Post(ch, MIRA, 'gomi what is six times seven?')
    task = asyncio.create_task(bot.on_message(question))
    await wait(started)
    assert [p.id for _, _, p in bot.unanswered[ch.id]] == [question.id], 'request consumed before generation'
    release.set(); await task
    assert len(calls) == 1 and ch.attempts == int(delivery)
    assert not ch.sent and not bot.unanswered[ch.id]
    entries = bot.chat_log.read(ch.id, reactions=True)
    assert not any(e['author'] == 'Gomihyu' and e.get('kind', 'message') == 'message' for e in entries)
    failures = [e for e in entries if e.get('kind') == 'reply_failure']
    assert len(failures) == 1 and failures[0]['request_ids'] == [question.id]
    assert failures[0]['reason'] == ('delivery' if delivery else 'generation')


async def bounded_batches():
    ch = Channel()
    answer = 'First result is four. Second result is six. Third result is eight.'
    calls, started, release = model(['Hello there.', answer, 'Five and five make ten.'])
    hello = Post(ch, SOL, 'gomi hello')
    first = asyncio.create_task(bot.on_message(hello))
    await wait(started)
    questions = [Post(ch, MIRA, f'gomi what is {i} plus {i}?') for i in range(2, 6)]
    for question in questions:
        await bot.on_message(question)
    release.set(); await first
    assert ch.sent == ['Hello there.', answer, 'Five and five make ten.']
    entries = [e for e in bot.chat_log.read(ch.id) if e['author'] == 'Gomihyu']
    assert entries[1]['answered_requests'] == [q.id for q in questions[:3]]
    assert entries[2]['answered_requests'] == [questions[3].id] and not bot.unanswered[ch.id]
    # A canned answer alone cannot detect a prompt which asks her to answer her own prior result.
    for call, batch, newest in reversed(list(zip(calls, [[hello], questions[:3], questions[3:]],
                                                 [hello, questions[-1], questions[-1]]))):
        instruction = call['messages'][1]['content'].split('Above is the recent chat log', 1)[1]
        sources = '\n'.join(f'{post.author.name}: {post.content}' for post in batch)
        assert f'The newest message, from {newest.author.name}:\n{newest.author.name}: {newest.content}\n' in instruction
        assert f'These messages still need your reply:\n{sources}\n' in instruction, instruction
        assert 'You are replying to the newest message' not in instruction
        assert 'respond to that directly' not in instruction, instruction
        assert 'Answer the selected requests above' in instruction
        assert '\nGomihyu:' not in instruction, instruction


async def pending_speakers_after_eviction():
    ch = Channel()
    bot.memory.remember(MIRA.id, MIRA.name, 'My synthetic board size is nine')
    bot.memory.remember(SOL.id, SOL.name, 'My synthetic board size is nineteen')
    bot.memory.set_nickname(SOL.id, SOL.name, 'Solar')
    bot.memory.learn(MIRA.id, MIRA.name, 'Mira tried synthetic chess', '2026-11-14')
    bot.memory.learn(SOL.id, SOL.name, 'Sol tried synthetic shogi', '2026-11-14')
    calls, started, release = model(['Hello there.', 'Mira chose nine. Sol chose nineteen. Mira tried chess.',
                                      'Sol tried shogi.'])
    hello = Post(ch, SOL, 'gomi hello')
    first = asyncio.create_task(bot.on_message(hello)); await wait(started)
    questions = [Post(ch, author, text) for author, text in [
        (MIRA, 'gomi what board size did I ask you to remember?'),
        (SOL, 'gomi what board size did I ask you to remember?'),
        (MIRA, 'gomi what did I try before?'),
        (SOL, 'gomi what did I try before?')]]
    for question in questions:
        await bot.on_message(question)
    # A display-name alias can overwrite a handle lookup; pending requests still know author IDs.
    bot.handles[MIRA.name.lower()] = SOL.id
    # Other-bot context can evict every request and become the newest observed source.
    doumi = NS(id=4, name='Doumi', display_name='Doumi', bot=True)
    for i in range(bot.HISTORY_LENGTH + 1):
        await bot.on_message(Post(ch, doumi, f'synthetic context {i}'))
    release.set(); await first
    assert len(ch.sent) == len(calls) == 3 and not bot.unanswered[ch.id]
    for call, batch in zip(calls[1:], [questions[:3], questions[3:]]):
        prompt = call['messages'][1]['content']
        instruction = prompt.split('Above is the recent chat log', 1)[1]
        assert 'The newest message, from Doumi (bot):\nDoumi (bot): synthetic context' in instruction
        assert 'directly mentioned/addressed' not in instruction
        assert 'You are replying to the newest message' not in instruction
        assert 'These messages still need your reply:\n' + '\n'.join(
            f'{post.author.name}: {post.content}' for post in batch) + '\n' in instruction
        if any(post.author is MIRA for post in batch):
            assert 'Mira: Asked you to remember: "My synthetic board size is nine"' in prompt
            assert 'Mira: Past observation (may be out of date): Mira tried synthetic chess' in prompt
        else:
            assert 'Mira: Asked you to remember:' not in prompt
        assert 'Sol: Asked you to remember: "My synthetic board size is nineteen"' in prompt
        assert 'Sol is Solar' in prompt and 'Mira is Solar' not in prompt
        assert 'Mira: Asked you to remember: "My synthetic board size is nineteen"' not in prompt
        assert 'Sol: Asked you to remember: "My synthetic board size is nine"' not in prompt
        assert 'Sol: Past observation (may be out of date): Sol tried synthetic shogi' in prompt
    entries = [e for e in bot.chat_log.read(ch.id) if e['author'] == 'Gomihyu']
    assert [e['answered_requests'] for e in entries] == [[hello.id], [p.id for p in questions[:3]], [questions[-1].id]]


async def failure_during_burst():
    ch = Channel(); calls, started, release = model([None, 'The newer result is eight.'])
    original = Post(ch, MIRA, 'gomi what is three plus three?')
    first = asyncio.create_task(bot.on_message(original))
    await wait(started)
    newer = Post(ch, SOL, 'gomi what is four plus four?')
    await bot.on_message(newer)
    release.set(); await first
    assert len(calls) == 2 and ch.sent == ['The newer result is eight.'] and not bot.unanswered[ch.id]
    entries = bot.chat_log.read(ch.id, reactions=True)
    assert [e['request_ids'] for e in entries if e.get('kind') == 'reply_failure'] == [[original.id]]
    assert [e['answered_requests'] for e in entries if e['author'] == 'Gomihyu'
            and e.get('kind', 'message') == 'message'] == [[newer.id]]


async def ambiguous_delivery():
    ch = Channel(fail='timeout')
    calls, _, release = model(['Forty two is the answer.']); release.set()
    question = Post(ch, MIRA, 'gomi what is six times seven?')
    await bot.on_message(question)
    assert ch.attempts == 1 and len(ch.sent) == 1 and not bot.unanswered[ch.id]
    # A later post cannot cause an automatic resend of the uncertain delivery.
    calls, _, release = model(['{"interest": 0, "react": 0, "emoji": "none"}']); release.set()
    await bot.on_message(Post(ch, SOL, 'ok'))
    assert ch.attempts == 1
    entries = bot.chat_log.read(ch.id, reactions=True)
    assert [e['request_ids'] for e in entries if e.get('kind') == 'reply_failure'] == [[question.id]]
    assert not any(e['author'] == 'Gomihyu' and e.get('kind', 'message') == 'message' for e in entries)


async def filtered_answer():
    ch = Channel()
    calls, _, release = model(['The answer is forty two. Ask @UnknownPerson for the other answer.'] * 2)
    release.set()
    question = Post(ch, MIRA, 'gomi answer both parts?')
    await bot.on_message(question)
    assert len(calls) == 2 and ch.sent == ['The answer is forty two.']
    entries = bot.chat_log.read(ch.id, reactions=True)
    assert [e['request_ids'] for e in entries if e.get('kind') == 'reply_failure'] == [[question.id]]
    assert [e['answered_requests'] for e in entries if e.get('kind', 'message') == 'message'
            and e['author'] == 'Gomihyu'] == [[]]
    assert [e['about'] for e in entries if e.get('kind', 'message') == 'message'
            and e['author'] == 'Gomihyu'] == ['filtered']


async def persistence_failure():
    original_add = bot.chat_log.add

    def disk_full(*args, **kwargs):
        if args[4] == 'Gomihyu':
            raise OSError('synthetic disk full')
        return original_add(*args, **kwargs)

    bot.chat_log.add = disk_full
    try:
        for answer in ('Forty two is the answer.', None):
            ch = Channel(); calls, _, release = model([answer]); release.set()
            await bot.on_message(Post(ch, MIRA, 'gomi what is six times seven?'))
            assert not bot.unanswered[ch.id] and ch.attempts == int(answer is not None)
            calls, _, release = model(['{"interest": 0, "react": 0, "emoji": "none"}']); release.set()
            await bot.on_message(Post(ch, SOL, 'ok'))
            assert ch.attempts == int(answer is not None), 'log persistence failure caused duplicate delivery'
    finally:
        bot.chat_log.add = original_add


async def intake_persistence_failure():
    original_add, original_enrich, original_look = bot.chat_log.add, bot.chat_log.enrich, bot.look_at

    def disk_full(*args, **kwargs):
        raise OSError('synthetic intake disk full')

    async def look(post):
        return post, {('attachment', 0): 'a red kite'}

    try:
        for failing in ('observation', 'description'):
            ch = Channel()
            bot.VISION = True; bot.look_at = look
            bot.chat_log.add = disk_full if failing == 'observation' else original_add
            bot.chat_log.enrich = disk_full if failing == 'description' else original_enrich
            calls, _, release = model(['The picture shows a red kite.']); release.set()
            question = Post(ch, MIRA, 'gomi what is this?', image=True)
            await bot.on_message(question)
            assert ch.sent == ['The picture shows a red kite.'] and not bot.unanswered[ch.id]
            assert '[image: a red kite]' in calls[0]['messages'][1]['content']
    finally:
        bot.chat_log.add, bot.chat_log.enrich, bot.look_at = original_add, original_enrich, original_look
        bot.VISION = False


async def mute_pending(during):
    ch = Channel()
    original_look = bot.look_at
    started, release = asyncio.Event(), asyncio.Event()
    bot.owner_ids.add(SOL.id)
    calls, generation_started, generation_release = model(['The answer is four.'])

    async def look(post):
        started.set(); await release.wait()
        return post, {('attachment', 0): 'a red kite'}

    try:
        bot.VISION = during == 'vision'
        bot.look_at = look
        first_question = Post(ch, MIRA, 'gomi what is two plus two?', image=bot.VISION)
        first = asyncio.create_task(bot.on_message(first_question))
        await wait(started if bot.VISION else generation_started)
        second_question = Post(ch, MIRA, 'gomi what is three plus three?')
        second = asyncio.create_task(bot.on_message(second_question))
        await asyncio.sleep(0)
        await bot.on_message(Post(ch, SOL, 'gomi mute'))
        assert not bot.unanswered[ch.id], 'mute left queued required requests alive'
        # Even a quick unmute must not revive a cancelled generation or vision wait.
        await bot.on_message(Post(ch, SOL, 'gomi unmute'))
        release.set(); generation_release.set()
        await asyncio.gather(first, second)
        assert not ch.sent and len(calls) == int(during == 'generation')
        failures = [e for e in bot.chat_log.read(ch.id, reactions=True) if e.get('kind') == 'reply_failure']
        assert len(failures) == 1 and failures[0]['reason'] == 'muted'
        assert failures[0]['request_ids'] == [first_question.id, second_question.id]
        bot.CHIME_IN_THRESHOLD = 8
        calls, _, ready = model(['{"interest": 0, "react": 0, "emoji": "none"}']); ready.set()
        await bot.on_message(Post(ch, MIRA, 'my pizza arrived and it smells good'))
        assert len(calls) == 1 and 'format' in calls[0] and not ch.sent
    finally:
        bot.VISION = False; bot.CHIME_IN_THRESHOLD = 0; bot.look_at = original_look
        bot.owner_ids.discard(SOL.id)


async def main():
    failures = []
    for name, run in [('reaction vision', reaction_vision), ('short correction', short_correction),
                      ('slow image', slow_image), ('pending shape', pending_shape), ('pending pings', pending_pings),
                      ('failed generation', lambda: failure(None)), ('empty generation', lambda: failure('')),
                      ('failed delivery', lambda: failure('Forty two is the answer.', True)),
                      ('clipped answer', lambda: failure('First full answer. Second full answer. Third full answer. Fourth full answer.')),
                      ('token cap', lambda: failure({'message': {'content': 'The answer is forty'}, 'done_reason': 'length'})),
                      ('ambiguous delivery', ambiguous_delivery), ('filtered answer', filtered_answer),
                      ('bounded batches', bounded_batches), ('pending speakers after eviction', pending_speakers_after_eviction),
                      ('failure during burst', failure_during_burst),
                      ('persistence failure', persistence_failure), ('intake persistence failure', intake_persistence_failure),
                      ('mute pending generation', lambda: mute_pending('generation')),
                      ('mute pending vision', lambda: mute_pending('vision'))]:
        try:
            await run()
        except AssertionError as error:
            failures.append(f'{name}: {error}')
    assert not failures, '\n'.join(failures)
    print('CONVERSATION RACE TESTS PASSED')


asyncio.run(main())
