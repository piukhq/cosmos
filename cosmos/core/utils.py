import logging
import random

from typing import TYPE_CHECKING, Any, Callable
from uuid import uuid4

from pydantic import UUID4
from pydantic.validators import str_validator
from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.utils.synchronous import enqueue_many_retry_tasks, sync_create_many_tasks

from cosmos.accounts.api.enums.http_error import HttpErrors
from cosmos.core.config import redis_raw, settings
from cosmos.db.base_class import sync_run_query
from cosmos.db.models import AccountHolderPendingReward

if TYPE_CHECKING:  # pragma: no cover
    from pydantic.typing import CallableGenerator  # pragma: no cover
    from sqlalchemy.orm import Session

MINIMUM_ACCOUNT_NUMBER_LENGTH = 10


def generate_account_number(prefix: str, number_length: int = MINIMUM_ACCOUNT_NUMBER_LENGTH) -> str:
    prefix = prefix.strip().upper()
    if not prefix.isalnum():
        raise ValueError("prefix is not alpha-numeric")
    if number_length < MINIMUM_ACCOUNT_NUMBER_LENGTH:
        raise ValueError(f"minimum card number length is {MINIMUM_ACCOUNT_NUMBER_LENGTH}")
    start, end = 1, (10**number_length) - 1
    return f"{prefix}{str(random.randint(start, end)).zfill(number_length)}"


class AccountHolderUUIDValidator(UUID4):
    @classmethod
    def __get_validators__(cls) -> "CallableGenerator":
        yield str_validator
        yield cls.validate

    @classmethod
    def validate(cls, value: str) -> UUID4:
        try:
            v = UUID4(value)
        except ValueError:
            raise HttpErrors.NO_ACCOUNT_FOUND.value  # pylint: disable=raise-missing-from
        else:
            return v


def enqueue_pending_rewards(
    db_session: "Session", query_func: Callable[[], list[AccountHolderPendingReward]], logger: logging.Logger
) -> None:
    while True:
        pending_rewards = sync_run_query(query_func, db_session, rollback_on_exc=False)
        if pending_rewards:
            logger.info(f"Processing {len(pending_rewards)} AccountHolderPendingRewards...")
            try:
                params_list = []

                for pending_reward in pending_rewards:

                    params_list.append(
                        {
                            "reward_slug": pending_reward.reward_slug,
                            "retailer_slug": pending_reward.retailer_slug,
                            "pending_reward_id": pending_reward.id,
                            "idempotency_token": str(uuid4()),
                            # This is informational only since the pending reward is deleted and
                            # consequentially this task's link to the account holder:
                            "account_holder_id": pending_reward.account_holder_id,
                        }
                    )
                    pending_reward.enqueued = True

                tasks = sync_create_many_tasks(
                    db_session, task_type_name=settings.PROCESS_PENDING_REWARD_TASK_NAME, params_list=params_list
                )
                # We have task ids here as sync_create_many_tasks calls flush(). We do not call commit here as
                # if the enqueuing was to fail, then each task would be marked as queued when it hadn't been. Instead,
                # we opt to commit once we know the enqueuing has succeeded, acknowledging that there is a small window
                # for an RQ worker to pick up the job prior to the task being committed to the db. This eventuality is
                # benign as the job will simply fail and we'd be left with PENDING retry tasks in the database.
                # If we encounter this in the future (it has not happened yet), an option would be to enqueue the tasks
                # a short time in the future so that the commit has time to happen prior to workers receiving the jobs
                # to run.
                enqueue_many_retry_tasks(
                    db_session, retry_tasks_ids=[task.retry_task_id for task in tasks], connection=redis_raw
                )
            except Exception as ex:  # pylint: disable=broad-except
                sync_run_query(
                    lambda: db_session.rollback(),  # pylint: disable=unnecessary-lambda
                    db_session,
                    rollback_on_exc=False,
                )
                logger.exception("Failed to enqueue pending rewards", exc_info=ex)
                break
            else:
                sync_run_query(
                    lambda: db_session.commit(), db_session, rollback_on_exc=False  # pylint: disable=unnecessary-lambda
                )
        else:
            logger.info("No AccountHolderPendingRewards to process.")
            break


def set_param_value(
    db_session: "Session", retry_task: RetryTask, param_name: str, param_value: Any, commit: bool = True
) -> str:
    def _query() -> str:
        key_ids_by_name = retry_task.task_type.get_key_ids_by_name()
        task_type_key_val = retry_task.get_task_type_key_values([(key_ids_by_name[param_name], param_value)])[0]
        db_session.add(task_type_key_val)
        if commit:
            db_session.commit()

        return task_type_key_val.value

    return sync_run_query(_query, db_session)
