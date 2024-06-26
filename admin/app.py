import logging

from typing import Any

import sentry_sdk

from authlib.integrations.flask_client import OAuth
from flask import Blueprint, Flask, Response
from flask_wtf.csrf import CSRFProtect
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from admin.config import admin_settings
from admin.version import __version__
from admin.views import main_admin
from admin.views.model_views import BaseModelView
from cosmos.core.config import redis_raw
from cosmos.db.session import scoped_db_session

oauth = OAuth()
oauth.register(
    "cosmos_admin",
    server_metadata_url=admin_settings.OAUTH_SERVER_METADATA_URL,
    client_kwargs={"scope": "openid profile email"},
)


class RelativeLocationHeaderResponse(Response):
    # Below setting allows relative location headers, allowing us to redirect
    # without having to hardcode the Azure Front Door host to all redirects
    autocorrect_location_header = False


def create_app(with_activities: bool = True) -> Flask:

    from retry_tasks_lib.admin.views import register_tasks_admin

    from admin.views.accounts import register_customer_admin
    from admin.views.auth import auth_bp
    from admin.views.campaign_reward import register_campaign_and_reward_management_admin
    from admin.views.healthz import healthz_bp
    from admin.views.retailer import register_retailer_admin
    from admin.views.transactions import register_transactions_admin

    sqla_logger = logging.getLogger("sqlalchemy.engine")
    sqla_logger.setLevel(admin_settings.ADMIN_QUERY_LOG_LEVEL)
    sqla_handler = logging.StreamHandler()
    sqla_handler.setLevel(level=admin_settings.ADMIN_QUERY_LOG_LEVEL)
    sqla_logger.addHandler(sqla_handler)

    if admin_settings.core.SENTRY_DSN is not None:
        sentry_sdk.init(
            dsn=admin_settings.core.SENTRY_DSN,
            integrations=[FlaskIntegration(), SqlalchemyIntegration()],
            environment=admin_settings.core.SENTRY_ENV,
            release=__version__,
            traces_sample_rate=0.0,
        )

    app = Flask(__name__)
    app.config.from_object(admin_settings)
    app.response_class = RelativeLocationHeaderResponse

    register_customer_admin(main_admin)
    register_retailer_admin(main_admin)
    register_campaign_and_reward_management_admin(main_admin)
    register_transactions_admin(main_admin)
    register_tasks_admin(
        admin=main_admin, scoped_db_session=scoped_db_session, admin_base_classes=(BaseModelView,), redis=redis_raw
    )

    if with_activities:
        from admin.hubble.db.models import Base as HubbleModelBase
        from admin.hubble.db.session import activity_engine, activity_scoped_session
        from admin.views.activity import register_hubble_admin

        HubbleModelBase.prepare(activity_engine, reflect=True)
        register_hubble_admin(main_admin)
        register_tasks_admin(
            admin=main_admin,
            scoped_db_session=activity_scoped_session,
            admin_base_classes=(BaseModelView,),
            redis=redis_raw,
            endpoint_prefix="activity-",
            url_prefix="activity",
            menu_title="Activity",
        )

        @app.teardown_appcontext
        def remove_hubble_session(exception: BaseException | None = None) -> Any:  # noqa: ARG001, ANN401
            activity_scoped_session.remove()

    main_admin.init_app(app)
    oauth.init_app(app)
    CSRFProtect(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(healthz_bp)

    eh_bp = Blueprint(
        "eh", __name__, static_url_path=f"{admin_settings.ADMIN_ROUTE_BASE}/eh/static", static_folder="static"
    )
    app.register_blueprint(eh_bp)

    @app.teardown_appcontext
    def remove_cosmos_session(exception: BaseException | None = None) -> Any:  # noqa: ARG001, ANN401
        scoped_db_session.remove()

    return app
