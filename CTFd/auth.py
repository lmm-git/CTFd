import logging

from flask import Blueprint
from flask import current_app as app
from flask import redirect, request, url_for

from CTFd.models import Users, db
from CTFd.utils import config, email
from CTFd.utils import user as current_user
from CTFd.utils import validators
from CTFd.utils.decorators import ratelimit
from CTFd.utils.decorators.visibility import check_registration_visibility
from CTFd.utils.logging import log
from CTFd.utils.security.auth import login_user, logout_user

from flask_oidc_ext import OpenIDConnect

auth = Blueprint("auth", __name__)

logging.basicConfig(level=logging.DEBUG)
app.config.update({
    'OIDC_CLIENT_SECRETS': 'client_secrets.json',
    'OIDC_ID_TOKEN_COOKIE_SECURE': True,
    'OIDC_REQUIRE_VERIFIED_EMAIL': True,
    'OIDC_USER_INFO_ENABLED': True,
    'OIDC_SCOPES': ['openid', 'email'],
})

oidc = OpenIDConnect(app)


@auth.route("/login", methods=["GET"])
@check_registration_visibility
@oidc.require_login
@ratelimit(method="POST", limit=10, interval=5)
def login():
    sub = oidc.user_getfield('sub')
    name = oidc.user_getfield('preferred_username')
    email_address = oidc.user_getfield('email')

    # Check whether user exists
    user = Users.query.filter_by(id=sub).first()
    if user:
        user.email = email_address
        login_user(user)
        db.session.commit()
        return redirect(url_for("challenges.listing"))
    else:
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
