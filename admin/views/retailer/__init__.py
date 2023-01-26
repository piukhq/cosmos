from flask_admin import Admin

from admin.db.session import db_session
from admin.views.retailer.main import (
    EmailTemplateAdmin,
    EmailTemplateKeyAdmin,
    RetailerAdmin,
    RetailerFetchTypeAdmin,
    RetailerStoreAdmin,
)
from cosmos.core.config import settings
from cosmos.db.models import EmailTemplate, EmailTemplateKey, Retailer, RetailerFetchType, RetailerStore


def register_retailer_admin(admin: "Admin") -> None:
    retailer_management = "Retailer"
    admin.add_view(
        RetailerAdmin(
            Retailer,
            db_session,
            "Retailers",
            endpoint=f"{settings.RETAILER_MENU_PREFIX}/retailer",
            category=retailer_management,
        )
    )
    admin.add_view(
        RetailerStoreAdmin(
            RetailerStore,
            db_session,
            "Retailer's Stores",
            endpoint=f"{settings.RETAILER_MENU_PREFIX}/retailer-stores",
            category=retailer_management,
        )
    )
    admin.add_view(
        RetailerFetchTypeAdmin(
            RetailerFetchType,
            db_session,
            "Retailer's Fetch Types",
            endpoint=f"{settings.RETAILER_MENU_PREFIX}/retailer-fetch-types",
            category=retailer_management,
        )
    )
    admin.add_view(
        EmailTemplateAdmin(
            EmailTemplate,
            db_session,
            "Email Templates",
            endpoint=f"{settings.RETAILER_MENU_PREFIX}/email-templates",
            category=retailer_management,
        )
    )
    admin.add_view(
        EmailTemplateKeyAdmin(
            EmailTemplateKey,
            db_session,
            "Email Template Keys",
            endpoint=f"{settings.RETAILER_MENU_PREFIX}/email-template-keys",
            category=retailer_management,
        )
    )
