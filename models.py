# models.py
from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    DateTime,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship, Mapped

# Share the same Base as the engine/session (so Alembic can see models)
from db import Base, get_db_session


# ============================================================
# ORM MODELS
# ============================================================

class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = Column(String, unique=True, nullable=False)
    is_active: Mapped[int] = Column(Integer, nullable=False, default=1)

    # Admin-managed fields you previously ensured at runtime:
    postcode_prefixes: Mapped[str] = Column(Text, nullable=False, default="")
    sort_order: Mapped[int] = Column(Integer, nullable=False, default=0)


class Landlord(Base):
    __tablename__ = "landlords"

    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = Column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = Column(String, nullable=False)
    created_at: Mapped[datetime] = Column(DateTime, default=datetime.utcnow, nullable=False)

    profile: Mapped["LandlordProfile"] = relationship(
        "LandlordProfile",
        back_populates="landlord",
        uselist=False,
        cascade="all, delete-orphan",
    )

    landlord_accreditations: Mapped[list["LandlordAccreditation"]] = relationship(
        "LandlordAccreditation",
        back_populates="landlord",
        cascade="all, delete-orphan",
    )


class LandlordProfile(Base):
    __tablename__ = "landlord_profiles"

    landlord_id: Mapped[int] = Column(
        Integer, ForeignKey("landlords.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str | None] = Column(String)
    phone: Mapped[str | None] = Column(String)
    website: Mapped[str | None] = Column(String)
    bio: Mapped[str | None] = Column(Text)
    public_slug: Mapped[str | None] = Column(String, unique=True)
    profile_views: Mapped[int] = Column(Integer, nullable=False, default=0)
    is_verified: Mapped[int] = Column(Integer, nullable=False, default=0)
    role: Mapped[str] = Column(String, nullable=False, default="owner")  # owner / agent
    logo_path: Mapped[str | None] = Column(String)
    photo_path: Mapped[str | None] = Column(String)
    enable_new_landlord: Mapped[int] = Column(Integer, nullable=False, default=1)

    landlord: Mapped["Landlord"] = relationship("Landlord", back_populates="profile")


class AccreditationType(Base):
    __tablename__ = "accreditation_types"
    __table_args__ = (
        UniqueConstraint("name", name="uq_accreditation_types_name"),
        UniqueConstraint("slug", name="uq_accreditation_types_slug"),
    )

    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = Column(String, nullable=False)
    slug: Mapped[str] = Column(String, nullable=False)
    is_active: Mapped[int] = Column(Integer, nullable=False, default=1)
    sort_order: Mapped[int] = Column(Integer, nullable=False, default=0)
    help_text: Mapped[str] = Column(Text, nullable=False, default="")

    landlord_accreditations: Mapped[list["LandlordAccreditation"]] = relationship(
        "LandlordAccreditation",
        back_populates="accreditation",
        cascade="all, delete-orphan",
    )


class LandlordAccreditation(Base):
    __tablename__ = "landlord_accreditations"
    # Association object (junction) with an extra field "note"
    landlord_id: Mapped[int] = Column(
        Integer, ForeignKey("landlords.id", ondelete="CASCADE"), primary_key=True
    )
    accreditation_id: Mapped[int] = Column(
        Integer, ForeignKey("accreditation_types.id", ondelete="CASCADE"), primary_key=True
    )
    note: Mapped[str] = Column(Text, nullable=False, default="")

    landlord: Mapped["Landlord"] = relationship("Landlord", back_populates="landlord_accreditations")
    accreditation: Mapped["AccreditationType"] = relationship(
        "AccreditationType", back_populates="landlord_accreditations"
    )


# ============================================================
# PUBLIC HELPERS (ORM versions)
# ============================================================

def get_active_cities_safe(order_by_admin: bool = True) -> list[City]:
    """
    Returns a list of active City ORM objects.
    On any DB error, returns [] (safe for templates).
    """
    try:
        with get_db_session() as db:
            q = db.query(City).filter(City.is_active == 1)
            if order_by_admin:
                q = q.order_by(City.sort_order.asc(), City.name.asc())
            else:
                q = q.order_by(City.name.asc())
            return q.all()
    except Exception as e:  # keep this defensive like before
        print("[WARN] get_active_cities_safe:", e)
        return []


def get_active_city_names(order_by_admin: bool = True) -> List[str]:
    """Convenience helper: returns just the active city names."""
    return [c.name for c in get_active_cities_safe(order_by_admin=order_by_admin)]


def validate_city_active(city: str) -> bool:
    """True if the given city exists and is marked active."""
    if not city:
        return False
    try:
        with get_db_session() as db:
            exists = (
                db.query(City.id)
                .filter(City.name == city, City.is_active == 1)
                .first()
                is not None
            )
            return bool(exists)
    except Exception:
        return False
