from .models import Room, Player, create_deck, card_key


def start_game(room):
    room.deck = create_deck()
    room.discard_pile = []
    room.current_turn_index = 0
    room.state = 'playing'
    
    for player in room.players.all().order_by('position'):
        for i in range(4):
            card = room.deck.pop()
            player.set_carrot(i, card)
        
        player.set_visible(2, True)
        player.set_visible(3, True)
        player.hand = []
        player.has_claimed_cooked = False
        player.save()
    
    room.save()
    return room


def draw_from_deck(player):
    room = player.room
    if room.state != 'playing':
        return None, "Game is not in progress"
    
    if room.players.all().order_by('position')[room.current_turn_index].id != player.id:
        return None, "Not your turn"
    
    if len(player.hand) > 0:
        return None, "You already have a card in hand"
    
    card, reshuffled = room.draw_from_deck()
    if card is None:
        return None, "No cards left to draw"
    
    player.hand = [card]
    player.save()
    if reshuffled:
        room.save()
    
    return card, None


def draw_from_discard(player):
    room = player.room
    if room.state != 'playing':
        return None, "Game is not in progress"
    
    if room.players.all().order_by('position')[room.current_turn_index].id != player.id:
        return None, "Not your turn"
    
    if len(player.hand) > 0:
        return None, "You already have a card in hand"
    
    if not room.discard_pile:
        return None, "Discard pile is empty"
    
    card = room.discard_pile.pop()
    player.hand = [card]
    player.save()
    room.save()
    
    return card, None


def discard_from_hand(player, hand_card_index=0):
    room = player.room
    if room.state != 'playing':
        return None, "Game is not in progress"
    
    if room.players.all().order_by('position')[room.current_turn_index].id != player.id:
        return None, "Not your turn"
    
    if len(player.hand) == 0:
        return None, "No card in hand to discard"
    
    if hand_card_index < 0 or hand_card_index >= len(player.hand):
        hand_card_index = 0
    
    card = player.hand.pop(hand_card_index)
    room.discard_pile.append(card)
    player.save()
    room.save()
    
    return card, None


def replace_carrot(player, hand_card_index, carrot_index):
    room = player.room
    if room.state != 'playing':
        return None, "Game is not in progress"
    
    if room.players.all().order_by('position')[room.current_turn_index].id != player.id:
        return None, "Not your turn"
    
    if len(player.hand) == 0:
        return None, "No card in hand"
    
    if carrot_index < 0 or carrot_index > 3:
        return None, "Invalid carrot index"
    
    if hand_card_index < 0 or hand_card_index >= len(player.hand):
        return None, "Invalid hand card index"
    
    new_card = player.hand.pop(hand_card_index)
    old_card = player.get_carrot(carrot_index)
    player.set_carrot(carrot_index, new_card)
    room.discard_pile.append(old_card)
    player.save()
    room.save()
    
    return new_card, old_card, None


def claim_cooked(player):
    room = player.room
    if room.state != 'playing':
        return False, "Game is not in progress"
    
    if room.players.all().order_by('position')[room.current_turn_index].id != player.id:
        return False, "Not your turn"
    
    if player.has_claimed_cooked:
        return False, "Already claimed cooked"
    
    player.has_claimed_cooked = True
    player.save()
    
    return True, None


def get_next_turn(room):
    players = list(room.players.all().order_by('position'))
    if not players:
        return
    
    current_player = players[room.current_turn_index]
    if current_player.has_claimed_cooked:
        room.state = 'finished'
        room.save()
        return
    
    room.current_turn_index = (room.current_turn_index + 1) % len(players)
    room.save()


def use_power_seven(player, target_carrot_index):
    room = player.room
    if room.state != 'playing':
        return None, "Game is not in progress"
    
    if target_carrot_index < 0 or target_carrot_index > 3:
        return None, "Invalid carrot index"
    
    carrot = player.get_carrot(target_carrot_index)
    player.set_visible(target_carrot_index, True)
    player.save()
    
    return carrot, None


def use_power_eight(player, target_player_id, target_carrot_index):
    room = player.room
    if room.state != 'playing':
        return None, "Game is not in progress"
    
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
    room = player.room
    if room.state != 'playing':
        return False, "Game is not in progress"
    
    try:
        player1 = Player.objects.get(id=carrot1_player_id, room=room)
        player2 = Player.objects.get(id=carrot2_player_id, room=room)
    except Player.DoesNotExist:
        return False, "Player not found"
    
    if carrot1_index < 0 or carrot1_index > 3 or carrot2_index < 0 or carrot2_index > 3:
        return False, "Invalid carrot index"
    
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
        room.discard_pile.append(carrot)
        room.save()
        return True, None
    else:
        penalty1, _ = room.draw_from_deck()
        penalty2, _ = room.draw_from_deck()
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
