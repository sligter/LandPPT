from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_deactivated_user_session_is_revoked():
    from landppt.auth.auth_service import AuthService
    from landppt.database.models import Base, User, UserSession

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[User.__table__, UserSession.__table__])
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)

    db = SessionLocal()
    try:
        user = User(username="u1", email="u1@example.com", is_admin=False, is_active=True, credits_balance=0)
        user.set_password("pw")
        db.add(user)
        db.commit()
        db.refresh(user)

        auth = AuthService()
        session_id = auth.create_session(db, user)

        # Disable user after session was issued
        user.is_active = False
        db.commit()

        # Existing session should no longer authenticate
        assert auth.get_user_by_session(db, session_id) is None

        # Session should be marked inactive
        sess = db.query(UserSession).filter(UserSession.session_id == session_id).first()
        assert sess is not None
        assert sess.is_active is False
    finally:
        db.close()

