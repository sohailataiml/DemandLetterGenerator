"""Role-based access control.

The identity source here is a header pair (``X-User-Id`` / ``X-User-Role``),
which is a **development stand-in only** — it trusts the caller. Before this
runs anywhere real, swap :func:`current_user` for a verified OIDC/session token
and keep the ``require_roles`` call sites exactly as they are.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from ..domain.enums import UserRole


@dataclass(frozen=True)
class CurrentUser:
    id: str
    role: UserRole

    @property
    def is_attorney(self) -> bool:
        return self.role in (UserRole.ATTORNEY, UserRole.ADMIN)


def current_user(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
) -> CurrentUser:
    if not x_user_id or not x_user_role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-User-Id and X-User-Role headers are required",
        )
    try:
        role = UserRole(x_user_role.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"unknown role {x_user_role!r}",
        ) from None
    return CurrentUser(id=x_user_id, role=role)


def require_roles(*allowed: UserRole):
    """Dependency factory guarding an endpoint by role."""

    permitted = set(allowed) | {UserRole.ADMIN}

    def _guard(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in permitted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"role {user.role.value!r} may not perform this action; "
                    f"requires one of {sorted(r.value for r in permitted)}"
                ),
            )
        return user

    return _guard


# Common guards, named for how they read at the call site.
can_read = require_roles(
    UserRole.ATTORNEY, UserRole.PARALEGAL, UserRole.REVIEWER, UserRole.READONLY
)
can_edit_case = require_roles(UserRole.ATTORNEY, UserRole.PARALEGAL)
can_verify_facts = require_roles(UserRole.ATTORNEY, UserRole.PARALEGAL, UserRole.REVIEWER)
can_approve = require_roles(UserRole.ATTORNEY)
