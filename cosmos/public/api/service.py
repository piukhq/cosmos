from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import status

from cosmos.accounts.activity.enums import ActivityType as AccountsActivityType
from cosmos.core.activity.tasks import async_send_activity
from cosmos.core.api.crud import get_reward
from cosmos.core.api.service import Service, ServiceError, ServiceResult
from cosmos.core.error_codes import ErrorCode
from cosmos.core.prometheus import invalid_marketing_opt_out, microsite_reward_requests
from cosmos.public.activity.enums import ActivityType as PublicActivityType
from cosmos.public.api import crud
from cosmos.public.config import public_settings
from cosmos.retailers.crud import get_retailer_by_slug

if TYPE_CHECKING:  # pragma: no cover
    from cosmos.db.models import Reward
    from cosmos.public.api.schemas import AccountHolderEmailEvent

RESPONSE_TEMPLATE = """
<!DOCTYPE HTML>
<html lang="en">
    <head>
        <title>Marketing opt out</title>
    </head>
    <body>
        <p>{msg}</p>
    </body>
</html>
"""


class PublicService(Service):
    async def handle_marketing_unsubscribe(self, u: str | None) -> ServiceResult[str, ServiceError]:
        msg = "You have opted out of any further marketing"
        if u:
            try:
                opt_out_uuid = UUID(u)
            except ValueError:
                invalid_marketing_opt_out.labels(
                    app=public_settings.core.PROJECT_NAME, unknown_retailer=False, invalid_token=True
                ).inc()
                html_resp = RESPONSE_TEMPLATE.format(msg=msg)
                return ServiceResult(value=html_resp)

            data = await crud.get_account_holder_and_retailer_data_by_opt_out_token(
                self.db_session, opt_out_uuid=opt_out_uuid
            )
            if data is None:
                invalid_marketing_opt_out.labels(
                    app=public_settings.core.PROJECT_NAME, unknown_retailer=False, invalid_token=True
                ).inc()
            elif data.retailer_slug != self.retailer_slug:
                invalid_marketing_opt_out.labels(
                    app=public_settings.core.PROJECT_NAME, unknown_retailer=True, invalid_token=False
                ).inc()
            else:
                updates = await crud.update_boolean_marketing_preferences(
                    self.db_session, account_holder_id=data.account_holder_id
                )
                await self.commit_db_changes()
                msg += f" for {data.retailer_name}"

                for pref_name, updated_at in updates:
                    activity_payload = AccountsActivityType.get_marketing_preference_change_activity_data(
                        account_holder_uuid=data.account_holder_uuid,
                        retailer_slug=data.retailer_slug,
                        field_name=pref_name,
                        activity_datetime=updated_at,
                        summary="Unsubscribed via marketing opt-out",
                        associated_value="Marketing Preferences unsubscribed",
                        original_value="True",
                        new_value="False",
                    )
                    await self.trigger_asyncio_task(
                        async_send_activity(activity_payload, routing_key=AccountsActivityType.ACCOUNT_CHANGE.value)
                    )

        else:
            invalid_marketing_opt_out.labels(
                app=public_settings.core.PROJECT_NAME, unknown_retailer=False, invalid_token=True
            ).inc()

        html_resp = RESPONSE_TEMPLATE.format(msg=msg)
        return ServiceResult(value=html_resp)

    async def handle_get_reward_for_microsite(self, reward_uuid: str) -> ServiceResult["Reward", ServiceError]:
        try:
            valid_reward_uuid = UUID(reward_uuid)
        except ValueError:
            microsite_reward_requests.labels(
                app=public_settings.core.PROJECT_NAME,
                response_status=status.HTTP_404_NOT_FOUND,
                unknown_retailer=False,
                invalid_reward_uuid=True,
            ).inc()
            return ServiceResult(error=ServiceError(error_code=ErrorCode.INVALID_REQUEST))

        if retailer := await get_retailer_by_slug(self.db_session, retailer_slug=self.retailer_slug):
            if reward := await get_reward(self.db_session, reward_uuid=valid_reward_uuid, retailer_id=retailer.id):
                microsite_reward_requests.labels(
                    app=public_settings.core.PROJECT_NAME,
                    response_status=status.HTTP_200_OK,
                    unknown_retailer=False,
                    invalid_reward_uuid=False,
                ).inc()
                return ServiceResult(reward)
            return ServiceResult(error=ServiceError(error_code=ErrorCode.NO_REWARD_FOUND))

        microsite_reward_requests.labels(
            app=public_settings.core.PROJECT_NAME,
            response_status=status.HTTP_404_NOT_FOUND,
            unknown_retailer=retailer is None,
            invalid_reward_uuid=retailer is not None,
        ).inc()
        return ServiceResult(error=ServiceError(error_code=ErrorCode.INVALID_REQUEST))


class CallbackService(Service):
    async def handle_email_events(
        self, *, payload: "list[AccountHolderEmailEvent]"
    ) -> ServiceResult[dict, ServiceError]:
        for data in payload:
            await self._handle_email_event(payload=data)

        return ServiceResult({})

    async def _handle_email_event(self, *, payload: "AccountHolderEmailEvent") -> None:
        try:
            account_holder_uuid, retailer_slug = await crud.update_account_holder_email_status(
                self.db_session, payload.message_uuid, payload.event
            )
        except Exception:
            self.logger.exception(
                "Failed to update AccountHolderEmail with message_uuid %s with current_status %s",
                payload.message_uuid,
                payload.event,
            )

        else:
            await self.store_activity(
                activity_type=PublicActivityType.EMAIL_EVENT,
                payload_formatter_fn=PublicActivityType.get_email_event_activity_data,
                formatter_kwargs={
                    "event": payload.event,
                    "message_uuid": payload.message_uuid,
                    "underlying_timestamp": payload.event_datetime,
                    "retailer_slug": retailer_slug,
                    "account_holder_uuid": account_holder_uuid,
                    "payload": payload.dict(),
                },
            )
            await self.format_and_send_stored_activities()
