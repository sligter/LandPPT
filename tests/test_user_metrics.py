from sqlalchemy import create_engine
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import joinedload, sessionmaker


def _create_db():
    from landppt.database.models import Base, CreditTransaction, Project, User, UserMetrics

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            UserMetrics.__table__,
            Project.__table__,
            CreditTransaction.__table__,
        ],
    )
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return SessionLocal()


def test_user_metrics_track_projects_credits_and_activity():
    from landppt.database.models import CreditTransaction, Project, User, UserMetrics

    db = _create_db()
    try:
        user = User(username="metrics-user", email="metrics@example.com", is_active=True, is_admin=False)
        user.set_password("pw")
        db.add(user)
        db.commit()
        db.refresh(user)

        metrics = db.get(UserMetrics, user.id)
        assert metrics is not None
        assert metrics.projects_count == 0
        assert metrics.credits_consumed_total == 0
        assert metrics.credits_recharged_total == 0
        assert metrics.last_active_at is not None

        project_created_at = 2_000_000_100.0
        consumed_at = 2_000_000_200.0
        recharged_at = 2_000_000_300.0
        logged_in_at = 2_000_000_400.0

        project = Project(
            project_id="project-1",
            user_id=user.id,
            title="Project 1",
            scenario="general",
            topic="Topic",
            created_at=project_created_at,
            updated_at=project_created_at,
        )
        db.add(project)
        db.commit()

        db.expire_all()
        metrics = db.get(UserMetrics, user.id)
        assert metrics is not None
        assert metrics.projects_count == 1
        assert metrics.last_project_created_at == project_created_at
        assert metrics.last_active_at == project_created_at

        db.add(
            CreditTransaction(
                user_id=user.id,
                amount=-7,
                balance_after=93,
                transaction_type="consume",
                description="consume credits",
                reference_id="project-1",
                created_at=consumed_at,
            )
        )
        db.commit()

        db.expire_all()
        metrics = db.get(UserMetrics, user.id)
        assert metrics is not None
        assert metrics.credits_consumed_total == 7
        assert metrics.last_credit_consumed_at == consumed_at
        assert metrics.last_active_at == consumed_at

        db.add(
            CreditTransaction(
                user_id=user.id,
                amount=11,
                balance_after=104,
                transaction_type="admin_adjust",
                description="admin recharge",
                reference_id="manual",
                created_at=recharged_at,
            )
        )
        db.commit()

        db.expire_all()
        metrics = db.get(UserMetrics, user.id)
        assert metrics is not None
        assert metrics.credits_recharged_total == 11
        assert metrics.last_credit_recharged_at == recharged_at
        assert metrics.last_active_at == consumed_at

        user.last_login = logged_in_at
        db.commit()

        db.expire_all()
        metrics = db.get(UserMetrics, user.id)
        assert metrics is not None
        assert metrics.last_active_at == logged_in_at
    finally:
        db.close()


def test_user_to_dict_includes_loaded_metrics():
    from landppt.database.models import User, UserMetrics

    db = _create_db()
    try:
        user = User(username="metrics-json", email="json@example.com", is_active=True, is_admin=False)
        user.set_password("pw")
        db.add(user)
        db.commit()

        loaded = (
            db.query(User)
            .options(joinedload(User.metrics))
            .filter(User.username == "metrics-json")
            .first()
        )
        assert loaded is not None

        payload = loaded.to_dict()
        assert "metrics" in payload
        assert payload["metrics"]["user_id"] == loaded.id
        assert payload["metrics"]["projects_count"] == 0
    finally:
        db.close()


@pytest.mark.asyncio
async def test_user_repository_sorts_by_metric_fields():
    from landppt.database.models import Base, User, UserMetrics
    from landppt.database.repositories import UserRepository

    class AsyncSessionAdapter:
        def __init__(self, sync_session):
            self._sync_session = sync_session

        async def execute(self, statement):
            return self._sync_session.execute(statement)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)

    try:
        Base.metadata.create_all(engine, tables=[User.__table__, UserMetrics.__table__])

        with session_factory() as session:
            alpha = User(username="alpha", email="alpha@example.com", is_active=True, is_admin=False)
            alpha.set_password("pw")
            beta = User(username="beta", email="beta@example.com", is_active=True, is_admin=False)
            beta.set_password("pw")
            gamma = User(username="gamma", email="gamma@example.com", is_active=True, is_admin=False)
            gamma.set_password("pw")
            session.add_all([alpha, beta, gamma])
            session.commit()

            metrics_result = session.execute(select(UserMetrics))
            metrics_by_user_id = {metric.user_id: metric for metric in metrics_result.scalars().all()}
            for user in (alpha, beta, gamma):
                metrics_by_user_id.setdefault(user.id, UserMetrics(user_id=user.id))
            session.add_all(metrics_by_user_id.values())

            metrics_by_user_id[alpha.id].projects_count = 2
            metrics_by_user_id[alpha.id].credits_consumed_total = 15
            metrics_by_user_id[alpha.id].last_active_at = 100.0

            metrics_by_user_id[beta.id].projects_count = 5
            metrics_by_user_id[beta.id].credits_consumed_total = 30
            metrics_by_user_id[beta.id].last_active_at = 200.0

            metrics_by_user_id[gamma.id].projects_count = 0
            metrics_by_user_id[gamma.id].credits_consumed_total = 0
            metrics_by_user_id[gamma.id].last_active_at = 300.0
            session.commit()

            repo = UserRepository(AsyncSessionAdapter(session))

            users, total = await repo.list_users(
                page=1,
                page_size=10,
                sort_by="projects_count",
                sort_dir="desc",
            )
            assert total == 3
            assert [user.username for user in users] == ["beta", "alpha", "gamma"]

            users, _ = await repo.list_users(
                page=1,
                page_size=10,
                sort_by="credits_consumed_total",
                sort_dir="desc",
            )
            assert [user.username for user in users] == ["beta", "alpha", "gamma"]

            users, _ = await repo.list_users(
                page=1,
                page_size=10,
                sort_by="last_active_at",
                sort_dir="desc",
            )
            assert [user.username for user in users] == ["gamma", "beta", "alpha"]
    finally:
        engine.dispose()
