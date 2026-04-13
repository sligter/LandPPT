from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _create_db():
    from landppt.database.models import Base, User

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[User.__table__])
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return SessionLocal()


def _create_user(db, username: str, email: str):
    from landppt.database.models import User

    user = User(username=username, email=email, is_admin=False, is_active=True, credits_balance=0)
    user.set_password("pw")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_init_default_admin_skips_when_bootstrap_disabled(monkeypatch):
    from landppt.auth.auth_service import init_default_admin
    from landppt.core.config import app_config
    from landppt.database.models import User

    db = _create_db()
    try:
        monkeypatch.setattr(app_config, "bootstrap_admin_enabled", False)
        monkeypatch.setattr(app_config, "bootstrap_admin_username", "admin")
        monkeypatch.setattr(app_config, "bootstrap_admin_password", "strong-password")

        init_default_admin(db)

        assert db.query(User).count() == 0
    finally:
        db.close()


def test_init_default_admin_skips_when_credentials_missing(monkeypatch):
    from landppt.auth.auth_service import init_default_admin
    from landppt.core.config import app_config
    from landppt.database.models import User

    db = _create_db()
    try:
        monkeypatch.setattr(app_config, "bootstrap_admin_enabled", True)
        monkeypatch.setattr(app_config, "bootstrap_admin_username", "admin")
        monkeypatch.setattr(app_config, "bootstrap_admin_password", "")

        init_default_admin(db)

        assert db.query(User).count() == 0
    finally:
        db.close()


def test_init_default_admin_bootstraps_when_explicitly_configured(monkeypatch):
    from landppt.auth.auth_service import init_default_admin
    from landppt.core.config import app_config
    from landppt.database.models import User

    db = _create_db()
    try:
        monkeypatch.setattr(app_config, "bootstrap_admin_enabled", True)
        monkeypatch.setattr(app_config, "bootstrap_admin_username", "founder")
        monkeypatch.setattr(app_config, "bootstrap_admin_password", "strong-password")

        init_default_admin(db)

        created = db.query(User).one()
        assert created.username == "founder"
        assert created.is_admin is True
    finally:
        db.close()


def test_init_default_admin_skips_when_users_exist(monkeypatch):
    from landppt.auth.auth_service import init_default_admin
    from landppt.core.config import app_config
    from landppt.database.models import User

    db = _create_db()
    try:
        _create_user(db, "existing", "existing@example.com")
        monkeypatch.setattr(app_config, "bootstrap_admin_enabled", True)
        monkeypatch.setattr(app_config, "bootstrap_admin_username", "founder")
        monkeypatch.setattr(app_config, "bootstrap_admin_password", "strong-password")

        init_default_admin(db)

        users = db.query(User).order_by(User.username.asc()).all()
        assert [user.username for user in users] == ["existing"]
    finally:
        db.close()
