from datetime import date, datetime
from sqlalchemy import Column, Integer, Float, String, Date, DateTime, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

class Base(DeclarativeBase):
    pass


class DietRecord(Base):
    __tablename__ = "diet_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, unique=True, nullable=False, index=True)

    total_calories = Column(Float)
    exercise_calories = Column(Float)
    budget_calories = Column(Float)
    over_budget = Column(Float)

    protein_g = Column(Float)
    protein_goal_g = Column(Float)
    carbs_g = Column(Float)
    carbs_goal_g = Column(Float)
    fat_g = Column(Float)
    fat_goal_g = Column(Float)

    meals_json = Column(Text)
    exercise_json = Column(Text)

    image_path = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    raw_llm_response = Column(Text)


class BodyComposition(Base):
    __tablename__ = "body_compositions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, unique=True, nullable=False, index=True)

    weight_kg = Column(Float)
    bmi = Column(Float)
    body_fat_pct = Column(Float)
    body_fat_kg = Column(Float)

    muscle_mass_kg = Column(Float)       # 肌肉量
    muscle_rate_pct = Column(Float)       # 肌肉率
    skeletal_muscle_kg = Column(Float)    # 骨骼肌量
    skeletal_muscle_rate_pct = Column(Float)  # 骨骼肌率
    fat_free_mass_kg = Column(Float)      # 去脂体重

    protein_kg = Column(Float)
    water_kg = Column(Float)
    bone_mass_kg = Column(Float)
    subcutaneous_fat_kg = Column(Float)
    subcutaneous_fat_pct = Column(Float)  # 皮下脂肪率

    visceral_fat_level = Column(Integer)
    bmr_kcal = Column(Float)
    body_age = Column(Integer)
    health_score = Column(Integer)
    body_type = Column(String)            # 体型评估，如"肥胖型"
    ideal_weight_kg = Column(Float)       # 理想体重

    weight_to_lose_kg = Column(Float)
    fat_to_lose_kg = Column(Float)

    image_path = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    raw_llm_response = Column(Text)


class WorkoutRecord(Base):
    __tablename__ = "workout_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    workout_type = Column(String)

    exercises = Column(Text)

    cardio_type = Column(String)
    cardio_duration_min = Column(Integer)
    cardio_distance_km = Column(Float)
    cardio_calories = Column(Float)

    duration_min = Column(Integer)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class DailySummary(Base):
    __tablename__ = "daily_summaries"

    date = Column(Date, primary_key=True)

    total_calories_in = Column(Float)
    total_protein_g = Column(Float)
    total_carbs_g = Column(Float)
    total_fat_g = Column(Float)

    bmr = Column(Float)
    calorie_deficit = Column(Float)
    protein_goal_g = Column(Float)
    protein_achievement_pct = Column(Float)

    weight_kg = Column(Float)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DiaryEntry(Base):
    __tablename__ = "diary_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    mood = Column(String)        # 心情关键词，如 "好" / "累" / "焦虑"
    mood_score = Column(Integer) # 1-5 分
    content = Column(Text)       # 日记正文
    created_at = Column(DateTime, default=datetime.utcnow)


class UserProfile(Base):
    __tablename__ = "user_profile"

    id = Column(Integer, primary_key=True, default=1)
    age = Column(Integer)
    height_cm = Column(Float)
    gender = Column(String, default="male")   # male / female
    weight_goal_kg = Column(Float)
    protein_goal_per_kg = Column(Float)
    updated_at = Column(DateTime, default=datetime.utcnow)


def init_db(db_path: str) -> None:
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine
