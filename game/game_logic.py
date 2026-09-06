import random
from .models import Room, Player, create_deck, card_key


def _require_turn(player):
    """Returns (room, current_player, error_string).
    If error_string is not None, the check failed."""
    room = player.room
    if room.state != 'playing':
        return None, None, "Game is not in progress"
    current = room.players.all().order_by('position')[room.current_turn_index]
    if current.id != player.id:
        return None, None, "Not your turn"
    return room, current, None


def draw_from_deck_pile(room):
    """Draw a card from the room's deck. Reshuffles discard pile if empty.
    Returns (card, reshuffled)."""
    reshuffled = False
    if not room.deck:
        if len(room.discard_pile) > 1:
            top = room.discard_pile.pop()
            room.deck = room.discard_pile[:]
            room.deck.reverse()
            room.discard_pile = [top]
            random.shuffle(room.deck)
            reshuffled = True
        else:
            return None, False
    deck = room.deck[:]
    card = deck.pop()
    room.deck = deck
    return card, reshuffled


def start_game(room):
    deck = create_deck()
    room.discard_pile = []
    room.current_turn_index = 0
    room.state = 'playing'

    for player in room.players.all().order_by('position'):
        for i in range(4):
            card = deck.pop()
            player.set_carrot(i, card)

        player.set_visible(2, True)
        player.set_visible(3, True)
        player.hand = []
        player.has_claimed_cooked = False
        player.save()

    room.deck = deck
    room.save()
    return room


def draw_from_deck(player):
    room, current, err = _require_turn(player)
    if err:
        return None, err

    if len(player.hand) > 0:
        return None, "You already have a card in hand"

    card, reshuffled = draw_from_deck_pile(room)
    if card is None:
        return None, "No cards left to draw"

    player.hand = [card]
    player.save()
    room.save()

    return card, None


def draw_from_discard(player):
    room, current, err = _require_turn(player)
    if err:
        return None, err

    if len(player.hand) > 0:
        return None, "You already have a card in hand"

    if not room.discard_pile:
        return None, "Discard pile is empty"

    discard_pile = room.discard_pile[:]
    card = discard_pile.pop()
    room.discard_pile = discard_pile
    player.hand = [card]
    player.save()
    room.save()

    return card, None


def discard_from_hand(player, hand_card_index=0):
    room, current, err = _require_turn(player)
    if err:
        return None, err

    if len(player.hand) == 0:
        return None, "No card in hand to discard"

    if hand_card_index < 0 or hand_card_index >= len(player.hand):
        hand_card_index = 0

    card = player.hand.pop(hand_card_index)
    discard_pile = room.discard_pile[:]
    discard_pile.append(card)
    room.discard_pile = discard_pile
    player.save()
    room.save()

    return card, None


def replace_carrot(player, hand_card_index, carrot_index):
    room, current, err = _require_turn(player)
    if err:
        return None, err

    if len(player.hand) == 0:
        return None, "No card in hand"

    if carrot_index < 0 or carrot_index > 3:
        return None, "Invalid carrot index"

    if hand_card_index < 0 or hand_card_index >= len(player.hand):
        return None, "Invalid hand card index"

    new_card = player.hand.pop(hand_card_index)
    old_card = player.get_carrot(carrot_index)
    player.set_carrot(carrot_index, new_card)
    discard_pile = room.discard_pile[:]
    discard_pile.append(old_card)
    room.discard_pile = discard_pile
    player.save()
    room.save()

    return {'new_card': new_card, 'old_card': old_card}, None


def claim_cooked(player):
    room, current, err = _require_turn(player)
    if err:
        return False, err

    if player.has_claimed_cooked:
        return False, "Already claimed cooked"

    player.has_claimed_cooked = True
    player.save()

    return True, None


def get_next_turn(room):
    players = list(room.players.all().order_by('position'))
    if not players:
        return

    room.current_turn_index = (room.current_turn_index + 1) % len(players)
    next_player = players[room.current_turn_index]
    if next_player.has_claimed_cooked:
        room.state = 'finished'
        room.save()
        return

    room.save()


def use_power_seven(player, target_carrot_index):
    room, current, err = _require_turn(player)
    if err:
        return None, err

    if target_carrot_index < 0 or target_carrot_index > 3:
        return None, "Invalid carrot index"

    carrot = player.get_carrot(target_carrot_index)
    player.set_visible(target_carrot_index, True)
    player.save()

    return carrot, None


def use_power_eight(player, target_player_id, target_carrot_index):
    room, current, err = _require_turn(player)
    if err:
        return None, err

    try:
        target_player = Player.objects.get(id=target_player_id, room=room)
    except Player.DoesNotExist:
        return None, "Target player not found"

    if target_player.id == player.id:
        return None, "Cannot target yourself with 8"

    if target_carrot_index < 0 or target_carrot_index > 3:
        return None, "Invalid carrot index"

    carrot = target_player.get_carrot(target_carrot_index)
    return carrot, None


def use_power_nine(player, carrot1_player_id, carrot1_index, carrot2_player_id, carrot2_index):
    room, current, err = _require_turn(player)
    if err:
        return False, err

    if carrot1_index < 0 or carrot1_index > 3 or carrot2_index < 0 or carrot2_index > 3:
        return False, "Invalid carrot index"

    if carrot1_player_id == carrot2_player_id:
        target = Player.objects.get(id=carrot1_player_id, room=room)
        card1 = target.get_carrot(carrot1_index)
        card2 = target.get_carrot(carrot2_index)
        target.set_carrot(carrot1_index, card2)
        target.set_carrot(carrot2_index, card1)
        target.set_visible(carrot1_index, False)
        target.set_visible(carrot2_index, False)
        target.save()
    else:
        try:
            player1 = Player.objects.get(id=carrot1_player_id, room=room)
            player2 = Player.objects.get(id=carrot2_player_id, room=room)
        except Player.DoesNotExist:
            return False, "Player not found"

        card1 = player1.get_carrot(carrot1_index)
        card2 = player2.get_carrot(carrot2_index)

        player1.set_carrot(carrot1_index, card2)
        player2.set_carrot(carrot2_index, card1)

        player1.set_visible(carrot1_index, False)
        player2.set_visible(carrot2_index, False)

        player1.save()
        player2.save()

    return True, None


def try_match_carrot(player, target_player_id, carrot_index):
    room = player.room
    if room.state != 'playing':
        return None, "Game is not in progress"

    top_discard = room.get_top_discard()
    if top_discard is None:
        return None, "No card on discard pile"

    try:
        target_player = Player.objects.get(id=target_player_id, room=room)
    except Player.DoesNotExist:
        return None, "Target player not found"

    if carrot_index < 0 or carrot_index > 3:
        return None, "Invalid carrot index"

    carrot = target_player.get_carrot(carrot_index)
    if carrot is None:
        return None, "No carrot at that position"

    if card_key(carrot) == card_key(top_discard):
        target_player.set_carrot(carrot_index, None)
        target_player.save()
        discard_pile = room.discard_pile[:]
        discard_pile.append(carrot)
        room.discard_pile = discard_pile
        room.save()
        return True, None
    else:
        penalty1, _ = draw_from_deck_pile(room)
        penalty2, _ = draw_from_deck_pile(room)
        if penalty1:
            player.hand.append(penalty1)
        if penalty2:
            player.hand.append(penalty2)
        player.save()
        room.save()
        return False, None


def calculate_scores(room):
    scores = []
    for player in room.players.all().order_by('position'):
        scores.append({
            'player_id': player.id,
            'name': player.name,
            'score': player.calculate_score()
        })
    scores.sort(key=lambda x: x['score'])
    return scores
