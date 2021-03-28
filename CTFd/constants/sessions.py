from flask import session


class _SessionWrapper:
    @property
    def id(self):
        if session.get('sub'):
            return session.get('sub')
        return None

    @property
    def nonce(self):
        return session.get("nonce")

    @property
    def hash(self):
        return session.get("hash")


Session = _SessionWrapper()
