from flask import session

from CTFd.auth import oidc


class _SessionWrapper:
    @property
    def id(self):
        if not oidc.user_loggedin:
            return None
        return oidc.user_getfield('sub')

    @property
    def nonce(self):
        return session.get("nonce")

    @property
    def hash(self):
        return session.get("hash")


Session = _SessionWrapper()
