"""Big Lebowski quotes module for alembic migration helper."""

import random

QUOTES = [
    '"The Dude abides." — The Dude',
    '"Yeah, well, you know, that\'s just, like, your opinion, man." — The Dude',
    '"This rug really tied the room together." — The Dude',
    '"Careful, man, there\'s a beverage here!" — The Dude',
    '"Shut up, Donny, you\'re out of your element!" — Walter Sobchak',
    '"I\'m the Dude. So that\'s what you call me. That or His Dudeness, or Duder, or El Duderino..." — The Dude',
    '"This is a very complicated case, Maude. You know, a lotta ins, a lotta outs, a lotta what-have-yous." — The Dude',
    '"Obviously you\'re not a golfer." — The Dude',
    '"Mark it zero, Dude. Next frame." — Walter Sobchak',
    '"Nobody messes with the Jesus." — Jesus Quintana',
    '"Hey, nice marmot." — The Dude',
    '"Sometimes you eat the bear, and sometimes, well, he eats you." — The Stranger',
    '"You\'re entering a world of pain." — Walter Sobchak',
    '"I don\'t roll on Shabbos!" — Walter Sobchak',
    '"Strikes and gutters, ups and downs." — The Dude',
]


def get_random_quote() -> str:
    """Return a randomly selected Big Lebowski quote."""
    return random.choice(QUOTES)


if __name__ == "__main__":
    print(get_random_quote())
