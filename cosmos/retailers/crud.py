from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, joinedload

from cosmos.db.models import Campaign, Retailer


async def get_retailer_by_slug(
    db_session: AsyncSession, retailer_slug: str, with_campaign_data: bool = False, lock_row: bool = False
) -> Retailer | None:

    stmt = select(Retailer).where(Retailer.slug == retailer_slug)
    if lock_row:
        stmt = stmt.with_for_update()
    elif with_campaign_data:
        stmt = (
            stmt.outerjoin(Retailer.campaigns)
            .outerjoin(Retailer.stores)
            .options(
                contains_eager(Retailer.stores),
                contains_eager(Retailer.campaigns).options(
                    joinedload(Campaign.reward_rule),
                    joinedload(Campaign.earn_rule),
                ),
            )
        )
    return (await db_session.execute(stmt)).unique().scalar_one_or_none()
