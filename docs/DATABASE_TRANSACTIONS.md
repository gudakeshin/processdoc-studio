# Database Transaction Checkpoints

This project uses explicit checkpoint marks around multi-step write flows so failures are easier to diagnose and recover from.

## Flush vs Commit

- Use `db.flush()` when later steps need generated IDs or FK-visible rows in the same transaction.
- Use `db.commit()` only after all dependent writes for the response are prepared.
- If any step fails before `commit`, the transaction should be rolled back and no partial state should persist.

## Checkpoint Scope

Use `checkpoint_scope(db, "<flow_name>")` from `app.core.db_checkpoints` in multi-step handlers.

Example pattern:

```python
from app.core.db_checkpoints import checkpoint_scope

with checkpoint_scope(db, "user_message_flow", metadata={"project_id": pid}) as cp:
    cp.mark("user_message_received")
    db.add(user_msg)
    db.flush()
    cp.mark("user_message_flushed")

    # routing + state update
    save_state(conv, state)
    db.flush()
    cp.mark("state_flushed")

    # assistant write
    db.add(assistant_msg)
    cp.mark("assistant_pre_commit")
    db.commit()
    cp.mark("assistant_committed")
```

## Recovery Expectations

- Uncaught exceptions inside `checkpoint_scope` trigger `session.rollback()` automatically.
- Checkpoint logs show the latest completed stage, which makes partial-flow diagnosis straightforward.
- Long flows should place marks before and after each flush/commit boundary and before early returns.
