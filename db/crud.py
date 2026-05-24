import json
import os
from datetime import date, datetime
from sqlalchemy import create_engine, select, desc
from sqlalchemy.orm import Session
from .models import Base, DietRecord, BodyComposition, WorkoutRecord, DailySummary, DiaryEntry, UserProfile
from utils.food_log import write_entry as write_food_log


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        db_path = os.path.join(os.path.dirname(__file__), "..", "data", "health.db")
        db_path = os.path.abspath(db_path)
        _engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(_engine)
    return _engine


def _session():
    return Session(get_engine(), expire_on_commit=False)


def upsert_diet_record(data: dict, image_path: str, raw_response: str) -> DietRecord:
    with _session() as session:
        record_date = _parse_date(data.get("date"))
        existing = session.scalar(select(DietRecord).where(DietRecord.date == record_date))

        summary = data.get("summary", {})
        if existing:
            rec = existing
        else:
            rec = DietRecord(date=record_date)
            session.add(rec)

        rec.total_calories = summary.get("total_calories")
        rec.exercise_calories = summary.get("exercise_calories")
        rec.budget_calories = summary.get("budget_calories")
        rec.over_budget = summary.get("over_budget")
        rec.protein_g = summary.get("protein_g")
        rec.protein_goal_g = summary.get("protein_goal_g")
        rec.carbs_g = summary.get("carbs_g")
        rec.carbs_goal_g = summary.get("carbs_goal_g")
        rec.fat_g = summary.get("fat_g")
        rec.fat_goal_g = summary.get("fat_goal_g")
        rec.meals_json = json.dumps(data.get("meals", []), ensure_ascii=False)
        rec.exercise_json = json.dumps(data.get("exercise", []), ensure_ascii=False)
        rec.image_path = image_path
        rec.raw_llm_response = raw_response
        rec.created_at = datetime.utcnow()

        session.commit()
        session.refresh(rec)
        _update_daily_summary_from_diet(session, rec)
        session.commit()
        write_food_log(rec)
        return rec


def upsert_body_composition(data: dict, image_path: str, raw_response: str) -> BodyComposition:
    with _session() as session:
        record_date = _parse_date(data.get("date"))
        existing = session.scalar(select(BodyComposition).where(BodyComposition.date == record_date))

        if existing:
            rec = existing
        else:
            rec = BodyComposition(date=record_date)
            session.add(rec)

        for field in [
            "weight_kg", "bmi", "body_fat_pct", "body_fat_kg",
            "muscle_mass_kg", "muscle_rate_pct",
            "skeletal_muscle_kg", "skeletal_muscle_rate_pct",
            "fat_free_mass_kg",
            "protein_kg", "water_kg", "bone_mass_kg",
            "subcutaneous_fat_kg", "subcutaneous_fat_pct",
            "visceral_fat_level", "bmr_kcal", "body_age", "health_score",
            "body_type", "ideal_weight_kg",
            "weight_to_lose_kg", "fat_to_lose_kg",
        ]:
            val = data.get(field)
            if val is not None:
                setattr(rec, field, val)

        rec.image_path = image_path
        rec.raw_llm_response = raw_response
        rec.created_at = datetime.utcnow()

        session.commit()
        session.refresh(rec)

        summary = session.get(DailySummary, record_date)
        if summary:
            summary.weight_kg = rec.weight_kg
            summary.updated_at = datetime.utcnow()
            session.commit()

        return rec


def save_workout(data: dict) -> WorkoutRecord:
    with _session() as session:
        record_date = _parse_date(data.get("date"))
        rec = WorkoutRecord(
            date=record_date,
            workout_type=data.get("workout_type"),
            exercises=json.dumps(data.get("exercises", []), ensure_ascii=False),
            cardio_type=data.get("cardio", {}).get("type") if data.get("cardio") else None,
            cardio_duration_min=data.get("cardio", {}).get("duration_min") if data.get("cardio") else None,
            cardio_distance_km=data.get("cardio", {}).get("distance_km") if data.get("cardio") else None,
            cardio_calories=data.get("cardio", {}).get("calories") if data.get("cardio") else None,
            duration_min=data.get("duration_min"),
            notes=data.get("notes"),
        )
        session.add(rec)
        session.commit()
        session.refresh(rec)
        return rec


def get_diet_record(target_date: date) -> DietRecord | None:
    with _session() as session:
        return session.scalar(select(DietRecord).where(DietRecord.date == target_date))


def get_latest_body_composition() -> BodyComposition | None:
    with _session() as session:
        return session.scalar(select(BodyComposition).order_by(desc(BodyComposition.date)).limit(1))


def get_body_compositions_range(start: date, end: date) -> list[BodyComposition]:
    with _session() as session:
        rows = session.scalars(
            select(BodyComposition)
            .where(BodyComposition.date >= start, BodyComposition.date <= end)
            .order_by(BodyComposition.date)
        ).all()
        return list(rows)


def get_diet_records_range(start: date, end: date) -> list[DietRecord]:
    with _session() as session:
        rows = session.scalars(
            select(DietRecord)
            .where(DietRecord.date >= start, DietRecord.date <= end)
            .order_by(DietRecord.date)
        ).all()
        return list(rows)


def get_workouts_range(start: date, end: date) -> list[WorkoutRecord]:
    with _session() as session:
        rows = session.scalars(
            select(WorkoutRecord)
            .where(WorkoutRecord.date >= start, WorkoutRecord.date <= end)
            .order_by(WorkoutRecord.date)
        ).all()
        return list(rows)


def get_daily_summary(target_date: date) -> DailySummary | None:
    with _session() as session:
        return session.get(DailySummary, target_date)


def get_daily_summaries_range(start: date, end: date) -> list[DailySummary]:
    with _session() as session:
        rows = session.scalars(
            select(DailySummary)
            .where(DailySummary.date >= start, DailySummary.date <= end)
            .order_by(DailySummary.date)
        ).all()
        return list(rows)


def quick_weight_entry(target_date: date, weight_kg: float) -> None:
    with _session() as session:
        existing = session.scalar(select(BodyComposition).where(BodyComposition.date == target_date))
        if existing:
            existing.weight_kg = weight_kg
        else:
            rec = BodyComposition(date=target_date, weight_kg=weight_kg)
            session.add(rec)

        summary = session.get(DailySummary, target_date)
        if summary:
            summary.weight_kg = weight_kg
        else:
            summary = DailySummary(date=target_date, weight_kg=weight_kg, updated_at=datetime.utcnow())
            session.add(summary)

        session.commit()


def save_diary(entry_date: date, content: str, mood: str = None, mood_score: int = None) -> DiaryEntry:
    with _session() as session:
        rec = DiaryEntry(
            date=entry_date,
            content=content,
            mood=mood,
            mood_score=mood_score,
            created_at=datetime.utcnow(),
        )
        session.add(rec)
        session.commit()
        return rec


def get_diary_entries(start: date, end: date) -> list[DiaryEntry]:
    with _session() as session:
        rows = session.scalars(
            select(DiaryEntry)
            .where(DiaryEntry.date >= start, DiaryEntry.date <= end)
            .order_by(DiaryEntry.date)
        ).all()
        return list(rows)


def apply_correction(table: str, field: str, value, record_date: date) -> bool:
    """Apply a user correction to body or diet record. Returns True if successful."""
    with _session() as session:
        if table == "body":
            rec = session.scalar(select(BodyComposition).where(BodyComposition.date == record_date))
            if not rec:
                rec = BodyComposition(date=record_date)
                session.add(rec)
            if hasattr(rec, field):
                setattr(rec, field, value)
                session.commit()
                return True
        elif table == "diet":
            rec = session.scalar(select(DietRecord).where(DietRecord.date == record_date))
            if rec and hasattr(rec, field):
                setattr(rec, field, value)
                session.commit()
                return True
    return False


def get_user_profile() -> UserProfile | None:
    with _session() as session:
        return session.get(UserProfile, 1)


def update_user_profile(**kwargs) -> UserProfile:
    with _session() as session:
        rec = session.get(UserProfile, 1)
        if not rec:
            rec = UserProfile(id=1)
            session.add(rec)
        for k, v in kwargs.items():
            if hasattr(rec, k):
                setattr(rec, k, v)
        rec.updated_at = datetime.utcnow()
        session.commit()
        session.refresh(rec)
        return rec


def get_bmr() -> float:
    """Calculate BMR from user profile + latest weight. Falls back to .env USER_BMR."""
    profile = get_user_profile()
    body = get_latest_body_composition()
    weight = body.weight_kg if body else None

    if profile and profile.age and profile.height_cm and weight:
        # Mifflin-St Jeor
        bmr = 10 * weight + 6.25 * profile.height_cm - 5 * profile.age
        bmr += 5 if (profile.gender or "male") == "male" else -161
        return round(bmr, 1)

    return float(os.getenv("USER_BMR", 1916))


def _update_daily_summary_from_diet(session: Session, rec: DietRecord) -> None:
    bmr = float(os.getenv("USER_BMR", 1916))
    protein_goal_per_kg = float(os.getenv("USER_PROTEIN_GOAL_PER_KG", 1.8))

    body = session.scalar(select(BodyComposition).where(BodyComposition.date == rec.date))
    weight = body.weight_kg if body else None
    protein_goal = weight * protein_goal_per_kg if weight else None

    calorie_deficit = bmr - (rec.total_calories or 0) + (rec.exercise_calories or 0)

    summary = session.get(DailySummary, rec.date)
    if not summary:
        summary = DailySummary(date=rec.date)
        session.add(summary)

    summary.total_calories_in = rec.total_calories
    summary.total_protein_g = rec.protein_g
    summary.total_carbs_g = rec.carbs_g
    summary.total_fat_g = rec.fat_g
    summary.bmr = bmr
    summary.calorie_deficit = calorie_deficit
    summary.protein_goal_g = protein_goal or rec.protein_goal_g
    if protein_goal and rec.protein_g:
        summary.protein_achievement_pct = rec.protein_g / protein_goal * 100
    summary.updated_at = datetime.utcnow()


def _parse_date(d) -> date:
    if isinstance(d, date):
        return d
    if not d or d == "today":
        return date.today()
    if isinstance(d, str):
        return date.fromisoformat(d[:10])
    return date.today()
