from pathlib import Path
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.models.agent import Agent
from app.models.ticket import TicketSession, CSATRating
from app.models.cart import CustomerCart

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def render_dashboard(request: Request, db: Session):
    agents_raw = db.query(Agent).filter(Agent.is_active == True).all()
    total_agents = len(agents_raw)
    total_resolved = sum(a.tickets_resolved for a in agents_raw)

    agents_data = []
    total_ratings = 0
    rating_sum = 0.0

    for a in agents_raw:
        avg_seconds = (a.total_time_seconds // a.tickets_resolved) if a.tickets_resolved > 0 else 0
        mins, secs = avg_seconds // 60, avg_seconds % 60
        time_str = f"{mins}m {secs}s" if a.tickets_resolved > 0 else "N/A"

        csat_avg = db.query(func.avg(CSATRating.rating)).filter(CSATRating.agent_id == a.telegram_id).scalar() or 0.0
        csat_count = db.query(CSATRating).filter(CSATRating.agent_id == a.telegram_id).count()

        if csat_count > 0:
            rating_sum += csat_avg * csat_count
            total_ratings += csat_count

        agents_data.append({
            "name": a.name,
            "id": a.telegram_id,
            "resolved": a.tickets_resolved,
            "avg_time": time_str,
            "rating_str": f"⭐ {csat_avg:.1f} ({csat_count} ratings)" if csat_count > 0 else "No ratings yet"
        })

    avg_csat = round(rating_sum / total_ratings, 1) if total_ratings > 0 else 5.0

    metrics = {
        "total_agents": total_agents,
        "total_resolved": total_resolved,
        "avg_csat": avg_csat,
        "agents": agents_data
    }
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"metrics": metrics})

@router.get("/", response_class=HTMLResponse)
def root_view(request: Request, db: Session = Depends(get_db)):
    return render_dashboard(request, db)

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_view(request: Request, db: Session = Depends(get_db)):
    return render_dashboard(request, db)

@router.post("/dashboard/add-agent")
def add_agent_view(name: str = Form(...), telegram_id: str = Form(...), db: Session = Depends(get_db)):
    existing = db.query(Agent).filter(Agent.telegram_id == telegram_id).first()
    if existing:
        existing.name = name
        existing.is_active = True
    else:
        db.add(Agent(telegram_id=telegram_id, name=name))
    db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)
