from django.urls import path
from . import views

urlpatterns = [
    path('create-room/', views.create_room, name='create_room'),
    path('join-room/', views.join_room, name='join_room'),
    path('start-game/', views.start_game, name='start_game'),
    path('game-state/<str:room_code>/', views.game_state, name='game_state'),
    path('draw-card/', views.draw_card, name='draw_card'),
    path('discard-card/', views.discard_card, name='discard_card'),
    path('replace-carrot/', views.replace_carrot_view, name='replace_carrot'),
    path('claim-cooked/', views.claim_cooked_view, name='claim_cooked'),
    path('use-power/', views.use_power, name='use_power'),
    path('try-match/', views.try_match, name='try_match'),
    path('scores/<str:room_code>/', views.scores, name='scores'),
]
