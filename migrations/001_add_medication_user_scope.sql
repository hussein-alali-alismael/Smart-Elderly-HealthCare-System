-- Add per-user ownership to medication records created by the dashboard.
-- Existing records are assigned to the first seeded administrator.
ALTER TABLE medications ADD COLUMN user_id INT NULL AFTER id;
UPDATE medications SET user_id = (SELECT id FROM users ORDER BY id ASC LIMIT 1) WHERE user_id IS NULL;
CREATE INDEX idx_medications_user_id ON medications (user_id);
