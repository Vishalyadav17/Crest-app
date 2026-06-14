from __future__ import annotations
from sqlalchemy.orm import Session
from models import UserPreference, UserDashboardModule

_DEFAULT_MODULES = [
    {"module_key": "vault",         "is_enabled": True,  "display_order": 0, "custom_label": "Vault",
     "config": '{"sub_tabs":{"snapshot":true,"allocation":true,"swings":true,"mf":true,"global":false,"crypto":false}}'},
    {"module_key": "market_pulse",  "is_enabled": True,  "display_order": 1, "custom_label": "Market Pulse",
     "config": '{"show_heatmap":true,"show_breadth":true,"show_news":true}'},
    {"module_key": "alpha_scanner", "is_enabled": True,  "display_order": 2, "custom_label": "Alpha Scanner",
     "config": '{"auto_run":false,"email_alerts":false,"min_score":60,"top_n":10}'},
    {"module_key": "wavesight",     "is_enabled": True,  "display_order": 3, "custom_label": "Wavesight",
     "config": '{"default_layout":4,"default_tf":"1d","show_watchlist":true,"show_info":true}'},
]


def get_pref(db: Session, user_id: int, key: str, default: str | None = None) -> str | None:
    row = db.query(UserPreference).filter(
        UserPreference.user_id == user_id,
        UserPreference.key == key,
    ).first()
    return row.value if row else default


def set_pref(db: Session, user_id: int, key: str, value: str) -> None:
    row = db.query(UserPreference).filter(
        UserPreference.user_id == user_id,
        UserPreference.key == key,
    ).first()
    if row:
        row.value = value
    else:
        db.add(UserPreference(user_id=user_id, key=key, value=value))
    db.commit()


def get_all_prefs(db: Session, user_id: int) -> dict[str, str]:
    rows = db.query(UserPreference).filter(UserPreference.user_id == user_id).all()
    return {r.key: r.value for r in rows}


def get_dashboard_modules(db: Session, user_id: int) -> list[dict]:
    rows = db.query(UserDashboardModule).filter(
        UserDashboardModule.user_id == user_id,
    ).order_by(UserDashboardModule.display_order).all()

    if not rows:
        # Seed defaults
        for m in _DEFAULT_MODULES:
            db.add(UserDashboardModule(user_id=user_id, **m))
        db.commit()
        rows = db.query(UserDashboardModule).filter(
            UserDashboardModule.user_id == user_id,
        ).order_by(UserDashboardModule.display_order).all()

    return [
        {
            "id":            r.id,
            "module_key":    r.module_key,
            "is_enabled":    r.is_enabled,
            "display_order": r.display_order,
            "custom_label":  r.custom_label,
            "config":        r.config,
        }
        for r in rows
    ]


def set_dashboard_module(db: Session, user_id: int, module_key: str, **kwargs) -> dict:
    row = db.query(UserDashboardModule).filter(
        UserDashboardModule.user_id == user_id,
        UserDashboardModule.module_key == module_key,
    ).first()
    if not row:
        row = UserDashboardModule(user_id=user_id, module_key=module_key)
        db.add(row)
    for k, v in kwargs.items():
        if hasattr(row, k):
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return {
        "id":            row.id,
        "module_key":    row.module_key,
        "is_enabled":    row.is_enabled,
        "display_order": row.display_order,
        "custom_label":  row.custom_label,
        "config":        row.config,
    }
