from fastapi import APIRouter

from app.api.v1 import admin, auth, banking, mobile

# everything in this package is served under /api/v1
# a breaking change later would go to a new v2 package, v1 stays as it is
router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(mobile.router)
router.include_router(banking.router)
router.include_router(admin.router)
