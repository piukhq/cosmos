import json

from typing import TYPE_CHECKING

from flask import Markup, url_for

from admin.views.model_views import BaseModelView
from cosmos.db.models import (
    AccountHolderProfile,
    Campaign,
    CampaignBalance,
    EarnRule,
    PendingReward,
    RetailerFetchType,
    RetailerStore,
    Reward,
    RewardConfig,
    RewardRule,
)

if TYPE_CHECKING:
    from flask_admin.contrib.sqla import ModelView
    from jinja2.runtime import Context
    from sqlalchemy.ext.automap import AutomapBase


def format_json_field(_v: type["ModelView"], _c: "Context", model: type["AutomapBase"], p: str) -> str:
    return (
        Markup("<pre>") + Markup.escape(json.dumps(getattr(model, p), indent=2, ensure_ascii=False)) + Markup("</pre>")
    )


def account_holder_repr(
    _v: type[BaseModelView],
    _c: "Context",
    model: AccountHolderProfile | Reward | CampaignBalance,
    _p: str,
) -> str:
    return Markup(
        (
            "<strong><a href='{}'>ID:</a></strong>&nbsp;{}<br />"
            "<strong>Email:</strong>&nbsp;{}<br />"
            "<strong>UUID:</strong>&nbsp;{}"
        ).format(
            url_for("accounts/account-holders.details_view", id=model.account_holder.id),
            model.account_holder.id,
            model.account_holder.email,
            model.account_holder.account_holder_uuid,
        )
    )


def retailer_slug_repr(
    _v: type[BaseModelView],
    _c: "Context",
    model: Campaign | EarnRule | RewardRule | RewardConfig | RetailerStore,
    _p: str,
) -> str:
    if isinstance(model, (EarnRule, RewardRule)):
        return model.campaign.retailer.slug
    elif isinstance(model, RetailerFetchType):
        return model.fetch_type.retailer.slug
    return model.retailer.slug


def campaign_slug_repr(
    _v: type[BaseModelView],
    _c: "Context",
    model: PendingReward,
    _p: str,
) -> str:
    return model.campaign.slug


def account_holder_export_repr(
    _v: type[BaseModelView],
    _c: "Context",
    model: Reward | PendingReward,
    _p: str,
) -> str:
    return model.account_holder.account_holder_uuid