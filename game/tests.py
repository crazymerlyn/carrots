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
