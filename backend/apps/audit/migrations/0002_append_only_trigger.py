from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION audit_event_block_changes() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_event is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_event_no_update
    BEFORE UPDATE OR DELETE ON audit_event
    FOR EACH ROW EXECUTE FUNCTION audit_event_block_changes();

CREATE TRIGGER audit_event_no_truncate
    BEFORE TRUNCATE ON audit_event
    FOR EACH STATEMENT EXECUTE FUNCTION audit_event_block_changes();
"""

REVERSE = """
DROP TRIGGER IF EXISTS audit_event_no_truncate ON audit_event;
DROP TRIGGER IF EXISTS audit_event_no_update ON audit_event;
DROP FUNCTION IF EXISTS audit_event_block_changes();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
