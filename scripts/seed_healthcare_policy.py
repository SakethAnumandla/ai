"""
Seed a sample healthcare policy (max 5000) and workflow users for local testing.
Run: python -m scripts.seed_healthcare_policy
"""
from datetime import datetime

from app.database import SessionLocal
from app.models import (
    Department,
    MainCategory,
    Policy,
    PolicyStatus,
    User,
    UserRole,
)


def run():
    db = SessionLocal()
    try:
        employee = db.query(User).filter(User.username == "devuser").first()
        if not employee:
            employee = User(
                email="dev@local.test",
                username="devuser",
                hashed_password="not-used",
                full_name="Dev Employee",
                is_active=True,
                is_admin=False,
                role=UserRole.EMPLOYEE,
                department=Department.ENGINEERING,
            )
            db.add(employee)
            db.flush()

        dept_head = db.query(User).filter(User.username == "depthead").first()
        if not dept_head:
            dept_head = User(
                email="depthead@local.test",
                username="depthead",
                hashed_password="not-used",
                full_name="Engineering Dept Head",
                is_active=True,
                is_admin=False,
                role=UserRole.DEPARTMENT_HEAD,
                department=Department.ENGINEERING,
                department_head_for=Department.ENGINEERING,
            )
            db.add(dept_head)

        manager = db.query(User).filter(User.username == "manager").first()
        if not manager:
            manager = User(
                email="manager@local.test",
                username="manager",
                hashed_password="not-used",
                full_name="Engineering Manager",
                is_active=True,
                is_admin=False,
                role=UserRole.MANAGER,
                department=Department.ENGINEERING,
            )
            db.add(manager)
            db.flush()

        employee.manager_id = manager.id

        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                email="admin@local.test",
                username="admin",
                hashed_password="not-used",
                full_name="Policy Admin",
                is_active=True,
                is_admin=True,
                role=UserRole.SUPER_ADMIN,
                department=Department.ADMIN,
            )
            db.add(admin)
            db.flush()

        policy = db.query(Policy).filter(Policy.policy_id == "POL-HEALTH-5000").first()
        if not policy:
            creator_id = admin.id if admin else employee.id
            policy = Policy(
                policy_id="POL-HEALTH-5000",
                policy_name="Healthcare Reimbursement 2025",
                policy_type="medical",
                description="Employee healthcare bills up to INR 5000 per claim.",
                maximum_amount=5000.0,
                minimum_amount=0.0,
                coverage_percentage=100.0,
                main_category=MainCategory.POLICY,
                sub_category="healthcare",
                requires_approval=True,
                approval_flow=["department_head", "manager"],
                terms_and_conditions=(
                    "Valid medical bills only. Amount above policy limit is not reimbursable "
                    "and will be recorded as personal expense."
                ),
                valid_from=datetime.utcnow(),
                status=PolicyStatus.ACTIVE,
                created_by=creator_id,
            )
            db.add(policy)

        db.commit()
        print("Seeded POL-HEALTH-5000 (max 5000), devuser, depthead, manager, admin")
    finally:
        db.close()


if __name__ == "__main__":
    run()
