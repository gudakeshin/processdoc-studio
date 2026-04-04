from fastapi import APIRouter

from app.api import agent_bash, auth, documents, dpdp, formats, lp_library, memory, model_realtime_ws, models, projects, runs, skills, swarm, tasks

from app.api import drawio_collab, run_artifacts

router = APIRouter()
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(projects.router, prefix="/projects", tags=["projects"])
router.include_router(agent_bash.router, prefix="/projects", tags=["agent-bash"])
router.include_router(documents.router, prefix="/documents", tags=["documents"])
router.include_router(runs.router, prefix="/runs", tags=["runs"])
router.include_router(swarm.router, prefix="/runs", tags=["swarm"])
router.include_router(run_artifacts.router, prefix="/runs", tags=["run-artifacts"])
router.include_router(drawio_collab.router, prefix="/drawio", tags=["drawio-collab"])
router.include_router(model_realtime_ws.router, prefix="/ws", tags=["model-realtime-ws"])
router.include_router(skills.router, prefix="/workspace/{pid}/skills", tags=["skills"])
router.include_router(formats.router, prefix="/workspace/{pid}", tags=["output-types"])
router.include_router(lp_library.router, prefix="/lp-library", tags=["lp-library"])
router.include_router(dpdp.router, prefix="/dpdp", tags=["dpdp"])
router.include_router(memory.router, prefix="/memory", tags=["memory"])
router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
router.include_router(models.router, tags=["models"])
