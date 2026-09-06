import json
from django.test import TestCase, Client
from .models import Room, Player, create_deck, card_score, card_key, SUITS, VALUES
from . import game_logic


def make_card(value, suit='hearts'):
    return {'value': value, 'suit': suit}


def create_started_game(num_players=2):
    """Helper: create a room with N players, start the game, return (room, players).
    Uses a deterministic deck (not shuffled) for predictable tests."""
    room = Room.objects.create()
    room.deck = [make_card(v, s) for s in SUITS for v in VALUES]
    room.save()
    players = []
    for i in range(num_players):
        p = Player.objects.create(room=room, name=f'P{i}', position=i)
        players.append(p)
    game_logic.start_game(room)
    room.refresh_from_db()
    for p in players:
        p.refresh_from_db()
    return room, players


# ---------------------------------------------------------------------------
# Pure unit tests — no DB required
# ---------------------------------------------------------------------------
class TestCardFunctions(TestCase):

    def test_card_score_number_cards(self):
        for v in ['2', '3', '4', '5', '6', '7', '8', '9', '10']:
            self.assertEqual(card_score(make_card(v)), int(v))

    def test_card_score_jack_and_queen(self):
        self.assertEqual(card_score(make_card('J')), 10)
        self.assertEqual(card_score(make_card('Q')), 10)

    def test_card_score_king_black(self):
        self.assertEqual(card_score(make_card('K', 'spades')), 10)
        self.assertEqual(card_score(make_card('K', 'clubs')), 10)

    def test_card_score_king_red(self):
        self.assertEqual(card_score(make_card('K', 'hearts')), -1)
        self.assertEqual(card_score(make_card('K', 'diamonds')), -1)

    def test_card_score_ace(self):
        self.assertEqual(card_score(make_card('A')), 1)

    def test_card_key_format(self):
        self.assertEqual(card_key(make_card('7', 'hearts')), '7_of_hearts')
        self.assertEqual(card_key(make_card('K', 'spades')), 'K_of_spades')

    def test_create_deck_52_cards(self):
        deck = create_deck()
        self.assertEqual(len(deck), 52)

    def test_create_deck_all_suits_and_values(self):
        deck = create_deck()
        suits_in_deck = {c['suit'] for c in deck}
        values_in_deck = {c['value'] for c in deck}
        self.assertEqual(suits_in_deck, set(SUITS))
        self.assertEqual(values_in_deck, set(VALUES))

    def test_create_deck_no_duplicates(self):
        deck = create_deck()
        keys = [card_key(c) for c in deck]
        self.assertEqual(len(keys), len(set(keys)))


# ---------------------------------------------------------------------------
# Game logic integration tests
# ---------------------------------------------------------------------------
class TestStartGame(TestCase):

    def test_deals_4_cards_per_player(self):
        room, players = create_started_game(2)
        for p in players:
            for i in range(4):
                self.assertIsNotNone(p.get_carrot(i))

    def test_visible_cards_2_and_3(self):
        room, players = create_started_game(2)
        for p in players:
            self.assertFalse(p.get_visible(0))
            self.assertFalse(p.get_visible(1))
            self.assertTrue(p.get_visible(2))
            self.assertTrue(p.get_visible(3))

    def test_hand_is_empty(self):
        room, players = create_started_game(2)
        for p in players:
            self.assertEqual(p.hand, [])

    def test_deck_size(self):
        room, players = create_started_game(3)
        # 52 - 4*3 = 40
        self.assertEqual(len(room.deck), 40)

    def test_discard_pile_empty(self):
        room, players = create_started_game(2)
        self.assertEqual(room.discard_pile, [])

    def test_room_state_playing(self):
        room, players = create_started_game(2)
        self.assertEqual(room.state, 'playing')

    def test_turn_starts_at_0(self):
        room, players = create_started_game(2)
        self.assertEqual(room.current_turn_index, 0)


class TestDrawFromDeck(TestCase):

    def setUp(self):
        self.room, self.players = create_started_game(2)
        self.p0 = self.players[0]

    def test_draw_card_goes_to_hand(self):
        card, err = game_logic.draw_from_deck(self.p0)
        self.assertIsNone(err)
        self.assertIsNotNone(card)
        self.p0.refresh_from_db()
        self.assertEqual(len(self.p0.hand), 1)
        self.assertEqual(self.p0.hand[0], card)

    def test_deck_shrinks(self):
        deck_before = len(self.room.deck)
        game_logic.draw_from_deck(self.p0)
        self.room.refresh_from_db()
        self.assertEqual(len(self.room.deck), deck_before - 1)

    def test_not_your_turn(self):
        card, err = game_logic.draw_from_deck(self.players[1])
        self.assertEqual(err, "Not your turn")

    def test_already_holding(self):
        game_logic.draw_from_deck(self.p0)
        card, err = game_logic.draw_from_deck(self.p0)
        self.assertEqual(err, "You already have a card in hand")

    def test_game_not_playing(self):
        self.room.state = 'waiting'
        self.room.save()
        card, err = game_logic.draw_from_deck(self.p0)
        self.assertEqual(err, "Game is not in progress")

    def test_reshuffle_when_deck_empty(self):
        self.room.deck = []
        # Put some cards in discard pile (more than 1 so reshuffle happens)
        self.room.discard_pile = [make_card('2'), make_card('3'), make_card('4')]
        self.room.save()

        card, err = game_logic.draw_from_deck(self.p0)
        self.assertIsNone(err)
        self.assertIsNotNone(card)
        self.room.refresh_from_db()
        # After reshuffle: 3 discard cards minus top = 2 reshuffled into deck,
        # then we drew 1, so deck should have 1 left, and discard has 1 (the top)
        self.assertEqual(len(self.room.discard_pile), 1)

    def test_no_cards_left(self):
        self.room.deck = []
        self.room.discard_pile = [make_card('2')]  # only 1 card, can't reshuffle
        self.room.save()
        card, err = game_logic.draw_from_deck(self.p0)
        self.assertEqual(err, "No cards left to draw")


class TestDrawFromDiscard(TestCase):

    def setUp(self):
        self.room, self.players = create_started_game(2)
        self.p0 = self.players[0]

    def test_draw_from_discard(self):
        test_card = make_card('A', 'spades')
        self.room.discard_pile = [test_card]
        self.room.save()

        card, err = game_logic.draw_from_discard(self.p0)
        self.assertIsNone(err)
        self.assertEqual(card, test_card)
        self.p0.refresh_from_db()
        self.assertEqual(self.p0.hand, [test_card])
        self.room.refresh_from_db()
        self.assertEqual(self.room.discard_pile, [])

    def test_not_your_turn(self):
        card, err = game_logic.draw_from_discard(self.players[1])
        self.assertEqual(err, "Not your turn")

    def test_already_holding(self):
        self.room.discard_pile = [make_card('A')]
        self.room.save()
        game_logic.draw_from_discard(self.p0)
        card, err = game_logic.draw_from_discard(self.p0)
        self.assertEqual(err, "You already have a card in hand")

    def test_empty_pile(self):
        card, err = game_logic.draw_from_discard(self.p0)
        self.assertEqual(err, "Discard pile is empty")


class TestDiscardFromHand(TestCase):

    def setUp(self):
        self.room, self.players = create_started_game(2)
        self.p0 = self.players[0]

    def test_discard_card(self):
        # Draw a card first
        drawn, _ = game_logic.draw_from_deck(self.p0)
        card, err = game_logic.discard_from_hand(self.p0, 0)
        self.assertIsNone(err)
        self.assertEqual(card, drawn)
        self.p0.refresh_from_db()
        self.assertEqual(self.p0.hand, [])
        self.room.refresh_from_db()
        self.assertEqual(self.room.discard_pile[-1], drawn)

    def test_discard_not_your_turn(self):
        self.p0.hand = [make_card('A')]
        self.p0.save()
        card, err = game_logic.discard_from_hand(self.players[1], 0)
        self.assertEqual(err, "Not your turn")

    def test_discard_empty_hand(self):
        card, err = game_logic.discard_from_hand(self.p0, 0)
        self.assertEqual(err, "No card in hand to discard")

    def test_discard_invalid_index_defaults_to_0(self):
        self.p0.hand = [make_card('A'), make_card('B')]
        self.p0.save()
        card, err = game_logic.discard_from_hand(self.p0, -1)
        self.assertIsNone(err)
        self.assertEqual(card['value'], 'A')


class TestReplaceCarrot(TestCase):

    def setUp(self):
        self.room, self.players = create_started_game(2)
        self.p0 = self.players[0]

    def test_replace_carrot(self):
        drawn, _ = game_logic.draw_from_deck(self.p0)
        old_carrot = self.p0.get_carrot(0)

        result, err = game_logic.replace_carrot(self.p0, 0, 0)
        self.assertIsNone(err)
        self.assertEqual(result['new_card'], drawn)
        self.assertEqual(result['old_card'], old_carrot)

        self.p0.refresh_from_db()
        self.assertEqual(self.p0.get_carrot(0), drawn)
        self.assertEqual(self.p0.hand, [])

        self.room.refresh_from_db()
        self.assertEqual(self.room.discard_pile[-1], old_carrot)

    def test_replace_invalid_carrot_index(self):
        drawn, _ = game_logic.draw_from_deck(self.p0)
        result, err = game_logic.replace_carrot(self.p0, 0, 5)
        self.assertEqual(err, "Invalid carrot index")

    def test_replace_invalid_hand_index(self):
        drawn, _ = game_logic.draw_from_deck(self.p0)
        result, err = game_logic.replace_carrot(self.p0, 99, 0)
        self.assertEqual(err, "Invalid hand card index")

    def test_replace_not_your_turn(self):
        self.p0.hand = [make_card('A')]
        self.p0.save()
        result, err = game_logic.replace_carrot(self.players[1], 0, 0)
        self.assertEqual(err, "Not your turn")

    def test_replace_no_hand(self):
        result, err = game_logic.replace_carrot(self.p0, 0, 0)
        self.assertEqual(err, "No card in hand")


class TestPowers(TestCase):

    def setUp(self):
        self.room, self.players = create_started_game(3)
        self.p0 = self.players[0]

    def test_power_seven_peeks_own_carrot(self):
        # Set a known carrot
        known = make_card('K', 'diamonds')
        self.p0.set_carrot(0, known)
        self.p0.save()

        carrot, err = game_logic.use_power_seven(self.p0, 0)
        self.assertIsNone(err)
        self.assertEqual(carrot, known)
        self.p0.refresh_from_db()
        self.assertTrue(self.p0.get_visible(0))

    def test_power_seven_invalid_index(self):
        carrot, err = game_logic.use_power_seven(self.p0, 5)
        self.assertEqual(err, "Invalid carrot index")

    def test_power_eight_peeks_opponent(self):
        p1 = self.players[1]
        known = make_card('A', 'clubs')
        p1.set_carrot(2, known)
        p1.save()

        carrot, err = game_logic.use_power_eight(self.p0, p1.id, 2)
        self.assertIsNone(err)
        self.assertEqual(carrot, known)

    def test_power_eight_cannot_target_self(self):
        carrot, err = game_logic.use_power_eight(self.p0, self.p0.id, 0)
        self.assertEqual(err, "Cannot target yourself with 8")

    def test_power_eight_invalid_player(self):
        carrot, err = game_logic.use_power_eight(self.p0, 99999, 0)
        self.assertEqual(err, "Target player not found")

    def test_power_nine_swaps_carrots(self):
        p1 = self.players[1]
        card_a = make_card('2', 'hearts')
        card_b = make_card('J', 'spades')
        self.p0.set_carrot(1, card_a)
        self.p0.set_visible(1, True)
        p1.set_carrot(3, card_b)
        p1.set_visible(3, True)
        self.p0.save()
        p1.save()

        success, err = game_logic.use_power_nine(self.p0, self.p0.id, 1, p1.id, 3)
        self.assertIsNone(err)
        self.assertTrue(success)

        self.p0.refresh_from_db()
        p1.refresh_from_db()
        self.assertEqual(self.p0.get_carrot(1), card_b)
        self.assertEqual(p1.get_carrot(3), card_a)
        # Visibility should be reset
        self.assertFalse(self.p0.get_visible(1))
        self.assertFalse(p1.get_visible(3))

    def test_power_nine_invalid_player(self):
        success, err = game_logic.use_power_nine(self.p0, 99999, 0, self.p0.id, 1)
        self.assertEqual(err, "Player not found")


class TestTryMatch(TestCase):

    def setUp(self):
        self.room, self.players = create_started_game(2)
        self.p0 = self.players[0]
        self.p1 = self.players[1]

    def test_match_success(self):
        known = make_card('5', 'diamonds')
        self.p1.set_carrot(0, known)
        self.p1.save()
        # Put matching card on discard pile
        self.room.discard_pile = [make_card('5', 'diamonds')]
        self.room.save()

        matched, err = game_logic.try_match_carrot(self.p0, self.p1.id, 0)
        self.assertIsNone(err)
        self.assertTrue(matched)

        self.p1.refresh_from_db()
        self.assertIsNone(self.p1.get_carrot(0))

    def test_match_fail_gives_penalty(self):
        self.p1.set_carrot(0, make_card('2'))
        self.p1.save()
        self.room.discard_pile = [make_card('K', 'spades')]
        self.room.save()

        matched, err = game_logic.try_match_carrot(self.p0, self.p1.id, 0)
        self.assertIsNone(err)
        self.assertFalse(matched)

        self.p0.refresh_from_db()
        self.assertEqual(len(self.p0.hand), 2)

    def test_match_empty_pile(self):
        matched, err = game_logic.try_match_carrot(self.p0, self.p1.id, 0)
        self.assertEqual(err, "No card on discard pile")

    def test_match_invalid_player(self):
        self.room.discard_pile = [make_card('A')]
        self.room.save()
        matched, err = game_logic.try_match_carrot(self.p0, 99999, 0)
        self.assertEqual(err, "Target player not found")

    def test_match_empty_carrot(self):
        self.p1.set_carrot(0, None)
        self.p1.save()
        self.room.discard_pile = [make_card('A')]
        self.room.save()
        matched, err = game_logic.try_match_carrot(self.p0, self.p1.id, 0)
        self.assertEqual(err, "No carrot at that position")


class TestClaimCooked(TestCase):

    def setUp(self):
        self.room, self.players = create_started_game(2)
        self.p0 = self.players[0]

    def test_claim_cooked(self):
        success, err = game_logic.claim_cooked(self.p0)
        self.assertIsNone(err)
        self.assertTrue(success)
        self.p0.refresh_from_db()
        self.assertTrue(self.p0.has_claimed_cooked)

    def test_claim_cooked_already_claimed(self):
        game_logic.claim_cooked(self.p0)
        success, err = game_logic.claim_cooked(self.p0)
        self.assertEqual(err, "Already claimed cooked")

    def test_claim_cooked_not_your_turn(self):
        success, err = game_logic.claim_cooked(self.players[1])
        self.assertEqual(err, "Not your turn")

    def test_claim_cooked_ends_game_on_next_turn(self):
        game_logic.claim_cooked(self.p0)
        # Advance to next player (p1) — game continues
        game_logic.get_next_turn(self.room)
        self.room.refresh_from_db()
        self.assertEqual(self.room.state, 'playing')

        # Advance back to p0 (who claimed cooked) — game ends
        game_logic.get_next_turn(self.room)
        self.room.refresh_from_db()
        self.assertEqual(self.room.state, 'finished')


class TestGetNextTurn(TestCase):

    def setUp(self):
        self.room, self.players = create_started_game(3)

    def test_advances_turn(self):
        self.assertEqual(self.room.current_turn_index, 0)
        game_logic.get_next_turn(self.room)
        self.room.refresh_from_db()
        self.assertEqual(self.room.current_turn_index, 1)

    def test_wraps_around(self):
        self.room.current_turn_index = 2
        self.room.save()
        game_logic.get_next_turn(self.room)
        self.room.refresh_from_db()
        self.assertEqual(self.room.current_turn_index, 0)

    def test_ends_game_when_cooked_claimed(self):
        # p1 claims cooked on their turn, turn advances to p2,
        # then p2 plays, p0 plays, then p1's turn again → game ends
        self.room.current_turn_index = 1
        self.room.save()
        self.players[1].has_claimed_cooked = True
        self.players[1].save()

        # Advance from p1 to p2 — game continues
        game_logic.get_next_turn(self.room)
        self.room.refresh_from_db()
        self.assertEqual(self.room.state, 'playing')
        self.assertEqual(self.room.current_turn_index, 2)

        # Advance from p2 to p0 — game continues
        game_logic.get_next_turn(self.room)
        self.room.refresh_from_db()
        self.assertEqual(self.room.state, 'playing')
        self.assertEqual(self.room.current_turn_index, 0)

        # Advance from p0 to p1 (who claimed) — game ends
        game_logic.get_next_turn(self.room)
        self.room.refresh_from_db()
        self.assertEqual(self.room.state, 'finished')


class TestCalculateScores(TestCase):

    def test_scores_sorted_ascending(self):
        room, players = create_started_game(2)
        # Clear all carrots first, then set known cards
        for p in players:
            for i in range(4):
                p.set_carrot(i, None)
        # Give known cards
        players[0].set_carrot(0, make_card('K', 'hearts'))  # -1
        players[0].set_carrot(1, make_card('2'))             # 2
        players[0].save()
        players[1].set_carrot(0, make_card('Q'))             # 10
        players[1].set_carrot(1, make_card('10'))            # 10
        players[1].save()

        scores = game_logic.calculate_scores(room)
        self.assertEqual(scores[0]['score'], 1)   # p0: -1+2=1
        self.assertEqual(scores[1]['score'], 20)  # p1: 10+10=20


# ---------------------------------------------------------------------------
# View / API tests
# ---------------------------------------------------------------------------
class TestCreateRoom(TestCase):

    def setUp(self):
        self.client = Client()

    def test_create_room(self):
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Alice'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('room_code', data)
        self.assertIn('player_id', data)
        self.assertEqual(data['position'], 0)

    def test_create_room_no_name(self):
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': ''}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_create_room_invalid_json(self):
        resp = self.client.post('/api/create-room/',
                                data='not json',
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)


class TestJoinRoom(TestCase):

    def setUp(self):
        self.client = Client()
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Host'}),
                                content_type='application/json')
        self.room_code = resp.json()['room_code']

    def test_join_room(self):
        resp = self.client.post('/api/join-room/',
                                data=json.dumps({'name': 'Bob', 'room_code': self.room_code}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['position'], 1)

    def test_join_room_not_found(self):
        resp = self.client.post('/api/join-room/',
                                data=json.dumps({'name': 'Bob', 'room_code': 'ZZZZZZ'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_join_room_missing_fields(self):
        resp = self.client.post('/api/join-room/',
                                data=json.dumps({'name': ''}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_join_room_full(self):
        # Fill up to 8 players (already have 1 from create)
        for i in range(7):
            self.client.post('/api/join-room/',
                             data=json.dumps({'name': f'P{i}', 'room_code': self.room_code}),
                             content_type='application/json')
        resp = self.client.post('/api/join-room/',
                                data=json.dumps({'name': 'Extra', 'room_code': self.room_code}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)


class TestStartGame(TestCase):

    def setUp(self):
        self.client = Client()
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Host'}),
                                content_type='application/json')
        self.host_data = resp.json()
        self.room_code = self.host_data['room_code']
        # Join with second player
        resp = self.client.post('/api/join-room/',
                                data=json.dumps({'name': 'P2', 'room_code': self.room_code}),
                                content_type='application/json')
        self.p2_data = resp.json()

    def test_start_game(self):
        resp = self.client.post('/api/start-game/',
                                data=json.dumps({'player_id': self.host_data['player_id']}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

    def test_start_game_not_enough_players(self):
        # Create a fresh room with only 1 player
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Solo'}),
                                content_type='application/json')
        solo_id = resp.json()['player_id']
        resp = self.client.post('/api/start-game/',
                                data=json.dumps({'player_id': solo_id}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_start_game_not_host(self):
        resp = self.client.post('/api/start-game/',
                                data=json.dumps({'player_id': self.p2_data['player_id']}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)


class TestGameState(TestCase):

    def setUp(self):
        self.client = Client()
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Host'}),
                                content_type='application/json')
        self.host_data = resp.json()
        self.room_code = self.host_data['room_code']
        self.client.post('/api/join-room/',
                         data=json.dumps({'name': 'P2', 'room_code': self.room_code}),
                         content_type='application/json')

    def test_game_state_waiting(self):
        resp = self.client.get(f'/api/game-state/{self.room_code}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['state'], 'waiting')
        self.assertEqual(len(data['players']), 2)

    def test_game_state_playing(self):
        self.client.post('/api/start-game/',
                         data=json.dumps({'player_id': self.host_data['player_id']}),
                         content_type='application/json')
        resp = self.client.get(f'/api/game-state/{self.room_code}/')
        data = resp.json()
        self.assertEqual(data['state'], 'playing')
        self.assertIsNotNone(data['current_player_id'])
        self.assertIsNotNone(data['deck_count'])

    def test_game_state_not_found(self):
        resp = self.client.get('/api/game-state/ZZZZZZ/')
        self.assertEqual(resp.status_code, 400)


class TestDrawCard(TestCase):

    def setUp(self):
        self.client = Client()
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Host'}),
                                content_type='application/json')
        self.host = resp.json()
        self.room_code = self.host['room_code']
        resp = self.client.post('/api/join-room/',
                                data=json.dumps({'name': 'P2', 'room_code': self.room_code}),
                                content_type='application/json')
        self.p2 = resp.json()
        self.client.post('/api/start-game/',
                         data=json.dumps({'player_id': self.host['player_id']}),
                         content_type='application/json')

    def test_draw_from_deck(self):
        resp = self.client.post('/api/draw-card/',
                                data=json.dumps({'player_id': self.host['player_id'], 'source': 'deck'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('card', data)
        self.assertEqual(data['source'], 'deck')

    def test_draw_from_discard_empty(self):
        resp = self.client.post('/api/draw-card/',
                                data=json.dumps({'player_id': self.host['player_id'], 'source': 'discard'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_draw_not_your_turn(self):
        resp = self.client.post('/api/draw-card/',
                                data=json.dumps({'player_id': self.p2['player_id'], 'source': 'deck'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_draw_invalid_source(self):
        resp = self.client.post('/api/draw-card/',
                                data=json.dumps({'player_id': self.host['player_id'], 'source': 'invalid'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_draw_player_not_found(self):
        resp = self.client.post('/api/draw-card/',
                                data=json.dumps({'player_id': 99999, 'source': 'deck'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# Game logic edge cases
# ---------------------------------------------------------------------------
class TestTryMatchEdgeCases(TestCase):

    def setUp(self):
        self.room, self.players = create_started_game(2)
        self.p0 = self.players[0]

    def test_match_own_carrot(self):
        known = make_card('5', 'diamonds')
        self.p0.set_carrot(0, known)
        self.p0.save()
        self.room.discard_pile = [make_card('5', 'diamonds')]
        self.room.save()

        matched, err = game_logic.try_match_carrot(self.p0, self.p0.id, 0)
        self.assertIsNone(err)
        self.assertTrue(matched)
        self.p0.refresh_from_db()
        self.assertIsNone(self.p0.get_carrot(0))

    def test_match_not_in_progress(self):
        self.room.state = 'finished'
        self.room.save()
        matched, err = game_logic.try_match_carrot(self.p0, self.players[1].id, 0)
        self.assertEqual(err, "Game is not in progress")

    def test_match_penalty_when_deck_low(self):
        self.players[1].set_carrot(0, make_card('2'))
        self.players[1].save()
        self.room.discard_pile = [make_card('K')]
        self.room.deck = [make_card('A')]  # only 1 card in deck
        self.room.save()

        matched, err = game_logic.try_match_carrot(self.p0, self.players[1].id, 0)
        self.assertIsNone(err)
        self.assertFalse(matched)
        self.p0.refresh_from_db()
        # Only 1 card available for penalty
        self.assertEqual(len(self.p0.hand), 1)

    def test_match_penalty_when_deck_empty(self):
        self.players[1].set_carrot(0, make_card('2'))
        self.players[1].save()
        self.room.discard_pile = [make_card('K')]
        self.room.deck = []
        self.room.save()

        matched, err = game_logic.try_match_carrot(self.p0, self.players[1].id, 0)
        self.assertIsNone(err)
        self.assertFalse(matched)
        self.p0.refresh_from_db()
        self.assertEqual(len(self.p0.hand), 0)

    def test_match_invalid_carrot_index(self):
        self.room.discard_pile = [make_card('A')]
        self.room.save()
        matched, err = game_logic.try_match_carrot(self.p0, self.players[1].id, 5)
        self.assertEqual(err, "Invalid carrot index")


class TestPowerNineEdgeCases(TestCase):

    def setUp(self):
        self.room, self.players = create_started_game(3)
        self.p0 = self.players[0]

    def test_swap_same_carrot(self):
        card_a = make_card('2', 'hearts')
        self.p0.set_carrot(0, card_a)
        self.p0.save()

        success, err = game_logic.use_power_nine(self.p0, self.p0.id, 0, self.p0.id, 0)
        self.assertIsNone(err)
        self.assertTrue(success)
        self.p0.refresh_from_db()
        self.assertEqual(self.p0.get_carrot(0), card_a)

    def test_swap_two_carrots_same_player(self):
        card_a = make_card('2', 'hearts')
        card_b = make_card('J', 'spades')
        self.p0.set_carrot(0, card_a)
        self.p0.set_carrot(1, card_b)
        self.p0.save()

        success, err = game_logic.use_power_nine(self.p0, self.p0.id, 0, self.p0.id, 1)
        self.assertIsNone(err)
        self.assertTrue(success)
        self.p0.refresh_from_db()
        self.assertEqual(self.p0.get_carrot(0), card_b)
        self.assertEqual(self.p0.get_carrot(1), card_a)

    def test_swap_invalid_index_zero(self):
        success, err = game_logic.use_power_nine(self.p0, self.p0.id, -1, self.p0.id, 0)
        self.assertEqual(err, "Invalid carrot index")

    def test_swap_resets_visibility(self):
        card_a = make_card('2', 'hearts')
        card_b = make_card('J', 'spades')
        self.p0.set_carrot(0, card_a)
        self.p0.set_visible(0, True)
        self.players[1].set_carrot(1, card_b)
        self.players[1].set_visible(1, True)
        self.p0.save()
        self.players[1].save()

        game_logic.use_power_nine(self.p0, self.p0.id, 0, self.players[1].id, 1)
        self.p0.refresh_from_db()
        self.players[1].refresh_from_db()
        self.assertFalse(self.p0.get_visible(0))
        self.assertFalse(self.players[1].get_visible(1))


class TestCalculateScoresEdgeCases(TestCase):

    def test_scores_with_hand_cards(self):
        room, players = create_started_game(2)
        for p in players:
            for i in range(4):
                p.set_carrot(i, None)
        # p0 has no carrots but 2 cards in hand
        players[0].hand = [make_card('5'), make_card('3')]
        players[0].save()
        # p1 has one carrot
        players[1].set_carrot(0, make_card('Q'))
        players[1].save()

        scores = game_logic.calculate_scores(room)
        self.assertEqual(scores[0]['score'], 8)   # 5+3
        self.assertEqual(scores[1]['score'], 10)

    def test_scores_all_empty(self):
        room, players = create_started_game(2)
        for p in players:
            for i in range(4):
                p.set_carrot(i, None)
            p.save()

        scores = game_logic.calculate_scores(room)
        self.assertEqual(scores[0]['score'], 0)
        self.assertEqual(scores[1]['score'], 0)

    def test_scores_mixed_cards(self):
        room, players = create_started_game(2)
        for p in players:
            for i in range(4):
                p.set_carrot(i, None)
            p.save()
        # K♥(-1) + Q(10) + 5(5) + A(1) = 15
        players[0].set_carrot(0, make_card('K', 'hearts'))
        players[0].set_carrot(1, make_card('Q'))
        players[0].set_carrot(2, make_card('5'))
        players[0].set_carrot(3, make_card('A'))
        players[0].save()

        scores = game_logic.calculate_scores(room)
        self.assertEqual(scores[0]['score'], 0)   # p1: all empty
        self.assertEqual(scores[1]['score'], 15)   # p0: -1+10+5+1


class TestStartGameEdgeCases(TestCase):

    def test_start_game_4_players(self):
        room, players = create_started_game(4)
        for p in players:
            for i in range(4):
                self.assertIsNotNone(p.get_carrot(i))
        self.assertEqual(len(room.deck), 36)  # 52 - 16

    def test_start_game_resets_cooked_claim(self):
        room, players = create_started_game(2)
        players[0].has_claimed_cooked = True
        players[0].save()
        game_logic.start_game(room)
        players[0].refresh_from_db()
        self.assertFalse(players[0].has_claimed_cooked)

    def test_start_game_cards_unique_across_players(self):
        room, players = create_started_game(3)
        all_cards = []
        for p in players:
            for i in range(4):
                all_cards.append(card_key(p.get_carrot(i)))
        self.assertEqual(len(all_cards), len(set(all_cards)))

    def test_start_game_empty_room(self):
        room = Room.objects.create()
        room.deck = [make_card('A')]
        room.save()
        # No players — should not crash
        game_logic.start_game(room)
        room.refresh_from_db()
        self.assertEqual(room.state, 'playing')


class TestDrawFromDeckPileStandalone(TestCase):

    def test_draw_normal(self):
        room = Room.objects.create()
        room.deck = [make_card('A'), make_card('B')]
        room.save()
        card, reshuffled = game_logic.draw_from_deck_pile(room)
        self.assertEqual(card, make_card('B'))
        self.assertFalse(reshuffled)
        self.assertEqual(len(room.deck), 1)

    def test_draw_empty_deck_no_reshuffle(self):
        room = Room.objects.create()
        room.deck = []
        room.discard_pile = [make_card('A')]
        room.save()
        card, reshuffled = game_logic.draw_from_deck_pile(room)
        self.assertIsNone(card)
        self.assertFalse(reshuffled)

    def test_draw_reshuffles_discard(self):
        room = Room.objects.create()
        room.deck = []
        room.discard_pile = [make_card('A'), make_card('B'), make_card('C')]
        room.save()
        card, reshuffled = game_logic.draw_from_deck_pile(room)
        self.assertIsNotNone(card)
        self.assertTrue(reshuffled)
        # Top card (C) stays in discard, A+B reshuffled into deck
        self.assertEqual(len(room.discard_pile), 1)
        self.assertEqual(room.discard_pile[0], make_card('C'))


class TestGetNextTurnEdgeCases(TestCase):

    def test_empty_room(self):
        room = Room.objects.create()
        room.current_turn_index = 0
        room.save()
        # Should not crash
        game_logic.get_next_turn(room)

    def test_single_player(self):
        room, players = create_started_game(1)
        self.assertEqual(room.current_turn_index, 0)
        game_logic.get_next_turn(room)
        room.refresh_from_db()
        self.assertEqual(room.current_turn_index, 0)


# ---------------------------------------------------------------------------
# Additional view / API tests
# ---------------------------------------------------------------------------
class TestDiscardCardView(TestCase):

    def setUp(self):
        self.client = Client()
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Host'}),
                                content_type='application/json')
        self.host = resp.json()
        self.room_code = self.host['room_code']
        resp = self.client.post('/api/join-room/',
                                data=json.dumps({'name': 'P2', 'room_code': self.room_code}),
                                content_type='application/json')
        self.p2 = resp.json()
        self.client.post('/api/start-game/',
                         data=json.dumps({'player_id': self.host['player_id']}),
                         content_type='application/json')

    def test_discard_non_power_advances_turn(self):
        # Set up a deterministic deck so we know the drawn card
        room = Room.objects.get(code=self.room_code)
        room.deck = [make_card('3', 'clubs')]  # non-power card
        room.save()
        # Draw the known card
        self.client.post('/api/draw-card/',
                         data=json.dumps({'player_id': self.host['player_id'], 'source': 'deck'}),
                         content_type='application/json')
        resp = self.client.post('/api/discard-card/',
                                data=json.dumps({'player_id': self.host['player_id']}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        # Turn should have advanced to p2
        state_resp = self.client.get(f'/api/game-state/{self.room_code}/')
        self.assertEqual(state_resp.json()['current_player_id'], self.p2['player_id'])

    def test_discard_empty_hand(self):
        resp = self.client.post('/api/discard-card/',
                                data=json.dumps({'player_id': self.host['player_id']}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_discard_not_your_turn(self):
        # Draw for host first
        self.client.post('/api/draw-card/',
                         data=json.dumps({'player_id': self.host['player_id'], 'source': 'deck'}),
                         content_type='application/json')
        resp = self.client.post('/api/discard-card/',
                                data=json.dumps({'player_id': self.p2['player_id']}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_discard_player_not_found(self):
        resp = self.client.post('/api/discard-card/',
                                data=json.dumps({'player_id': 99999}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)


class TestReplaceCarrotView(TestCase):

    def setUp(self):
        self.client = Client()
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Host'}),
                                content_type='application/json')
        self.host = resp.json()
        self.room_code = self.host['room_code']
        resp = self.client.post('/api/join-room/',
                                data=json.dumps({'name': 'P2', 'room_code': self.room_code}),
                                content_type='application/json')
        self.p2 = resp.json()
        self.client.post('/api/start-game/',
                         data=json.dumps({'player_id': self.host['player_id']}),
                         content_type='application/json')

    def test_replace_carrot(self):
        # Draw a card
        self.client.post('/api/draw-card/',
                         data=json.dumps({'player_id': self.host['player_id'], 'source': 'deck'}),
                         content_type='application/json')
        resp = self.client.post('/api/replace-carrot/',
                                data=json.dumps({
                                    'player_id': self.host['player_id'],
                                    'hand_card_index': 0,
                                    'carrot_index': 0
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('new_card', data)
        self.assertIn('old_card', data)
        # Turn should advance
        state_resp = self.client.get(f'/api/game-state/{self.room_code}/')
        self.assertEqual(state_resp.json()['current_player_id'], self.p2['player_id'])

    def test_replace_missing_carrot_index(self):
        self.client.post('/api/draw-card/',
                         data=json.dumps({'player_id': self.host['player_id'], 'source': 'deck'}),
                         content_type='application/json')
        resp = self.client.post('/api/replace-carrot/',
                                data=json.dumps({
                                    'player_id': self.host['player_id'],
                                    'hand_card_index': 0
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_replace_no_hand(self):
        resp = self.client.post('/api/replace-carrot/',
                                data=json.dumps({
                                    'player_id': self.host['player_id'],
                                    'hand_card_index': 0,
                                    'carrot_index': 0
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_replace_not_your_turn(self):
        self.client.post('/api/draw-card/',
                         data=json.dumps({'player_id': self.host['player_id'], 'source': 'deck'}),
                         content_type='application/json')
        resp = self.client.post('/api/replace-carrot/',
                                data=json.dumps({
                                    'player_id': self.p2['player_id'],
                                    'hand_card_index': 0,
                                    'carrot_index': 0
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)


class TestClaimCookedView(TestCase):

    def setUp(self):
        self.client = Client()
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Host'}),
                                content_type='application/json')
        self.host = resp.json()
        self.room_code = self.host['room_code']
        self.client.post('/api/join-room/',
                         data=json.dumps({'name': 'P2', 'room_code': self.room_code}),
                         content_type='application/json')
        self.client.post('/api/start-game/',
                         data=json.dumps({'player_id': self.host['player_id']}),
                         content_type='application/json')

    def test_claim_cooked(self):
        resp = self.client.post('/api/claim-cooked/',
                                data=json.dumps({'player_id': self.host['player_id']}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

    def test_claim_cooked_not_your_turn(self):
        p2_id = self.client.get(f'/api/game-state/{self.room_code}/').json()['players'][1]['id']
        resp = self.client.post('/api/claim-cooked/',
                                data=json.dumps({'player_id': p2_id}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_claim_cooked_player_not_found(self):
        resp = self.client.post('/api/claim-cooked/',
                                data=json.dumps({'player_id': 99999}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)


class TestUsePowerView(TestCase):

    def setUp(self):
        self.client = Client()
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Host'}),
                                content_type='application/json')
        self.host = resp.json()
        self.room_code = self.host['room_code']
        resp = self.client.post('/api/join-room/',
                                data=json.dumps({'name': 'P2', 'room_code': self.room_code}),
                                content_type='application/json')
        self.p2 = resp.json()
        self.client.post('/api/start-game/',
                         data=json.dumps({'player_id': self.host['player_id']}),
                         content_type='application/json')

    def test_power_seven(self):
        resp = self.client.post('/api/use-power/',
                                data=json.dumps({
                                    'player_id': self.host['player_id'],
                                    'power': '7',
                                    'target_carrot_index': 0
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('carrot', resp.json())

    def test_power_seven_missing_index(self):
        resp = self.client.post('/api/use-power/',
                                data=json.dumps({
                                    'player_id': self.host['player_id'],
                                    'power': '7'
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_power_eight(self):
        resp = self.client.post('/api/use-power/',
                                data=json.dumps({
                                    'player_id': self.host['player_id'],
                                    'power': '8',
                                    'target_player_id': self.p2['player_id'],
                                    'target_carrot_index': 0
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

    def test_power_eight_self_target(self):
        resp = self.client.post('/api/use-power/',
                                data=json.dumps({
                                    'player_id': self.host['player_id'],
                                    'power': '8',
                                    'target_player_id': self.host['player_id'],
                                    'target_carrot_index': 0
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_power_nine(self):
        resp = self.client.post('/api/use-power/',
                                data=json.dumps({
                                    'player_id': self.host['player_id'],
                                    'power': '9',
                                    'carrot1_player_id': self.host['player_id'],
                                    'carrot1_index': 0,
                                    'carrot2_player_id': self.p2['player_id'],
                                    'carrot2_index': 1
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

    def test_power_nine_missing_params(self):
        resp = self.client.post('/api/use-power/',
                                data=json.dumps({
                                    'player_id': self.host['player_id'],
                                    'power': '9',
                                    'carrot1_player_id': self.host['player_id']
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_invalid_power(self):
        resp = self.client.post('/api/use-power/',
                                data=json.dumps({
                                    'player_id': self.host['player_id'],
                                    'power': '13'
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_power_not_your_turn(self):
        resp = self.client.post('/api/use-power/',
                                data=json.dumps({
                                    'player_id': self.p2['player_id'],
                                    'power': '7',
                                    'target_carrot_index': 0
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)


class TestTryMatchView(TestCase):

    def setUp(self):
        self.client = Client()
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Host'}),
                                content_type='application/json')
        self.host = resp.json()
        self.room_code = self.host['room_code']
        resp = self.client.post('/api/join-room/',
                                data=json.dumps({'name': 'P2', 'room_code': self.room_code}),
                                content_type='application/json')
        self.p2 = resp.json()
        self.client.post('/api/start-game/',
                         data=json.dumps({'player_id': self.host['player_id']}),
                         content_type='application/json')

    def test_try_match(self):
        # Put a card on the discard pile
        room = Room.objects.get(code=self.room_code)
        room.discard_pile = [make_card('A', 'spades')]
        room.save()

        resp = self.client.post('/api/try-match/',
                                data=json.dumps({
                                    'player_id': self.host['player_id'],
                                    'target_player_id': self.p2['player_id'],
                                    'carrot_index': 0
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('matched', resp.json())

    def test_try_match_missing_params(self):
        resp = self.client.post('/api/try-match/',
                                data=json.dumps({
                                    'player_id': self.host['player_id']
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_try_match_player_not_found(self):
        resp = self.client.post('/api/try-match/',
                                data=json.dumps({
                                    'player_id': 99999,
                                    'target_player_id': self.p2['player_id'],
                                    'carrot_index': 0
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 400)


class TestScoresView(TestCase):

    def setUp(self):
        self.client = Client()
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Host'}),
                                content_type='application/json')
        self.host = resp.json()
        self.room_code = self.host['room_code']
        self.client.post('/api/join-room/',
                         data=json.dumps({'name': 'P2', 'room_code': self.room_code}),
                         content_type='application/json')

    def test_scores_waiting(self):
        resp = self.client.get(f'/api/scores/{self.room_code}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['state'], 'waiting')
        self.assertEqual(len(data['scores']), 2)

    def test_scores_not_found(self):
        resp = self.client.get('/api/scores/ZZZZZZ/')
        self.assertEqual(resp.status_code, 400)


class TestGameStateVisibility(TestCase):

    def setUp(self):
        self.client = Client()
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Host'}),
                                content_type='application/json')
        self.host = resp.json()
        self.room_code = self.host['room_code']
        resp = self.client.post('/api/join-room/',
                                data=json.dumps({'name': 'P2', 'room_code': self.room_code}),
                                content_type='application/json')
        self.p2 = resp.json()
        self.client.post('/api/start-game/',
                         data=json.dumps({'player_id': self.host['player_id']}),
                         content_type='application/json')

    def test_host_sees_own_hand(self):
        # Draw a card so host has something in hand
        self.client.post('/api/draw-card/',
                         data=json.dumps({'player_id': self.host['player_id'], 'source': 'deck'}),
                         content_type='application/json')
        resp = self.client.get(f'/api/game-state/{self.room_code}/?player_id={self.host["player_id"]}')
        data = resp.json()
        host_player = [p for p in data['players'] if p['id'] == self.host['player_id']][0]
        self.assertIn('hand', host_player)
        self.assertEqual(len(host_player['hand']), 1)

    def test_other_player_sees_hand_count_only(self):
        self.client.post('/api/draw-card/',
                         data=json.dumps({'player_id': self.host['player_id'], 'source': 'deck'}),
                         content_type='application/json')
        resp = self.client.get(f'/api/game-state/{self.room_code}/?player_id={self.p2["player_id"]}')
        data = resp.json()
        host_player = [p for p in data['players'] if p['id'] == self.host['player_id']][0]
        self.assertNotIn('hand', host_player)
        self.assertEqual(host_player['hand_count'], 1)

    def test_visible_carrots_shown_to_others(self):
        resp = self.client.get(f'/api/game-state/{self.room_code}/?player_id={self.p2["player_id"]}')
        data = resp.json()
        host_player = [p for p in data['players'] if p['id'] == self.host['player_id']][0]
        # Carrots 2 and 3 should be visible (from start_game)
        self.assertIsNotNone(host_player['carrots'][2]['card'])
        self.assertIsNotNone(host_player['carrots'][3]['card'])
        # Carrots 0 and 1 should not be visible
        self.assertIsNone(host_player['carrots'][0]['card'])
        self.assertIsNone(host_player['carrots'][1]['card'])

    def test_discard_pile_shows_top_card(self):
        room = Room.objects.get(code=self.room_code)
        room.discard_pile = [make_card('A'), make_card('K', 'hearts')]
        room.save()

        resp = self.client.get(f'/api/game-state/{self.room_code}/')
        data = resp.json()
        self.assertIsNotNone(data['discard_pile'])
        self.assertEqual(data['discard_pile']['value'], 'K')

    def test_discard_pile_empty(self):
        resp = self.client.get(f'/api/game-state/{self.room_code}/')
        data = resp.json()
        self.assertIsNone(data['discard_pile'])

    def test_current_player_null_when_not_playing(self):
        # Game is in 'waiting' state (setUp started it, but let's use a fresh room)
        client = Client()
        resp = client.post('/api/create-room/',
                           data=json.dumps({'name': 'Solo'}),
                           content_type='application/json')
        room_code = resp.json()['room_code']
        resp = client.get(f'/api/game-state/{room_code}/')
        data = resp.json()
        self.assertEqual(data['state'], 'waiting')
        self.assertIsNone(data['current_player_id'])


class TestJoinRoomInProgress(TestCase):

    def test_join_room_already_started(self):
        client = Client()
        resp = client.post('/api/create-room/',
                           data=json.dumps({'name': 'Host'}),
                           content_type='application/json')
        room_code = resp.json()['room_code']
        host_id = resp.json()['player_id']
        client.post('/api/join-room/',
                    data=json.dumps({'name': 'P2', 'room_code': room_code}),
                    content_type='application/json')
        client.post('/api/start-game/',
                    data=json.dumps({'player_id': host_id}),
                    content_type='application/json')
        resp = client.post('/api/join-room/',
                           data=json.dumps({'name': 'P3', 'room_code': room_code}),
                           content_type='application/json')
        self.assertEqual(resp.status_code, 400)


class TestStartGameAlreadyStarted(TestCase):

    def test_start_game_already_playing(self):
        client = Client()
        resp = client.post('/api/create-room/',
                           data=json.dumps({'name': 'Host'}),
                           content_type='application/json')
        room_code = resp.json()['room_code']
        host_id = resp.json()['player_id']
        client.post('/api/join-room/',
                    data=json.dumps({'name': 'P2', 'room_code': room_code}),
                    content_type='application/json')
        client.post('/api/start-game/',
                    data=json.dumps({'player_id': host_id}),
                    content_type='application/json')
        resp = client.post('/api/start-game/',
                           data=json.dumps({'player_id': host_id}),
                           content_type='application/json')
        self.assertEqual(resp.status_code, 400)


class TestHttpMethodEnforcement(TestCase):

    def test_get_on_post_endpoint(self):
        client = Client()
        resp = client.get('/api/create-room/')
        self.assertEqual(resp.status_code, 405)

    def test_post_on_get_endpoint(self):
        client = Client()
        resp = client.post('/api/game-state/ABCDEF/')
        self.assertEqual(resp.status_code, 405)

    def test_put_on_post_endpoint(self):
        client = Client()
        resp = client.put('/api/create-room/')
        self.assertEqual(resp.status_code, 405)


# ---------------------------------------------------------------------------
# Integration / end-to-end tests
# ---------------------------------------------------------------------------
class TestFullGameFlow(TestCase):

    def setUp(self):
        self.client = Client()

    def test_complete_game(self):
        # Create room
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Alice'}),
                                content_type='application/json')
        alice = resp.json()
        room_code = alice['room_code']

        # Bob joins
        resp = self.client.post('/api/join-room/',
                                data=json.dumps({'name': 'Bob', 'room_code': room_code}),
                                content_type='application/json')
        bob = resp.json()

        # Alice starts game
        resp = self.client.post('/api/start-game/',
                                data=json.dumps({'player_id': alice['player_id']}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        # Set up deterministic deck AFTER start_game
        room = Room.objects.get(code=room_code)
        room.deck = [make_card('3', 'clubs'), make_card('5', 'diamonds'),
                     make_card('A', 'spades'), make_card('K', 'clubs'),
                     make_card('2', 'hearts'), make_card('J', 'spades')]
        room.save()

        # Verify initial state
        resp = self.client.get(f'/api/game-state/{room_code}/')
        state = resp.json()
        self.assertEqual(state['state'], 'playing')
        player_ids = [p['id'] for p in state['players']]
        self.assertIn(state['current_player_id'], player_ids)

        # Alice draws from deck (gets 3♣, a non-power card)
        resp = self.client.post('/api/draw-card/',
                                data=json.dumps({'player_id': alice['player_id'], 'source': 'deck'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        # Alice replaces carrot 0
        resp = self.client.post('/api/replace-carrot/',
                                data=json.dumps({
                                    'player_id': alice['player_id'],
                                    'hand_card_index': 0,
                                    'carrot_index': 0
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        # Verify turn advanced to Bob
        resp = self.client.get(f'/api/game-state/{room_code}/')
        state = resp.json()
        self.assertEqual(state['current_player_id'], bob['player_id'])

        # Bob draws from deck (gets 5♦)
        resp = self.client.post('/api/draw-card/',
                                data=json.dumps({'player_id': bob['player_id'], 'source': 'deck'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        # Bob discards the card
        resp = self.client.post('/api/discard-card/',
                                data=json.dumps({'player_id': bob['player_id']}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        # Verify turn advanced back to Alice
        resp = self.client.get(f'/api/game-state/{room_code}/')
        state = resp.json()
        self.assertEqual(state['current_player_id'], alice['player_id'])

        # Alice claims cooked
        resp = self.client.post('/api/claim-cooked/',
                                data=json.dumps({'player_id': alice['player_id']}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        # Alice draws and discards to end her turn (claim doesn't auto-advance)
        resp = self.client.post('/api/draw-card/',
                                data=json.dumps({'player_id': alice['player_id'], 'source': 'deck'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post('/api/discard-card/',
                                data=json.dumps({'player_id': alice['player_id']}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        # Bob takes his final turn — draw and discard
        resp = self.client.post('/api/draw-card/',
                                data=json.dumps({'player_id': bob['player_id'], 'source': 'deck'}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post('/api/discard-card/',
                                data=json.dumps({'player_id': bob['player_id']}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        # Alice's turn again → game should be finished
        resp = self.client.get(f'/api/game-state/{room_code}/')
        state = resp.json()
        self.assertEqual(state['state'], 'finished')

        # Check scores
        resp = self.client.get(f'/api/scores/{room_code}/')
        scores = resp.json()
        self.assertEqual(scores['state'], 'finished')
        self.assertEqual(len(scores['scores']), 2)


class TestPowerCardFlowThroughViews(TestCase):

    def setUp(self):
        self.client = Client()
        resp = self.client.post('/api/create-room/',
                                data=json.dumps({'name': 'Host'}),
                                content_type='application/json')
        self.host = resp.json()
        self.room_code = self.host['room_code']
        resp = self.client.post('/api/join-room/',
                                data=json.dumps({'name': 'P2', 'room_code': self.room_code}),
                                content_type='application/json')
        self.p2 = resp.json()
        self.client.post('/api/start-game/',
                         data=json.dumps({'player_id': self.host['player_id']}),
                         content_type='application/json')

    def test_discard_power_card_does_not_advance_turn(self):
        # Put a power card (7) in host's hand directly
        room = Room.objects.get(code=self.room_code)
        host = Player.objects.get(id=self.host['player_id'])
        host.hand = [make_card('7')]
        host.save()

        # Discard the 7 — turn should NOT advance
        resp = self.client.post('/api/discard-card/',
                                data=json.dumps({'player_id': self.host['player_id']}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        # Turn should still be host's
        resp = self.client.get(f'/api/game-state/{self.room_code}/')
        state = resp.json()
        self.assertEqual(state['current_player_id'], self.host['player_id'])

    def test_use_power_seven_then_turn_advances(self):
        # Use power 7
        resp = self.client.post('/api/use-power/',
                                data=json.dumps({
                                    'player_id': self.host['player_id'],
                                    'power': '7',
                                    'target_carrot_index': 0
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        # Turn should advance to p2
        resp = self.client.get(f'/api/game-state/{self.room_code}/')
        state = resp.json()
        self.assertEqual(state['current_player_id'], self.p2['player_id'])

    def test_use_power_nine_then_turn_advances(self):
        resp = self.client.post('/api/use-power/',
                                data=json.dumps({
                                    'player_id': self.host['player_id'],
                                    'power': '9',
                                    'carrot1_player_id': self.host['player_id'],
                                    'carrot1_index': 0,
                                    'carrot2_player_id': self.p2['player_id'],
                                    'carrot2_index': 1
                                }),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get(f'/api/game-state/{self.room_code}/')
        state = resp.json()
        self.assertEqual(state['current_player_id'], self.p2['player_id'])
