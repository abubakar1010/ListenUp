"""HTTP routes of the identity module (Architecture 9.2: Auth and Account)."""

import uuid

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from listenup.modules.identity import service
from listenup.modules.identity.service import AccountsDep, CurrentLearner
from listenup.platform.database import DbSession

router = APIRouter(tags=["identity"])


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1000)


class Me(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    email_verified: bool


@router.post("/auth/register", status_code=201)
async def register(
    body: Credentials,
    request: Request,
    response: Response,
    session: DbSession,
    accounts: AccountsDep,
) -> Me:
    learner = await accounts.register(session, request, response, body.email, body.password)
    return Me.model_validate(await service.get_profile(session, learner))


@router.post("/auth/login")
async def login(
    body: Credentials,
    request: Request,
    response: Response,
    session: DbSession,
    accounts: AccountsDep,
) -> Me:
    learner = await accounts.sign_in(session, request, response, body.email, body.password)
    return Me.model_validate(await service.get_profile(session, learner))


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request, response: Response, session: DbSession, accounts: AccountsDep
) -> None:
    await accounts.sign_out(session, request, response)


@router.get("/me")
async def me(learner: CurrentLearner, session: DbSession) -> Me:
    return Me.model_validate(await service.get_profile(session, learner))
