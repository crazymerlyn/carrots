import uuid
import random
import string
from django.db import models


def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


SUITS = ['hearts', 'diamonds', 'clubs', 'spades']
VALUES = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']


def create_deck():
    deck = []
    for suit in SUITS:
        for value in VALUES:
            deck.append({'suit': suit, 'value': value})
    random.shuffle(deck)
    return deck


def card_score(card):
    value = card['value']
    suit = card['suit']
    
    if value in ['J', 'Q']:
        return 10
    if value == 'K':
        if suit in ['hearts', 'diamonds']:
            return -1
        return 10
    if value == 'A':
        return 1
    return int(value)


def card_key(card):
    return f"{card['value']}_of_{card['suit']}"


class Room(models.Model):
    code = models.CharField(max_length=6, unique=True, default=generate_room_code)
    state = models.CharField(
        max_length=20,
        choices=[
            ('waiting', 'Waiting for players'),
            ('playing', 'Game in progress'),
            ('finished', 'Game over'),
        ],
        default='waiting'
    )
    deck = models.JSONField(default=list)
    discard_pile = models.JSONField(default=list)
    current_turn_index = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        if not self.code:
            self.code = generate_room_code()
        super().save(*args, **kwargs)
    
    def get_top_discard(self):
        if self.discard_pile:
            return self.discard_pile[-1]
        return None
    
    def draw_from_deck(self):
        if not self.deck:
            if len(self.discard_pile) > 1:
                top = self.discard_pile.pop()
                self.deck = self.discard_pile[:]
                self.deck.reverse()
                self.discard_pile = [top]
                random.shuffle(self.deck)
            else:
                return None
        return self.deck.pop()
    
    def __str__(self):
        return f"Room {self.code} ({self.state})"


class Player(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='players')
    name = models.CharField(max_length=50)
    position = models.IntegerField()
    
    carrot_0 = models.JSONField(null=True, blank=True)
    carrot_1 = models.JSONField(null=True, blank=True)
    carrot_2 = models.JSONField(null=True, blank=True)
    carrot_3 = models.JSONField(null=True, blank=True)
    
    visible_0 = models.BooleanField(default=False)
    visible_1 = models.BooleanField(default=False)
    visible_2 = models.BooleanField(default=False)
    visible_3 = models.BooleanField(default=False)
    
    hand = models.JSONField(default=list)
    is_ready = models.BooleanField(default=False)
    has_claimed_cooked = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ['room', 'position']
    
    def get_carrot(self, index):
        return getattr(self, f'carrot_{index}')
    
    def set_carrot(self, index, card):
        setattr(self, f'carrot_{index}', card)
    
    def get_visible(self, index):
        return getattr(self, f'visible_{index}')
    
    def set_visible(self, index, visible):
        setattr(self, f'visible_{index}', visible)
    
    def calculate_score(self):
        score = 0
        for i in range(4):
            carrot = self.get_carrot(i)
            if carrot:
                score += card_score(carrot)
        for card in self.hand:
            score += card_score(card)
        return score
    
    def __str__(self):
        return f"{self.name} in Room {self.room.code}"
