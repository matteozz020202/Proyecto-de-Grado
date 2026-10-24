import time

STATE_KEY = 'booking_chat_state'
DRAFT_KEY = 'chatbot_booking_draft'
STATE_TTL = 1800
OPTION_TTL = 600


def state_for(session):
    state = session.get(STATE_KEY, {})
    if not isinstance(state, dict) or time.time() - state.get('updated_at', 0) > STATE_TTL:
        return {'preferences': {}, 'options': {}, 'last_message': ''}
    return state


def save_state(session, state):
    state['updated_at'] = time.time()
    session[STATE_KEY] = state


def option_token():
    import secrets
    return secrets.token_urlsafe(18)


def current_options(state):
    if time.time() - state.get('options_at', 0) > OPTION_TTL:
        return []
    return list(state.get('options', {}).values())
