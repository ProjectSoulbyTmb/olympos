class InvalidTransition(Exception):
    pass


class StateMachine:
    def __init__(self, states, transitions, initial):
        self.states = states
        self.transitions = transitions
        self.state = initial
        self.log = [("enter", initial, None)]
        enter = states[initial].get("on_enter")
        if enter:
            enter(None)

    def fire(self, event, payload=None):
        key = (self.state, event)
        if key not in self.transitions:
            raise InvalidTransition(
                f"no transition: state={self.state!r} event={event!r}"
            )
        target, guard = self.transitions[key]
        if guard is not None and not guard(payload):
            raise InvalidTransition(
                f"guard rejected: state={self.state!r} event={event!r} -> {target!r}"
            )
        exit_fn = self.states[self.state].get("on_exit")
        if exit_fn:
            exit_fn(payload)
        origin = self.state
        self.state = target
        self.log.append(("exit", origin, payload))
        enter_fn = self.states[target].get("on_enter")
        if enter_fn:
            enter_fn(payload)
        self.log.append(("enter", target, payload))
        return target

    def update(self, dt):
        update_fn = self.states[self.state].get("on_update")
        if update_fn:
            return update_fn(dt)
        return None
