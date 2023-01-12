from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import NonNegativeInt

from cosmos.accounts.activity.schemas import (
    AccountEventSchema,
    AccountRequestSchema,
    BalanceChangeDataSchema,
    MarketingPreferenceChangeSchema,
    RefundNotRecoupedDataSchema,
)
from cosmos.core.activity.enums import ActivityTypeMixin
from cosmos.core.activity.utils import pence_integer_to_currency_string
from cosmos.core.config import settings


class ActivityType(ActivityTypeMixin, Enum):
    ACCOUNT_REQUEST = f"activity.{settings.PROJECT_NAME}.account.request"
    ACCOUNT_ENROLMENT = f"activity.{settings.PROJECT_NAME}.account.enrolment"
    ACCOUNT_AUTHENTICATION = f"activity.{settings.PROJECT_NAME}.account.authentication"
    ACCOUNT_CHANGE = f"activity.{settings.PROJECT_NAME}.account.change"
    BALANCE_CHANGE = f"activity.{settings.PROJECT_NAME}.balance.change"
    REFUND_NOT_RECOUPED = f"activity.{settings.PROJECT_NAME}.refund.not.recouped"

    @classmethod
    def get_account_request_activity_data(
        cls,
        *,
        activity_datetime: datetime,
        retailer_slug: str,
        channel: str,
        request_data: dict,
        retailer_profile_config: dict,
        result: str | None,
    ) -> dict:
        fields = [
            {"field_name": k, "value": str(v)}
            for k, v in request_data["credentials"].items()
            if k in retailer_profile_config
        ]
        marketing_prefs: list[dict] = request_data.get("marketing_preferences", [])
        if marketing_prefs:
            fields.extend([{"field_name": pref["key"], "value": pref["value"]} for pref in marketing_prefs])
        email = request_data["credentials"]["email"]
        return cls._assemble_payload(
            ActivityType.ACCOUNT_REQUEST.name,
            user_id=str(request_data["third_party_identifier"]),
            activity_datetime=activity_datetime,
            summary=f"Enrolment Requested for {email}",
            associated_value=email,
            retailer_slug=retailer_slug,
            data=AccountRequestSchema(datetime=activity_datetime, channel=channel, fields=fields, result=result).dict(),
        )

    @classmethod
    def get_account_authentication_activity_data(
        cls,
        *,
        account_holder_uuid: UUID | str,
        activity_datetime: datetime,
        retailer_slug: str,
        channel: str,
    ) -> dict:
        return cls._assemble_payload(
            ActivityType.ACCOUNT_AUTHENTICATION.name,
            user_id=account_holder_uuid,
            activity_datetime=activity_datetime,
            summary=f"Account added to {channel}",
            associated_value=channel,
            retailer_slug=retailer_slug,
            data=AccountEventSchema(datetime=activity_datetime, channel=channel).dict(),
        )

    @classmethod
    def get_account_enrolment_activity_data(
        cls,
        *,
        account_holder_uuid: UUID | str,
        activity_datetime: datetime,
        retailer_slug: str,
        channel: str,
        third_party_identifier: str,
    ) -> dict:
        return cls._assemble_payload(
            ActivityType.ACCOUNT_ENROLMENT.name,
            user_id=account_holder_uuid,
            activity_datetime=activity_datetime,
            summary=f"Joined via {channel}; Account activated",
            reasons=[f"Third Party Identifier: {third_party_identifier}"],
            activity_identifier=third_party_identifier,
            associated_value=channel,
            retailer_slug=retailer_slug,
            data=AccountEventSchema(datetime=activity_datetime, channel=channel).dict(),
        )

    @classmethod
    def get_marketing_preference_change_activity_data(
        cls,
        *,
        account_holder_uuid: UUID | str,
        retailer_slug: str,
        activity_datetime: datetime,
        summary: str,
        associated_value: str,
        field_name: str,
        original_value: str,
        new_value: str,
    ) -> dict:
        return cls._assemble_payload(
            ActivityType.ACCOUNT_CHANGE.name,
            activity_datetime=activity_datetime,
            user_id=account_holder_uuid,
            retailer_slug=retailer_slug,
            summary=summary,
            associated_value=associated_value,
            data=MarketingPreferenceChangeSchema(
                field_name=field_name, original_value=original_value, new_value=new_value
            ).dict(),
        )

    @classmethod
    def get_balance_change_activity_data(
        cls,
        *,
        account_holder_uuid: UUID | str,
        retailer_slug: str,
        summary: str,
        new_balance: int,
        campaigns: list[str],
        reason: str,
        activity_datetime: datetime,
        original_balance: int,
    ) -> dict:

        return cls._assemble_payload(
            ActivityType.BALANCE_CHANGE.name,
            user_id=account_holder_uuid,
            activity_datetime=activity_datetime,
            activity_identifier="N/A",
            summary=summary,
            reasons=[reason],
            associated_value=str(new_balance),
            retailer_slug=retailer_slug,
            campaigns=campaigns,
            data=BalanceChangeDataSchema(new_balance=new_balance, original_balance=original_balance).dict(
                exclude_unset=True
            ),
        )

    @classmethod
    def get_refund_not_recouped_activity_data(
        cls,
        *,
        account_holder_uuid: UUID | str,
        activity_datetime: datetime,
        retailer_slug: str,
        campaigns: list[str],
        adjustment: int,
        amount_recouped: int,
        amount_not_recouped: NonNegativeInt,
    ) -> dict:
        return cls._assemble_payload(
            ActivityType.REFUND_NOT_RECOUPED.name,
            user_id=account_holder_uuid,
            activity_datetime=activity_datetime,
            summary=f"{retailer_slug} Refund transaction caused an account shortfall",
            reasons=["Account Holder Balance and/or Pending Rewards did not cover the refund"],
            associated_value=pence_integer_to_currency_string(adjustment, "GBP"),
            retailer_slug=retailer_slug,
            campaigns=campaigns,
            data=RefundNotRecoupedDataSchema(
                datetime=activity_datetime,
                amount=adjustment,
                amount_recouped=amount_recouped,
                amount_not_recouped=amount_not_recouped,
            ).dict(),
        )