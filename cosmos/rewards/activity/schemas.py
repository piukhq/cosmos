from uuid import UUID

from pydantic import BaseModel


class RewardStatusDataSchema(BaseModel):
    new_status: str
    original_status: str | None
    count: int | None


class RewardUpdateDataSchema(BaseModel):
    new_total_cost_to_user: int
    original_total_cost_to_user: int


class TotalCostToUserDataSchema(RewardUpdateDataSchema):
    pending_reward_id: int
    pending_reward_uuid: UUID