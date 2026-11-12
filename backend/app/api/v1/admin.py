from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AdminUserDep, AuthServiceDep, SessionDep
from app.core.exceptions import InvalidAuthRequestError
from app.domain.schemas import AdminUserOut, AdminUserUpdate
from app.repositories.users import UserRepository

router = APIRouter()


@router.get("/admin/users", response_model=list[AdminUserOut])
async def list_users(
    _admin: AdminUserDep, session: SessionDep
) -> list[AdminUserOut]:
    users = await UserRepository(session).list()
    return [AdminUserOut.model_validate(user) for user in users]


@router.patch("/admin/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    admin: AdminUserDep,
    service: AuthServiceDep,
) -> AdminUserOut:
    if user_id == admin.id and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admins cannot disable their own account",
        )

    try:
        user = await service.set_user_active(user_id, payload.is_active)
    except InvalidAuthRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        ) from exc

    return AdminUserOut.model_validate(user)
