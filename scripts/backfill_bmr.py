"""One-off: recompute every DailySummary's BMR + deficit with the scientific
Mifflin-St Jeor BMR (per-date weight), replacing the old Apple-resting figures."""
import os

from dotenv import load_dotenv

load_dotenv()

from db import crud
from db.crud import _session
from db.models import DailySummary, DietRecord, BodyComposition
from sqlalchemy import select


def main() -> None:
    with _session() as s:
        summaries = s.scalars(select(DailySummary)).all()
        changed = 0
        for summ in summaries:
            diet = s.scalar(select(DietRecord).where(DietRecord.date == summ.date))
            body = s.scalar(select(BodyComposition).where(BodyComposition.date == summ.date))
            # Interpolate when that day was not weighed. Falling through to
            # get_bmr(None) would use *today's* weight, stamping a June row with a
            # BMR from 5 kg later.
            weight = ((body.weight_kg if body else None) or summ.weight_kg
                      or crud.weight_on(summ.date))
            bmr = crud.get_bmr(weight=weight)
            intake = (diet.total_calories if diet else None) or summ.total_calories_in or 0
            exercise = (diet.exercise_calories if diet else 0) or 0
            eatback = float(os.getenv("ACTIVE_EATBACK_PCT", 0.4))
            new_deficit = round(bmr - intake + exercise * eatback)
            if summ.bmr != bmr or summ.calorie_deficit != new_deficit:
                print(f"{summ.date}: bmr {summ.bmr}->{bmr}  deficit {summ.calorie_deficit}->{new_deficit}")
                summ.bmr = bmr
                summ.calorie_deficit = new_deficit
                changed += 1
        s.commit()
        print(f"\nUpdated {changed}/{len(summaries)} daily summaries.")


if __name__ == "__main__":
    main()
