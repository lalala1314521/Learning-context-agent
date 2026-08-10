"""FSRS scheduling with a local fallback implementation."""

import math
from datetime import datetime, timedelta


def _days_between(last: str | None, now: datetime) -> float:
    if not last:
        return 0.0
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if last_dt.tzinfo is not None:
            now = now.replace(tzinfo=last_dt.tzinfo)
        return max(0.0, (now - last_dt).total_seconds() / 86400.0)
    except Exception:
        return 0.0


def schedule_review(
    state: dict,
    rating: int,
    now: datetime | None = None,
) -> dict:
    """Return next scheduling state for an FSRS rating (0=again..3=easy)."""
    now = now or datetime.now()
    rating = max(0, min(3, int(rating)))
    try:
        from fsrs import FSRS, Card, Rating
        f = FSRS()
        card = Card(
            stability=float(state.get("stability") or 1.0),
            difficulty=float(state.get("difficulty") or 5.0),
            elapsed_days=0,
            scheduled_days=float(state.get("interval_days") or 1),
            reps=int(state.get("repetitions") or 0),
            lapses=int(state.get("lapses") or 0),
            state="review",
            due=datetime.now(),
        )
        ratings = [Rating.Again, Rating.Hard, Rating.Good, Rating.Easy]
        scheduling = f.review_card(card, ratings[rating])
        item = scheduling[0] if isinstance(scheduling, list) else scheduling
        interval = max(1, round(getattr(item, "scheduled_days", 1)))
        stability = float(getattr(item, "stability", 1.0))
        difficulty = float(getattr(item, "difficulty", 5.0))
        status = "learning" if rating == 0 else "review"
        if rating >= 2 and stability >= 10:
            status = "mastered"
        return {
            "status": status,
            "repetitions": max(0, int(state.get("repetitions") or 0) + (1 if rating >= 2 else 0)),
            "interval_days": interval,
            "ease_factor": max(1.3, 2.5 - (difficulty - 5.0) * 0.2),
            "difficulty": difficulty,
            "stability": stability,
            "retrievability": max(0.0, math.exp(math.log(0.9) * interval / max(stability, 0.1))),
            "due_at": now + timedelta(days=interval),
            "last_reviewed_at": now,
            "lapses": max(0, int(state.get("lapses") or 0) + (1 if rating == 0 else 0)),
        }
    except ImportError:
        return _local_schedule(state, rating, now)
    except Exception:
        return _local_schedule(state, rating, now)


def _local_schedule(state: dict, rating: int, now: datetime) -> dict:
    delta_days = _days_between(state.get("last_reviewed_at"), now) or 1.0
    difficulty = float(state.get("difficulty") or 5.0)
    stability = float(state.get("stability") or 1.0)
    retrievability = math.exp(-delta_days / max(stability, 0.1))
    repetitions = int(state.get("repetitions") or 0)

    if rating == 0:
        stability = max(0.5, stability * 0.3)
        difficulty = min(10.0, difficulty + 1.0)
        interval = 1
        repetitions = 0
        status = "learning"
    elif rating == 1:
        stability = max(0.5, stability * 0.7)
        difficulty = min(10.0, difficulty + 0.3)
        interval = max(1, round(stability * 0.8))
        status = "review"
    elif rating == 2:
        stability = max(1.0, stability * 1.4 + 1.0)
        difficulty = max(1.0, difficulty - 0.1)
        interval = max(1, round(stability * 1.2))
        repetitions += 1
        status = "review"
    else:
        stability = max(1.0, stability * 2.2 + 2.0)
        difficulty = max(1.0, difficulty - 0.3)
        interval = max(1, round(stability * 1.5))
        repetitions += 1
        status = "mastered" if stability >= 8 else "review"

    due = now + timedelta(days=interval)
    return {
        "status": status,
        "repetitions": repetitions,
        "interval_days": interval,
        "ease_factor": max(1.3, 2.5 - (difficulty - 5.0) * 0.2),
        "difficulty": difficulty,
        "stability": stability,
        "retrievability": max(0.0, min(1.0, math.exp(math.log(0.9) * interval / max(stability, 0.1)))),
        "due_at": due,
        "last_reviewed_at": now,
        "lapses": max(0, int(state.get("lapses") or 0) + (1 if rating == 0 else 0)),
    }
