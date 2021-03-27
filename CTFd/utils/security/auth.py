import datetime
import os
from urllib.parse import quote

from flask import session, redirect, url_for

from CTFd.cache import clear_user_session
from CTFd.exceptions import UserNotFoundException, UserTokenExpiredException
from CTFd.models import UserTokens, db
from CTFd.utils.encoding import hexencode
from CTFd.utils.security.csrf import generate_nonce


def login_user(user):
    session["id"] = user.id
    session["nonce"] = generate_nonce()

    # Clear out any currently cached user attributes
    clear_user_session(user_id=user.id)


def update_user(user):
    session["id"] = user.id

    # Clear out any currently cached user attributes
    clear_user_session(user_id=user.id)


def logout_user():
    from CTFd.auth import oidc
    session.clear()
    oidc.logout()
    if 'end_session_endpoint' in oidc.client_secrets:
        return redirect(f'{oidc.client_secrets["end_session_endpoint"]}'
                        f'?redirect_uri={quote(url_for("views.static_html", _external=True))}')
    return None


def generate_user_token(user, expiration=None):
    temp_token = True
    while temp_token is not None:
        value = hexencode(os.urandom(32))
        temp_token = UserTokens.query.filter_by(value=value).first()

    token = UserTokens(user_id=user.id, expiration=expiration, value=value)
    db.session.add(token)
    db.session.commit()
    return token


def lookup_user_token(token):
    token = UserTokens.query.filter_by(value=token).first()
    if token:
        if datetime.datetime.utcnow() >= token.expiration:
            raise UserTokenExpiredException
        return token.user
    else:
        raise UserNotFoundException
    return None
