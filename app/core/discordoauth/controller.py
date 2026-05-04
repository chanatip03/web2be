from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.utils.validator import get_current_user
from .repository import (
    get_student_by_discord_user_id,
    get_student_by_user_id,
    link_discord_user,
)
from .service import (
    build_discord_authorize_url,
    exchange_code_for_user,
    generate_oauth_state,
    FRONTEND_URL,
)

router = APIRouter(prefix="/discord", tags=["discord"])


@router.get("/connect")
async def connect_discord(
    current_user: dict = Depends(get_current_user),
):
    role = current_user.get("role")
    if role and role.lower() != "student":
        raise HTTPException(
            status_code=403,
            detail="Only students can link Discord account",
        )

    state = generate_oauth_state(current_user["id"])
    authorize_url = build_discord_authorize_url(state)

    response = RedirectResponse(url=authorize_url)
    response.set_cookie(
        key="discord_oauth_state",
        value=state,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=600,
        path="/",
    )
    return response


@router.get("/callback")
async def discord_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")

    saved_state = request.cookies.get("discord_oauth_state")
    if not state or not saved_state or state != saved_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    from .service import decode_oauth_state
    decoded = decode_oauth_state(state)
    if not decoded or "uid" not in decoded:
        raise HTTPException(status_code=400, detail="Invalid OAuth state payload")
        
    user_id = decoded["uid"]

    student = get_student_by_user_id(db, user_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    discord_user = await exchange_code_for_user(code)
    discord_user_id = discord_user["id"]

    existing = get_student_by_discord_user_id(db, discord_user_id)
    if existing and existing.user_id != user_id:
        raise HTTPException(
            status_code=400,
            detail="Discord account already linked to another user",
        )

    updated_student = link_discord_user(
        db=db,
        user_id=user_id,
        discord_user_id=discord_user_id,
    )
    if not updated_student:
        raise HTTPException(status_code=404, detail="Student not found")

    if FRONTEND_URL:
        response = RedirectResponse(
            url=f"{FRONTEND_URL}?discord=linked",
            status_code=302,
        )
        response.delete_cookie("discord_oauth_state", path="/")
        return response

    response = JSONResponse(
        {
            "message": "Discord linked successfully",
            "discord_user_id": updated_student.discord_user_id,
        }
    )
    response.delete_cookie("discord_oauth_state", path="/")
    return response
