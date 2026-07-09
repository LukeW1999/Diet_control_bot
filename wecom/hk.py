"""HealthKit bridge: a tappable HTTPS link that redirects into the iOS
Shortcuts app, passing the nutrition JSON as the shortcut's text input.

Telegram won't linkify a `shortcuts://` URL, but it will linkify an https one.
Tapping the https link opens Safari, which follows the 302 to `shortcuts://`
and runs the "写入健康" shortcut with the nutrition data.
"""
import os
import urllib.parse

from flask import Blueprint, request, redirect, jsonify

hk_bp = Blueprint("hk", __name__)

SHORTCUT_NAME = "写入健康"


@hk_bp.route("/hk/write")
def hk_write():
    d = request.args.get("d", "")  # JSON string, already URL-decoded by Flask
    url = (
        "shortcuts://run-shortcut"
        f"?name={urllib.parse.quote(SHORTCUT_NAME)}"
        "&input=text"
        f"&text={urllib.parse.quote(d)}"
    )
    return redirect(url, code=302)


@hk_bp.route("/hk/ingest", methods=["POST"])
def hk_ingest():
    """Receive HealthKit daily totals (pushed from an iOS shortcut) and store
    them as the day's diet record — this is how the bot's stats reflect
    everything in HealthKit (薄荷 entries + bot-written labels), no screenshots."""
    import logging
    token = os.getenv("HK_INGEST_TOKEN")
    body = request.get_json(silent=True) or {}
    logging.getLogger(__name__).info("hk_ingest received body=%s", body)
    if not token or body.get("token") != token:
        return jsonify({"ok": False, "error": "bad token"}), 403

    from db import crud

    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _round(v, nd):
        x = _f(v)
        return round(x, nd) if x is not None else 0.0

    the_date = body.get("date", "today")

    # Body metrics first, so the diet record's protein-goal calc sees today's weight.
    weight = _f(body.get("weight"))
    bodyfat = _f(body.get("bodyfat"))
    if bodyfat is not None and 0 < bodyfat < 1:
        bodyfat *= 100  # HealthKit stores body-fat % as a 0–1 fraction
    bdata = {"date": the_date}
    if weight and weight > 0:
        bdata["weight_kg"] = round(weight, 1)
    if bodyfat and bodyfat > 0:
        bdata["body_fat_pct"] = round(bodyfat, 1)
    if len(bdata) > 1:
        crud.upsert_body_composition(bdata, image_path="healthkit", raw_response="from HealthKit")

    data = {
        "date": the_date,
        "summary": {
            # default 0.0 so downstream formatting (write_food_log) never sees None
            "total_calories": _round(body.get("kcal"), 0),
            "protein_g": _round(body.get("protein"), 1),
            "carbs_g": _round(body.get("carbs"), 1),
            "fat_g": _round(body.get("fat"), 1),
            # active energy burned → feeds the calorie-deficit formula
            "exercise_calories": _round(body.get("exercise"), 0),
        },
    }
    rec = crud.upsert_diet_record(data, image_path="healthkit", raw_response="from HealthKit")

    resp = {
        "ok": True, "date": str(rec.date),
        "kcal": rec.total_calories, "protein": rec.protein_g,
        "carbs": rec.carbs_g, "fat": rec.fat_g,
        "exercise": rec.exercise_calories,
        "weight": bdata.get("weight_kg"), "bodyfat": bdata.get("body_fat_pct"),
    }

    # If HealthKit resting energy is provided, use it as the day's basal instead
    # of the static BMR — deficit = resting - intake + active (do NOT add both).
    resting = _f(body.get("resting"))
    if resting and resting > 0:
        from db.crud import _session
        from db.models import DailySummary
        resting = round(resting)
        deficit = resting - (rec.total_calories or 0) + (rec.exercise_calories or 0)
        with _session() as s:
            summ = s.get(DailySummary, rec.date)
            if summ:
                summ.bmr = resting
                summ.calorie_deficit = deficit
                s.commit()
        resp["resting"] = resting
        resp["deficit"] = deficit

    return jsonify(resp)
