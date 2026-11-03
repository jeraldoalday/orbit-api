"""record_activity's commit flag, exercised directly.

Every caller in app/services passes commit=False, folding the row into a
larger transaction the caller commits itself (see the "atomic activity
logging" note in the README). That left the commit=True default path --
the one a future caller would get by just not passing the flag -- with no
coverage at all.
"""

import uuid

from app.models.task_activity import TaskActivityType
from app.services.task_activity_service import list_activities, record_activity


def test_record_activity_commits_and_refreshes_by_default(db):
    task_id = uuid.uuid4()

    activity = record_activity(db, task_id, None, TaskActivityType.CREATED)

    db.rollback()
    persisted = list_activities(db, task_id)
    assert [a.id for a in persisted] == [activity.id]


def test_record_activity_with_commit_false_leaves_it_to_the_caller(db):
    task_id = uuid.uuid4()

    record_activity(db, task_id, None, TaskActivityType.CREATED, commit=False)

    # Nothing is visible to another look at the database until the caller
    # commits the transaction this row was folded into.
    db.rollback()
    assert list_activities(db, task_id) == []


def test_list_activities_orders_by_created_at_then_id(db):
    task_id = uuid.uuid4()
    first = record_activity(db, task_id, None, TaskActivityType.CREATED)
    second = record_activity(db, task_id, None, TaskActivityType.UPDATED, data={"status": "done"})

    activities = list_activities(db, task_id)

    assert [a.id for a in activities] == [first.id, second.id]
    assert activities[1].data == {"status": "done"}


def test_record_activity_with_no_actor_leaves_actor_id_none(db):
    activity = record_activity(db, uuid.uuid4(), None, TaskActivityType.CREATED)

    assert activity.actor_id is None
