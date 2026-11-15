"""Words for fingerprints and one-time codes: 256 short, distinct, easy-to-say words, so each word is one byte."""

from __future__ import annotations

import hashlib
import secrets

WORDS = """
able acid acre aged aide alarm album alert alley amber angle ankle apple april apron arch arena armor arrow atlas
attic audio aunt avid award axis bacon badge bagel baker bamboo banjo barn basil basin beach beacon bean bench
berry bike birch bison blade blank blaze bloom board boat bonus boot brain brass bread brick brook brush bubble
cabin cable cactus camel candle canoe canvas cargo carpet cedar chalk charm chess chief cider cliff clock cloud
clover coast cobalt cocoa comet coral cotton crane crater crisp crown cube curve daisy dance delta denim desert
diary dingo dodge dolphin dome donut dragon drift drum dune eagle easel echo eclipse elbow elder ember engine
equal ethos fable falcon fern ferry fiber field fig flame flint flute focus forest fossil fox frost fruit galaxy
garden garlic gecko gem ginger glacier globe glove goose grain granite grape gravel guitar gull habit hammer harbor
hazel heart hedge helmet heron hill honey hook horizon hub igloo index ink iris island ivory jacket jade jaguar
jazz jelly jewel judge juice kayak kettle kiwi koala ladder lagoon lake lamp lantern lark lava lemon lens lilac
lime linen lion lotus lunar lynx magnet mango maple marble meadow melon mesa meteor mint mirror moss motor
mural nectar needle nest nickel noble north novel nutmeg oak oasis ocean olive onyx opal orbit orchid otter owl
oyster paddle palm panda paper parrot pasta peach pearl pebble pepper piano pilot pine planet plum polar pony
poppy prism pulse quartz quest quill rabbit radar raven reef ridge river robin rocket
""".split()
assert len(WORDS) == 256 and len(set(WORDS)) == 256, len(WORDS)


def fingerprint(data: bytes, n: int = 6) -> str:
    """n words from sha256(data): what both people read out to check a join code was not swapped."""
    d = hashlib.sha256(b"knos.fingerprint" + data).digest()
    return "-".join(WORDS[b] for b in d[:n])


def one_time_code(n: int = 6) -> str:
    return "-".join(WORDS[b] for b in secrets.token_bytes(n))
