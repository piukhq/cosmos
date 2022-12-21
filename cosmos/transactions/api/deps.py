from contextlib import suppress

from fastapi import Depends, Header, HTTPException
from starlette import status

from cosmos.core.config import settings


def get_authorization_token(authorization: str = Header(None)) -> str:
    with suppress(ValueError, AttributeError):
        token_type, token_value = authorization.split(" ")
        if token_type.lower() == "token":
            return token_value

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "display_message": "Supplied token is invalid.",
            "code": "INVALID_TOKEN",
        },
    )


# user as in user of our api, not an account holder.
def user_is_authorised(token: str = Depends(get_authorization_token)) -> None:
    if not token == settings.VELA_API_AUTH_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "display_message": "Supplied token is invalid.",
                "code": "INVALID_TOKEN",
            },
        )
