-- Prevent the same device event from creating duplicate incidents.
ALTER TABLE fall_incidents ADD COLUMN evidencePath VARCHAR(500) DEFAULT NULL;
ALTER TABLE fall_incidents ADD COLUMN eventId VARCHAR(128) DEFAULT NULL AFTER evidencePath;
ALTER TABLE fall_incidents ADD UNIQUE KEY uq_fall_incidents_eventId (eventId);