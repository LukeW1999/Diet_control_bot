import json
import math
import os
from datetime import date, datetime, timedelta
from sqlalchemy import create_engine, select, desc
from sqlalchemy.orm import Session
from .models import (Base, DietRecord, BodyComposition, DailySummary, DiaryEntry,
                     FoodLibraryItem, UserProfile)
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

        # Refresh stats cache whenever body data changes
        try:
            from utils.stats import compute_and_save
            compute_and_save()
        except Exception:
            pass

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


def get_bmr(weight: float | None = None) -> float:
    """Calculate BMR (Mifflin-St Jeor) from user profile + weight. Falls back to
    .env USER_BMR. Pass `weight` to compute for a specific day; else latest."""
    profile = get_user_profile()
    if weight is None:
        body = get_latest_body_composition()
        weight = body.weight_kg if body else None

    if profile and profile.age and profile.height_cm and weight:
        # Mifflin-St Jeor
        bmr = 10 * weight + 6.25 * profile.height_cm - 5 * profile.age
        bmr += 5 if (profile.gender or "male") == "male" else -161
        return round(bmr, 1)

    return float(os.getenv("USER_BMR", 1916))


def weight_on(target_date: date) -> float | None:
    """Weight for a date, linearly interpolated between the surrounding weigh-ins.

    Without this a date with no weigh-in falls back to the *latest* weight, so a June
    summary ends up carrying today's BMR — off by ~50 kcal after a 5 kg loss, and
    worse the further back you look. Beyond the recorded range the nearest weigh-in is
    carried flat rather than extrapolated, since projecting a weight trend past the
    data is guesswork."""
    with _session() as s:
        series = sorted(
            (b.date, b.weight_kg)
            for b in s.scalars(select(BodyComposition)).all() if b.weight_kg
        )
    if not series:
        return None
    if target_date <= series[0][0]:
        return series[0][1]
    if target_date >= series[-1][0]:
        return series[-1][1]
    prev = max(d for d, _ in series if d <= target_date)
    nxt = min(d for d, _ in series if d >= target_date)
    if prev == nxt:
        return dict(series)[prev]
    lo, hi = dict(series)[prev], dict(series)[nxt]
    return lo + (hi - lo) * ((target_date - prev).days / (nxt - prev).days)


def is_refeed_day(target_date: date) -> bool:
    with _session() as s:
        summ = s.get(DailySummary, target_date)
        return bool(summ and summ.is_refeed)


def toggle_refeed(target_date: date) -> bool:
    """Flip the refeed flag for a day (creating its summary row if needed). Returns
    the new state. A refeed day recommends maintenance calories (zero deficit)."""
    with _session() as s:
        summ = s.get(DailySummary, target_date)
        if not summ:
            summ = DailySummary(date=target_date, updated_at=datetime.utcnow())
            s.add(summ)
        summ.is_refeed = 0 if summ.is_refeed else 1
        s.commit()
        return bool(summ.is_refeed)


def refeed_status(target_date: date | None = None) -> dict:
    """Earn refeed days off real scale progress, ratcheted on your all-time low so a
    bounce up and back down can't re-earn. Each REFEED_WEIGHT_STEP_KG (default 1kg)
    below the baseline banks one refeed; the baseline is anchored at your lowest weight
    when the feature starts, so earning is forward-looking. No cap — refeeds stockpile.
    `available` = earned − taken (refeed days already switched on)."""
    step = float(os.getenv("REFEED_WEIGHT_STEP_KG", 1.0))
    with _session() as s:
        weights = [b.weight_kg for b in s.scalars(select(BodyComposition)).all() if b.weight_kg]
        min_w = min(weights) if weights else None
        taken = sum(1 for x in s.scalars(select(DailySummary)).all() if x.is_refeed)
        prof = s.get(UserProfile, 1)
        baseline = prof.refeed_weight_baseline if prof else None
        if baseline is None and min_w is not None:  # lazy anchor at current low
            if not prof:
                prof = UserProfile(id=1)
                s.add(prof)
            prof.refeed_weight_baseline = min_w
            baseline = min_w
            s.commit()

    earned = int(max(0, (baseline - min_w) // step)) if (baseline and min_w) else 0
    available = max(earned - taken, 0)
    next_low = round(baseline - (earned + 1) * step, 1) if baseline else None
    to_next = round(min_w - next_low, 1) if (min_w is not None and next_low is not None) else None
    return {
        "step": step,
        "baseline": round(baseline, 1) if baseline else None,
        "current_min": round(min_w, 1) if min_w else None,
        "earned": earned,
        "taken": taken,
        "available": available,
        "next_low": next_low,
        "to_next_kg": to_next,
    }


def recommend_calories(target_date: date | None = None) -> dict:
    """Recommended daily intake = static BMR + recent daily-average active energy
    − the deficit needed to hit MONTHLY_LOSS_KG (default 4). The static part (BMR)
    is fixed for the day, so the target doesn't drift the way Apple's accumulating
    resting energy does.

    Trackers (Apple Watch etc.) overestimate active energy, so only a fraction is
    added back (ACTIVE_EATBACK_PCT, default 0.4 — calibrated from Luke's actual
    weight loss). Set 1.0 to trust the tracker fully, 0 to ignore exercise.

    Also returns macro targets so intake can be split into protein/fat/carbs:
    protein = weight × goal_per_kg (fixed), fat = weight × 0.8 (cut floor),
    carbs = whatever calories remain at the recommended ceiling.

    On a refeed day the deficit is zeroed, so intake targets maintenance (TDEE)
    and the extra calories land in carbs."""
    target_date = target_date or date.today()
    body = get_latest_body_composition()
    weight = body.weight_kg if body else None
    bmr = get_bmr(weight)
    recent = get_diet_records_range(target_date - timedelta(days=7), target_date)
    active = [r.exercise_calories for r in recent if r.exercise_calories]
    avg_active = round(sum(active) / len(active)) if active else 0
    eatback = float(os.getenv("ACTIVE_EATBACK_PCT", 0.4))
    active_counted = round(avg_active * eatback)
    tdee = bmr + active_counted

    # Deficit sized for the monthly fat-loss goal (1 kg fat ≈ 7700 kcal); a refeed
    # day zeroes it so intake targets maintenance.
    refeed = is_refeed_day(target_date)
    monthly_goal = float(os.getenv("MONTHLY_LOSS_KG", 4.0))
    target_deficit = 0 if refeed else round(monthly_goal * 7700 / 30)
    low = round(tdee - target_deficit - 100)   # a bit faster
    high = round(tdee - target_deficit + 100)  # a bit slower

    protein_g = round(weight * float(os.getenv("USER_PROTEIN_GOAL_PER_KG", 1.8))) if weight else 0
    fat_g = round(weight * 0.8) if weight else 0
    carbs_g = round(max(high - protein_g * 4 - fat_g * 9, 0) / 4)
    return {
        "bmr": round(bmr),
        "avg_active": avg_active,
        "active_counted": active_counted,
        "eatback_pct": round(eatback * 100),
        "tdee": round(tdee),
        "refeed": refeed,
        "monthly_goal": monthly_goal,
        "target_deficit": target_deficit,
        "low": low,
        "high": high,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "carbs_g": carbs_g,
    }


def calibrate_eatback(window_days: int = 42) -> dict:
    """Fit ACTIVE_EATBACK_PCT from real scale movement over a trailing window.

    Inverts the same model recommend_calories uses: TDEE = BMR + eatback × active.
    TDEE is read off the energy balance as avg intake − weight trend × 7700, so
    eatback = (TDEE − BMR) / avg active.

    The trend is an OLS fit over every weigh-in in the window, never first-vs-last:
    endpoints discard the series and inherit the full day-to-day water swing (~0.45
    kg here), which on a 3-week window is worth ~±350 kcal of TDEE and produced a
    72% estimate where the regression says 35%.

    Slope standard error falls as N^-1.5, so patience pays superlinearly: ~±6pp of
    eatback at 28 days, ~±3pp at 42. Hence `min_days` gates on having enough of the
    window actually logged, and the verdict only moves eatback when the estimate
    clears a 2-SE deadband, then only halfway, so the parameter cannot oscillate on
    noise.

    Caveat worth remembering when reading the number: eatback also absorbs error in
    the Mifflin-St Jeor BMR (±10% individually, ±14pp of eatback on its own). It is
    a fitted correction, not a physiological measurement."""
    today = date.today()
    start = today - timedelta(days=window_days)
    # Today's log is still accumulating, so it would drag the intake mean down.
    weights = [b for b in get_body_compositions_range(start, today - timedelta(days=1))
               if b.weight_kg]
    logged = [r for r in get_diet_records_range(start, today - timedelta(days=1))
              if r.total_calories]

    min_days = int(os.getenv("CALIBRATE_MIN_DAYS", 20))
    current = float(os.getenv("ACTIVE_EATBACK_PCT", 0.4))
    result = {
        "window_days": window_days,
        "n_weights": len(weights),
        "n_intake": len(logged),
        "min_days": min_days,
        "current_pct": round(current * 100),
    }
    # The residual SD needs n − 2 degrees of freedom, so never fit on fewer than 3.
    if len(weights) < max(min_days, 3) or len(logged) < min_days:
        return {**result, "verdict": "insufficient"}

    xs = [(b.date - weights[0].date).days for b in weights]
    ys = [b.weight_kg for b in weights]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    resid_sd = math.sqrt(sum((y - (my + slope * (x - mx))) ** 2
                             for x, y in zip(xs, ys)) / (n - 2))
    slope_se = resid_sd / math.sqrt(sxx)

    avg_intake = sum(r.total_calories for r in logged) / len(logged)
    avg_active = sum(r.exercise_calories or 0 for r in logged) / len(logged)
    tdee = avg_intake - slope * 7700
    tdee_se = slope_se * 7700
    # Averaged across the window, not taken from the latest weigh-in: over a 56-day
    # window the weight loss itself moves BMR by ~30 kcal, which lands straight in
    # the eatback residual and biases it upward.
    span = [today - timedelta(days=k) for k in range(1, window_days + 1)]
    bmr = sum(get_bmr(weight=weight_on(d)) for d in span) / len(span)

    if avg_active <= 0:
        return {**result, "verdict": "insufficient"}
    implied = (tdee - bmr) / avg_active
    implied_se = tdee_se / avg_active

    off_by = implied - current
    within_deadband = abs(off_by) < 2 * implied_se
    return {
        **result,
        "slope_kg_per_week": round(slope * 7, 3),
        "slope_se_kg_per_week": round(slope_se * 7, 3),
        "resid_sd_kg": round(resid_sd, 3),
        "avg_intake": round(avg_intake),
        "avg_active": round(avg_active),
        "bmr": round(bmr),
        "tdee": round(tdee),
        "tdee_se": round(tdee_se),
        "implied_pct": round(implied * 100),
        "implied_se_pp": round(implied_se * 100, 1),
        # Damped: move half the gap, so a single noisy window cannot swing the target.
        "suggested_pct": round((current + off_by / 2) * 100),
        "verdict": "deadband" if within_deadband else "adjust",
    }


def summary_integrity(days: int = 14) -> list[str]:
    """Days whose stored BMR disagrees with the scientific BMR for that day's weight.

    A DailySummary's `bmr` is always Mifflin-St Jeor from that date's weigh-in, so a
    disagreement means something other than _update_daily_summary_from_diet wrote the
    row: a stale process still holding old code, a half-deployed service, a manual
    edit. That is exactly how the Apple-resting-energy regression went unnoticed for
    days — it wrote 795–1904 into this field while every visible number stayed
    plausible.

    Checks BMR rather than the deficit on purpose: BMR is parameter-free, so tuning
    ACTIVE_EATBACK_PCT or the intake target can never make this fire. Days with no
    weigh-in are unverifiable (BMR falls back to the latest weight, which legitimately
    drifts) and are skipped. Returns [] when healthy so callers can stay silent."""
    today = date.today()
    out = []
    with _session() as s:
        for summ in s.scalars(
            select(DailySummary)
            .where(DailySummary.date >= today - timedelta(days=days))
            .order_by(DailySummary.date)
        ).all():
            if summ.bmr is None:
                continue
            body = s.scalar(select(BodyComposition).where(BodyComposition.date == summ.date))
            if not (body and body.weight_kg):
                continue
            expected = get_bmr(weight=body.weight_kg)
            if abs(summ.bmr - expected) > 1.0:
                out.append(f"{summ.date}: 存储BMR {summ.bmr:.0f}，应为 {expected:.0f}")
    return out


def _update_daily_summary_from_diet(session: Session, rec: DietRecord) -> None:
    protein_goal_per_kg = float(os.getenv("USER_PROTEIN_GOAL_PER_KG", 1.8))

    body = session.scalar(select(BodyComposition).where(BodyComposition.date == rec.date))
    weight = body.weight_kg if body else None
    # Scientific BMR from height/age/weight, not Apple's synced resting energy.
    bmr = get_bmr(weight=weight)
    protein_goal = weight * protein_goal_per_kg if weight else None

    # HealthKit writes don't carry a protein goal; backfill it onto the diet record
    # so every downstream reader (morning report, weekly report) has it.
    if protein_goal and not rec.protein_goal_g:
        rec.protein_goal_g = round(protein_goal, 1)

    # Discount active energy (tracker overestimate) so the deficit — and the
    # fat-loss projection built on it — matches reality, not the watch.
    eatback = float(os.getenv("ACTIVE_EATBACK_PCT", 0.4))
    calorie_deficit = bmr - (rec.total_calories or 0) + (rec.exercise_calories or 0) * eatback

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


# ── food library ──────────────────────────────────────────────────────────────
def remember_food(name: str, canon: dict, barcode: str = None,
                  brand: str = None, serving_g: float = None) -> None:
    """Save (or refresh) a per-100g food. Keeps use_count when it is already known.

    Barcode entries are identified by their code; text-derived ones have no code,
    so they are matched on name to stop the same yoghurt piling up every time it
    is logged at a different weight.
    """
    with _session() as s:
        where = (FoodLibraryItem.barcode == barcode) if barcode else (
            (FoodLibraryItem.barcode.is_(None)) & (FoodLibraryItem.name == name))
        item = s.scalar(select(FoodLibraryItem).where(where))
        if item is None:
            item = FoodLibraryItem(barcode=barcode, use_count=0)
            s.add(item)
        item.name = name
        item.brand = brand or None
        item.serving_g = serving_g
        item.canon_json = json.dumps(canon)
        s.commit()


def record_food_use(item_id: int, grams: float) -> None:
    with _session() as s:
        item = s.get(FoodLibraryItem, item_id)
        if item is None:
            return
        item.last_grams = grams
        item.use_count = (item.use_count or 0) + 1
        item.last_used = datetime.utcnow()
        s.commit()


def get_food_library(keyword: str = "", limit: int = 12) -> list[FoodLibraryItem]:
    """Most-used first, then most recent. Filters on name/brand when given a keyword."""
    with _session() as s:
        q = select(FoodLibraryItem)
        if keyword:
            like = f"%{keyword}%"
            q = q.where(FoodLibraryItem.name.ilike(like) | FoodLibraryItem.brand.ilike(like))
        q = q.order_by(desc(FoodLibraryItem.use_count), desc(FoodLibraryItem.last_used)).limit(limit)
        return list(s.scalars(q))


def get_food_item(item_id: int) -> FoodLibraryItem | None:
    with _session() as s:
        return s.get(FoodLibraryItem, item_id)


def find_food(name: str, barcode: str = None) -> FoodLibraryItem | None:
    with _session() as s:
        where = (FoodLibraryItem.barcode == barcode) if barcode else (
            (FoodLibraryItem.barcode.is_(None)) & (FoodLibraryItem.name == name))
        return s.scalar(select(FoodLibraryItem).where(where))
