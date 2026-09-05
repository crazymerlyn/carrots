from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json

from .models import Room, Player
from . import game_logic


def json_error(message, status=400):
    return JsonResponse({'error': message}, status=status)


@csrf_exempt
@require_http_methods(["POST"])
def create_room(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return json_error("Invalid JSON")
    
    player_name = data.get('name', '').strip()
    if not player_name:
        return json_error("Name is required")
    
    room = Room.objects.create()
    player = Player.objects.create(
        room=room,
        name=player_name,
        position=0
    )
    
    return JsonResponse({
        'room_code': room.code,
        'player_id': player.id,
        'position': player.position
    })


@csrf_exempt
@require_http_methods(["POST"])
def join_room(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return json_error("Invalid JSON")
    
    room_code = data.get('room_code', '').strip().upper()
    player_name = data.get('name', '').strip()
    
    if not room_code or not player_name:
        return json_error("Room code and name are required")
    
    try:
        room = Room.objects.get(code=room_code)
    except Room.DoesNotExist:
        return json_error("Room not found")
    
    if room.state != 'waiting':
        return json_error("Game already in progress")
    
    existing_count = room.players.count()
    if existing_count >= 8:
        return json_error("Room is full")
    
    player = Player.objects.create(
        room=room,
        name=player_name,
        position=existing_count
    )
    
    return JsonResponse({
        'room_code': room.code,
        'player_id': player.id,
        'position': player.position
    })


@csrf_exempt
@require_http_methods(["POST"])
def start_game(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return json_error("Invalid JSON")
    
    player_id = data.get('player_id')
    if not player_id:
        return json_error("Player ID required")
    
    try:
        player = Player.objects.get(id=player_id)
    except Player.DoesNotExist:
        return json_error("Player not found")
    
    room = player.room
    if room.state != 'waiting':
        return json_error("Game already started")
    
    if room.players.count() < 2:
        return json_error("Need at least 2 players")
    
    if player.position != 0:
        return json_error("Only the host can start the game")
    
    game_logic.start_game(room)
    
    return JsonResponse({'status': 'Game started'})


@csrf_exempt
@require_http_methods(["GET"])
def game_state(request, room_code):
    room_code = room_code.upper()
    
    try:
        room = Room.objects.get(code=room_code)
    except Room.DoesNotExist:
        return json_error("Room not found")
    
    player_id = request.GET.get('player_id')
    
    players_data = []
    for player in room.players.all().order_by('position'):
        carrots = []
        for i in range(4):
            carrot = player.get_carrot(i)
            visible = player.get_visible(i)
            carrots.append({
                'card': carrot if visible or (player_id and int(player_id) == player.id) else None,
                'visible': visible
            })
        
        player_data = {
            'id': player.id,
            'name': player.name,
            'position': player.position,
            'carrots': carrots,
            'hand_count': len(player.hand),
            'has_claimed_cooked': player.has_claimed_cooked
        }
        if player_id and int(player_id) == player.id:
            player_data['hand'] = player.hand
        players_data.append(player_data)
    
    current_player = None
    players_list = list(room.players.all().order_by('position'))
    if players_list and room.state == 'playing':
        current_player = players_list[room.current_turn_index].id
    
    return JsonResponse({
        'room_code': room.code,
        'state': room.state,
        'deck_count': len(room.deck),
        'discard_pile': room.discard_pile[-1] if room.discard_pile else None,
        'discard_count': len(room.discard_pile),
        'current_player_id': current_player,
        'players': players_data,
    })


@csrf_exempt
@require_http_methods(["POST"])
def draw_card(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return json_error("Invalid JSON")
    
    player_id = data.get('player_id')
    source = data.get('source', 'deck')
    
    try:
        player = Player.objects.get(id=player_id)
    except Player.DoesNotExist:
        return json_error("Player not found")
    
    if source == 'deck':
        card, error = game_logic.draw_from_deck(player)
    elif source == 'discard':
        card, error = game_logic.draw_from_discard(player)
    else:
        return json_error("Invalid source")
    
    if error:
        return json_error(error)
    
    return JsonResponse({'card': card, 'source': source})


@csrf_exempt
@require_http_methods(["POST"])
def discard_card(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return json_error("Invalid JSON")
    
    player_id = data.get('player_id')
    hand_card_index = data.get('hand_card_index', 0)
    
    try:
        player = Player.objects.get(id=player_id)
    except Player.DoesNotExist:
        return json_error("Player not found")
    
    card, error = game_logic.discard_from_hand(player, hand_card_index)
    if error:
        return json_error(error)
    
    power_cards = ['7', '8', '9']
    if card['value'] not in power_cards:
        game_logic.get_next_turn(player.room)
    
    return JsonResponse({'card': card})


@csrf_exempt
@require_http_methods(["POST"])
def replace_carrot_view(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return json_error("Invalid JSON")
    
    player_id = data.get('player_id')
    hand_card_index = data.get('hand_card_index', 0)
    carrot_index = data.get('carrot_index')
    
    if carrot_index is None:
        return json_error("Carrot index required")
    
    try:
        player = Player.objects.get(id=player_id)
    except Player.DoesNotExist:
        return json_error("Player not found")
    
    result = game_logic.replace_carrot(player, hand_card_index, carrot_index)
    if len(result) == 2:
        return json_error(result[1])
    
    new_card, old_card, error = result
    if error:
        return json_error(error)
    
    game_logic.get_next_turn(player.room)
    
    return JsonResponse({'new_card': new_card, 'old_card': old_card})


@csrf_exempt
@require_http_methods(["POST"])
def claim_cooked_view(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return json_error("Invalid JSON")
    
    player_id = data.get('player_id')
    
    try:
        player = Player.objects.get(id=player_id)
    except Player.DoesNotExist:
        return json_error("Player not found")
    
    success, error = game_logic.claim_cooked(player)
    if error:
        return json_error(error)
    
    return JsonResponse({'status': 'cooked claimed'})


@csrf_exempt
@require_http_methods(["POST"])
def use_power(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return json_error("Invalid JSON")
    
    player_id = data.get('player_id')
    power = data.get('power')
    
    try:
        player = Player.objects.get(id=player_id)
    except Player.DoesNotExist:
        return json_error("Player not found")
    
    if power == '7':
        target_carrot_index = data.get('target_carrot_index')
        if target_carrot_index is None:
            return json_error("Target carrot index required")
        
        result = game_logic.use_power_seven(player, target_carrot_index)
        if len(result) == 2 and result[1]:
            return json_error(result[1])
        
        carrot = result[0]
        game_logic.get_next_turn(player.room)
        return JsonResponse({'carrot': carrot})
    
    elif power == '8':
        target_player_id = data.get('target_player_id')
        target_carrot_index = data.get('target_carrot_index')
        
        if not target_player_id or target_carrot_index is None:
            return json_error("Target player and carrot index required")
        
        result = game_logic.use_power_eight(player, target_player_id, target_carrot_index)
        if len(result) == 2 and result[1]:
            return json_error(result[1])
        
        carrot = result[0]
        game_logic.get_next_turn(player.room)
        return JsonResponse({'carrot': carrot})
    
    elif power == '9':
        carrot1_player_id = data.get('carrot1_player_id')
        carrot1_index = data.get('carrot1_index')
        carrot2_player_id = data.get('carrot2_player_id')
        carrot2_index = data.get('carrot2_index')
        
        if not all([carrot1_player_id, carrot1_index is not None, carrot2_player_id, carrot2_index is not None]):
            return json_error("All swap parameters required")
        
        success, error = game_logic.use_power_nine(
            player, carrot1_player_id, carrot1_index, carrot2_player_id, carrot2_index
        )
        if error:
            return json_error(error)
        
        game_logic.get_next_turn(player.room)
        return JsonResponse({'status': 'swap completed'})
    
    else:
        return json_error("Invalid power")


@csrf_exempt
@require_http_methods(["POST"])
def try_match(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return json_error("Invalid JSON")
    
    player_id = data.get('player_id')
    target_player_id = data.get('target_player_id')
    carrot_index = data.get('carrot_index')
    
    if not target_player_id or carrot_index is None:
        return json_error("Target player and carrot index required")
    
    try:
        player = Player.objects.get(id=player_id)
    except Player.DoesNotExist:
        return json_error("Player not found")
    
    matched, error = game_logic.try_match_carrot(player, target_player_id, carrot_index)
    if error:
        return json_error(error)
    
    return JsonResponse({'matched': matched})


@csrf_exempt
@require_http_methods(["GET"])
def scores(request, room_code):
    room_code = room_code.upper()
    
    try:
        room = Room.objects.get(code=room_code)
    except Room.DoesNotExist:
        return json_error("Room not found")
    
    scores = game_logic.calculate_scores(room)
    
    return JsonResponse({
        'room_code': room.code,
        'state': room.state,
        'scores': scores
    })
