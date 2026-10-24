import json
from urllib.parse import urlencode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from .security import acquire, identity
from .services.conversation import STATE_KEY, DRAFT_KEY, state_for, current_options
from .services.openai_service import InterpretationError
from .services.orchestrator import BookingOrchestrator, BookingSelectionError, consume_draft


def failure(message, status):
    return JsonResponse({'message': message, 'fallback_url': reverse('courts:establecimientos')}, status=status)


def payload(request, key, maximum):
    if request.content_type != 'application/json' or len(request.body) > 4096:
        raise ValueError
    data = json.loads(request.body)
    if not isinstance(data, dict) or set(data) != {key} or not isinstance(data[key], str):
        raise ValueError
    value = data[key].strip()
    if not value or len(value) > maximum:
        raise ValueError
    return value


@never_cache
@require_GET
@ensure_csrf_cookie
def state(request):
    identity(request)
    context = state_for(request.session)
    return JsonResponse({'message': context.get('last_message') or '¡Hola! Te ayudo a encontrar una cancha. ¿Para qué día quieres jugar?',
                         'options': current_options(context), 'csrf_token': get_token(request)})


@never_cache
@require_POST
def message(request):
    try:
        text = payload(request, 'message', 500)
    except (ValueError, UnicodeDecodeError):
        return failure('Escribe un mensaje de entre 1 y 500 caracteres.', 400)
    lock = acquire(request)
    if not lock:
        response = failure('Espera un momento antes de volver a consultar.', 429)
        response['Retry-After'] = '60'
        return response
    try:
        return JsonResponse(BookingOrchestrator().reply(request.session, text))
    except InterpretationError:
        return failure('El asistente no está disponible ahora. Puedes consultar los establecimientos directamente.', 503)
    finally:
        cache.delete(lock)


@never_cache
@require_POST
def select(request):
    try:
        option_id = payload(request, 'option_id', 80)
        BookingOrchestrator.select(request.session, option_id)
        if request.user.is_authenticated:
            url = consume_draft(request.session)
        else:
            url = reverse('users:login') + '?' + urlencode({'next': reverse('chatbot:resume')})
        return JsonResponse({'redirect_url': url, 'requires_login': not request.user.is_authenticated})
    except (ValueError, UnicodeDecodeError):
        return failure('La opción no es válida.', 400)
    except BookingSelectionError:
        request.session.pop(DRAFT_KEY, None)
        return failure('Ese horario cambió o la opción venció. Busca disponibilidad nuevamente.', 409)


@never_cache
@require_POST
def reset(request):
    request.session.pop(STATE_KEY, None)
    request.session.pop(DRAFT_KEY, None)
    return JsonResponse({'message': 'Empecemos de nuevo. ¿Para qué día quieres jugar?', 'options': []})


@never_cache
@login_required
@require_GET
def resume(request):
    try:
        return redirect(consume_draft(request.session))
    except BookingSelectionError:
        messages.info(request, 'El horario cambió o la selección venció. Consulta la disponibilidad nuevamente.')
        return redirect('courts:establecimientos')
