import logging
import os
from os import getenv

import requests
from flask import Blueprint, abort, session
from flask import current_app as app
from flask import redirect, request, url_for
from requests_oauthlib import OAuth2Session

from CTFd.config import Config
from CTFd.constants.config import RegistrationVisibilityTypes, ConfigTypes
from CTFd.models import Users, db
from CTFd.utils import config, email, get_config
from CTFd.utils import user as current_user
from CTFd.utils import validators
from CTFd.utils.config import is_setup
from CTFd.utils.decorators import ratelimit
from CTFd.utils.logging import log
from CTFd.utils.security.auth import login_user, logout_user

auth = Blueprint("auth", __name__)

logging.basicConfig(level=logging.DEBUG)

if Config.OAUTH_CLIENT_BASE_URI:
    auth_well_known = requests.get(f'{Config.OAUTH_CLIENT_BASE_URI}/.well-known/openid-configuration').json()
else:
    auth_well_known = None

# Enable insecure transport for development
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = getenv('FLASK_DEBUG', '0')


@auth.route("/login", methods=["GET"])
@ratelimit(method="GET", limit=10, interval=5)
def login():
    if not auth_well_known:
        return abort(500), 'OAUTH not configured'

    oauth = OAuth2Session(Config.OAUTH_CLIENT_ID, redirect_uri=url_for('auth.authorize', _external=True),
                          scope=['openid', 'email'])

    authorization_url, state = oauth.authorization_url(auth_well_known['authorization_endpoint'])

    session['oauth_state'] = state
    return redirect(authorization_url)


@auth.route("/login/authorize", methods=["GET"])
@ratelimit(method="GET", limit=10, interval=5)
def authorize():
    if not auth_well_known:
        return abort(500), 'OAUTH not configured'

    oauth = OAuth2Session(Config.OAUTH_CLIENT_ID, state=session['oauth_state'],
                          redirect_uri=url_for('auth.authorize', _external=True))
    token = oauth.fetch_token(auth_well_known['token_endpoint'], client_secret=Config.OAUTH_CLIENT_SECRET,
                              authorization_response=request.url)

    session['oauth_token'] = token
    user_data_req = oauth.get(auth_well_known['userinfo_endpoint'])
    if user_data_req.status_code != 200:
        return abort(403), "Userinfo did not return 200"
    user_data = user_data_req.json()

    sub = user_data['sub']
    name = user_data['preferred_username']
    email_address = user_data['email']

    # Check whether user exists
    user = Users.query.filter_by(id=sub).first()
    if user:
        user.email = email_address
        login_user(user)
        db.session.commit()
    else:
        # Check whether new registrations are allowed
        v = get_config(ConfigTypes.REGISTRATION_VISIBILITY)
        # Allow signups during setup
        if (v == RegistrationVisibilityTypes.PRIVATE or v != RegistrationVisibilityTypes.PUBLIC) and is_setup():
            logout_user()
            return abort(403)

        with app.app_context():
            user = Users(id=sub, name=name, email=email_address)

            db.session.add(user)
            db.session.commit()
            db.session.flush()

            db.session.commit()

            login_user(user)

            if config.can_send_mail():  # We want to notify the user that they have registered.
                email.successful_registration_notification(user.email)

            log(
                "registrations",
                format="[{date}] {ip} - {name} registered with {email}",
                name=user.name,
                email=user.email,
            )
            db.session.close()

    session['sub'] = user_data['sub']
    session['groups'] = user_data['groups']

    if request.args.get("next") and validators.is_safe_url(
            request.args.get("next")
    ):
        return redirect(request.args.get("next"))

    return redirect(url_for("challenges.listing"))


@auth.route("/logout")
def logout():
    if current_user.authed():
        logout_result = logout_user()
        if logout_result:
            return logout_result
    return redirect(url_for("views.static_html"))
