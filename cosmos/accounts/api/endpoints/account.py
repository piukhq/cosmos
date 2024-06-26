from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cosmos.accounts.api.schemas import (  # AccountHolderStatusResponseSchema,; AccountHolderUpdateStatusSchema,
    AccountHolderResponseSchema,
    AccountHolderUUIDValidator,
    GetAccountHolderByCredentials,
)
from cosmos.accounts.api.service import AccountService
from cosmos.accounts.config import account_settings
from cosmos.core.api.deps import RetailerDependency, UserIsAuthorised, bpl_channel_header_is_populated, get_session
from cosmos.db.models import Retailer

if TYPE_CHECKING:
    from cosmos.db.models import AccountHolder

get_retailer = RetailerDependency()
user_is_authorised = UserIsAuthorised(expected_token=account_settings.ACCOUNT_API_AUTH_TOKEN)

router = APIRouter(
    prefix=account_settings.ACCOUNT_API_PREFIX,
    dependencies=[Depends(user_is_authorised)],
)
bpl_operations_router = APIRouter(
    prefix=account_settings.ACCOUNT_API_PREFIX,
    dependencies=[Depends(user_is_authorised), Depends(bpl_channel_header_is_populated)],
)


@router.post(
    path="/{retailer_slug}/accounts/getbycredentials",
    response_model=AccountHolderResponseSchema,
)
async def get_account_holder_by_credentials(
    payload: GetAccountHolderByCredentials,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    retailer: Annotated[Retailer, Depends(get_retailer)],
    bpl_user_channel: str = Header(None),
    tx_qty: int = 10,
) -> "AccountHolder":
    service = AccountService(db_session=db_session, retailer=retailer)
    service_result = await service.handle_account_auth(payload, tx_qty=tx_qty, channel=bpl_user_channel)
    return service_result.handle_service_result()


@router.get(
    path="/{retailer_slug}/accounts/{account_holder_uuid}",
    response_model=AccountHolderResponseSchema,
)
async def get_account_holder(
    account_holder_uuid: AccountHolderUUIDValidator,
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    retailer: Annotated[Retailer, Depends(get_retailer)],
    tx_qty: int = 10,
) -> "AccountHolder":
    service = AccountService(db_session=db_session, retailer=retailer)
    service_result = await service.handle_get_account(
        account_holder_uuid=account_holder_uuid, retailer=retailer, request=request, tx_qty=tx_qty
    )
    return service_result.handle_service_result()
